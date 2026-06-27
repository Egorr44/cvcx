"""
Polymarket Activity Monitor — Telegram Bot  (v2: multi-wallet)

Each Telegram user can track up to MAX_WALLETS_PER_USER wallets.
Just send any 0x… address to add it; use /remove to delete individual wallets.

Required env var: BOT_TOKEN
Optional env var: DB_PATH   (default: data/bot.db)
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import Database, MAX_WALLETS_PER_USER
from notifications import format_activity, shorten
from polymarket import PolymarketClient

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 60
_ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$", re.I)

# ── Tiny helpers ──────────────────────────────────────────────────────────────

def _db(ctx: ContextTypes.DEFAULT_TYPE) -> Database:
    return ctx.bot_data["db"]

def _client(ctx: ContextTypes.DEFAULT_TYPE) -> PolymarketClient:
    return ctx.bot_data["client"]

def _valid(addr: str) -> bool:
    return bool(_ETH_RE.match(addr.strip()))

# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    wallets = await _db(ctx).get_wallets(chat_id)

    if wallets:
        lines = ["👋 *Polymarket Activity Monitor*\n"]
        lines.append(f"You're tracking *{len(wallets)}* wallet(s):\n")
        for i, w in enumerate(wallets, 1):
            lines.append(f"{i}. `{w['wallet']}`")
        lines.append(
            "\nSend any `0x…` address to *add* another wallet.\n\n"
            "/wallets — see full list\n"
            "/remove — remove a wallet\n"
            "/stop — remove all wallets\n"
            "/help — all commands"
        )
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    else:
        await update.message.reply_text(
            "👋 *Welcome to Polymarket Activity Monitor!*\n\n"
            "I send instant notifications when your Polymarket account sees:\n\n"
            "🔄 *Trade* — buy or sell order filled\n"
            "🏆 *Liquidity reward* — daily reward for providing liquidity\n"
            "💎 *Maker rebate* — rebate for maker orders\n"
            "💰 *Redemption* — winning position paid out\n"
            "🤝 *Referral reward* — reward from referred trader\n\n"
            "──────────────────────\n"
            "To start, *send me a Polymarket wallet address* (0x…).\n\n"
            "You can find it on your Polymarket profile page.\n"
            "You can add up to *10 wallets* per account.",
            parse_mode="Markdown",
        )

# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Polymarket Activity Monitor*\n\n"
        "*Commands:*\n"
        "/start — Welcome & wallet overview\n"
        "/wallets — List all tracked wallets\n"
        "/remove — Remove a specific wallet\n"
        "/stop — Remove ALL wallets (stop all monitoring)\n"
        "/help — This message\n\n"
        "💡 *Tip:* Just send any `0x…` address to add it.\n"
        "You can track up to *10 wallets* simultaneously.",
        parse_mode="Markdown",
    )

# ── /wallets ──────────────────────────────────────────────────────────────────

async def cmd_wallets(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wallets = await _db(ctx).get_wallets(update.effective_chat.id)

    if not wallets:
        await update.message.reply_text(
            "No wallets registered. Send a `0x…` address to start.",
            parse_mode="Markdown",
        )
        return

    lines = [f"📋 *Tracking {len(wallets)} of {MAX_WALLETS_PER_USER} wallets:*\n"]
    for i, w in enumerate(wallets, 1):
        lines.append(f"{i}. `{w['wallet']}`")
    lines.append("\n/remove — remove a wallet\n/stop — remove all")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ── /remove ───────────────────────────────────────────────────────────────────

async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wallets = await _db(ctx).get_wallets(update.effective_chat.id)

    if not wallets:
        await update.message.reply_text("Nothing to remove. Use /start to add a wallet.")
        return

    keyboard = [
        [InlineKeyboardButton(
            f"❌  {shorten(w['wallet'])}",
            callback_data=f"rm:{w['wallet']}",
        )]
        for w in wallets
    ]
    keyboard.append([InlineKeyboardButton("— Cancel —", callback_data="rm:cancel")])

    await update.message.reply_text(
        "Which wallet do you want to remove?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def handle_remove_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    data = query.data  # "rm:0x…" or "rm:cancel"
    if data == "rm:cancel":
        await query.edit_message_text("Cancelled.")
        return

    wallet  = data[len("rm:"):]
    chat_id = query.message.chat_id
    removed = await _db(ctx).remove_wallet(chat_id, wallet)

    if removed:
        remaining = await _db(ctx).get_wallets(chat_id)
        count_txt = (
            f"Still tracking *{len(remaining)}* wallet(s)."
            if remaining
            else "No wallets left. Use /start to add one."
        )
        await query.edit_message_text(
            f"✅ Removed: `{wallet}`\n\n{count_txt}",
            parse_mode="Markdown",
        )
    else:
        await query.edit_message_text("Wallet not found (already removed?).")

# ── /stop ─────────────────────────────────────────────────────────────────────

async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    wallets = await _db(ctx).get_wallets(chat_id)

    if not wallets:
        await update.message.reply_text("Nothing to stop. Use /start to begin.")
        return

    await _db(ctx).remove_all_wallets(chat_id)
    await update.message.reply_text(
        f"⏹ *Stopped monitoring {len(wallets)} wallet(s).*\n\n"
        "Use /start anytime to resume.",
        parse_mode="Markdown",
    )

# ── Text handler: add wallet when user sends 0x… ─────────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    raw = update.message.text.strip()
    if not _valid(raw):
        # Not a wallet address — ignore silently
        # (avoids spamming error messages on normal conversation)
        return

    wallet  = raw.lower()
    chat_id = update.effective_chat.id
    now_ts  = int(datetime.now(timezone.utc).timestamp())

    result = await _db(ctx).add_wallet(chat_id, wallet, now_ts)

    if result == "exists":
        await update.message.reply_text(
            f"⚠️ Already monitoring `{wallet}`\n\n"
            "Use /wallets to see all tracked wallets.",
            parse_mode="Markdown",
        )
        return

    if result == "limit":
        await update.message.reply_text(
            f"❌ You've reached the limit of *{MAX_WALLETS_PER_USER} wallets*.\n\n"
            "Use /remove to free up a slot.",
            parse_mode="Markdown",
        )
        return

    # result == "added"
    has_hist = await _client(ctx).has_history(wallet)
    note = (
        ""
        if has_hist
        else "\n\n⚠️ No prior activity found — I'll alert you when the first event occurs."
    )

    all_wallets = await _db(ctx).get_wallets(chat_id)
    count = len(all_wallets)
    slot_txt = f"{count}/{MAX_WALLETS_PER_USER}"

    await update.message.reply_text(
        f"✅ *Wallet added!* ({slot_txt} slots used)\n\n"
        f"`{wallet}`{note}\n\n"
        "_Send another address to add more, or /wallets to see all._",
        parse_mode="Markdown",
    )

# ── Background poll loop ──────────────────────────────────────────────────────

async def poll_loop(app: Application) -> None:
    database: Database         = app.bot_data["db"]
    poly:     PolymarketClient = app.bot_data["client"]

    logger.info("Poll loop started (interval=%ds)", POLL_INTERVAL)

    while True:
        rows = await database.all_wallets()
        logger.debug("Polling %d wallet row(s)…", len(rows))

        for row in rows:
            row_id    = row["id"]
            chat_id   = row["chat_id"]
            wallet    = row["wallet"]
            last_seen = row["last_seen"]

            try:
                events = await poly.get_activity(wallet, last_seen)
                if not events:
                    continue

                latest_ts = max(e["timestamp"] for e in events)
                await database.update_last_seen(row_id, latest_ts)

                # Count wallets for this user to decide whether to show wallet label
                user_wallet_count = len(await database.get_wallets(chat_id))

                for ev in events:
                    # Only show wallet label if user tracks multiple wallets
                    wallet_label = wallet if user_wallet_count > 1 else ""
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=format_activity(ev, wallet=wallet_label),
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                        )
                    except Forbidden:
                        logger.warning("User %s blocked bot; removing all their wallets.", chat_id)
                        await database.remove_all_wallets(chat_id)
                        break
                    except BadRequest as exc:
                        logger.error("BadRequest to %s: %s", chat_id, exc)
                    except Exception as exc:
                        logger.error("Send error to %s: %s", chat_id, exc)

                    await asyncio.sleep(0.3)

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Poll error wallet=%s: %s", shorten(wallet), exc)

            await asyncio.sleep(0.5)

        await asyncio.sleep(POLL_INTERVAL)

# ── App lifecycle ─────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    db_path = os.getenv("DB_PATH", "data/bot.db")
    db_dir  = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    database = Database(db_path)
    await database.init()        # also runs migration if needed

    app.bot_data["db"]        = database
    app.bot_data["client"]    = PolymarketClient()
    app.bot_data["poll_task"] = asyncio.create_task(poll_loop(app))
    logger.info("Bot initialised ✓")


async def post_shutdown(app: Application) -> None:
    task: asyncio.Task | None = app.bot_data.get("poll_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    poly: PolymarketClient | None = app.bot_data.get("client")
    if poly:
        await poly.close()

# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("ERROR: BOT_TOKEN is not set.")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("wallets", cmd_wallets))
    app.add_handler(CommandHandler("remove",  cmd_remove))
    app.add_handler(CommandHandler("stop",    cmd_stop))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CallbackQueryHandler(handle_remove_callback, pattern=r"^rm:"))
    # Catch all text messages that look like wallet addresses
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting bot…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
