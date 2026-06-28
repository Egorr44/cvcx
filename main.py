"""
Polymarket Activity Monitor — Telegram Bot  (v3: multi-wallet + labels)

Each user can track up to MAX_WALLETS_PER_USER wallets, each with a custom name.
Send any 0x… address to add it → bot asks for a name → wallet is saved.

Required env var : BOT_TOKEN
Optional env var : DB_PATH  (default: data/bot.db)
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
from notifications import format_activity, shorten, esc
from polymarket import PolymarketClient

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

POLL_INTERVAL = 60          # seconds between Polymarket checks
MAX_LABEL_LEN = 32          # max characters for a wallet name
_ETH_RE = re.compile(r"^0x[a-fA-F0-9]{40}$", re.I)

# ── Tiny helpers ──────────────────────────────────────────────────────────────

def _db(ctx: ContextTypes.DEFAULT_TYPE) -> Database:
    return ctx.bot_data["db"]

def _client(ctx: ContextTypes.DEFAULT_TYPE) -> PolymarketClient:
    return ctx.bot_data["client"]

def _valid(addr: str) -> bool:
    return bool(_ETH_RE.match(addr.strip()))

def _display(w: dict) -> str:
    """Label if set, otherwise shortened address."""
    return w.get("label") or shorten(w["wallet"])

# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wallets = await _db(ctx).get_wallets(update.effective_chat.id)

    if wallets:
        lines = ["👋 *Polymarket Activity Monitor*\n",
                 f"You're tracking *{len(wallets)}* wallet(s):\n"]
        for i, w in enumerate(wallets, 1):
            lines.append(f"{i}. 🏷 *{esc(w['label'] or '—')}*  `{shorten(w['wallet'])}`")
        lines.append(
            "\nSend any `0x…` address to *add* another wallet.\n\n"
            "/wallets — full list  ·  /rename — rename\n"
            "/remove — delete  ·  /stop — remove all  ·  /help — commands"
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
        "/wallets — List all tracked wallets with names\n"
        "/rename — Rename a wallet\n"
        "/remove — Remove a specific wallet\n"
        "/stop — Remove ALL wallets\n"
        "/skip — Add current wallet without a name\n"
        "/cancel — Cancel current action\n"
        "/help — This message\n\n"
        "💡 *Tip:* Just send any `0x…` address to add it — "
        "the bot will ask you for a name.",
        parse_mode="Markdown",
    )

# ── /cancel ───────────────────────────────────────────────────────────────────

async def cmd_cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    had = bool(
        ctx.user_data.pop("pending_wallet", None)
        or ctx.user_data.pop("pending_rename", None)
    )
    await update.message.reply_text(
        "Cancelled." if had else "Nothing to cancel.",
    )

# ── /skip — add pending wallet without a custom name ─────────────────────────

async def cmd_skip(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wallet = ctx.user_data.pop("pending_wallet", None)
    if not wallet:
        await update.message.reply_text(
            "Nothing pending. Send a wallet address first."
        )
        return

    chat_id = update.effective_chat.id
    now_ts  = int(datetime.now(timezone.utc).timestamp())
    label   = shorten(wallet)          # use short address as display name

    result = await _db(ctx).add_wallet(chat_id, wallet, label, now_ts)
    if result == "added":
        all_w = await _db(ctx).get_wallets(chat_id)
        await update.message.reply_text(
            f"✅ *Wallet added!* ({len(all_w)}/{MAX_WALLETS_PER_USER} slots used)\n\n"
            f"🏷 *{esc(label)}*\n`{wallet}`\n\n"
            "_Send another address to add more, or /wallets to see all._",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Something went wrong. Please try again.")

# ── /wallets ──────────────────────────────────────────────────────────────────

async def cmd_wallets(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wallets = await _db(ctx).get_wallets(update.effective_chat.id)

    if not wallets:
        await update.message.reply_text(
            "No wallets registered. Send a `0x…` address to start.",
            parse_mode="Markdown",
        )
        return

    lines = [f"📋 *Tracking {len(wallets)} of {MAX_WALLETS_PER_USER} wallet(s):*\n"]
    for i, w in enumerate(wallets, 1):
        name = w.get("label") or "—"
        lines.append(f"{i}. 🏷 *{esc(name)}*\n`{w['wallet']}`\n")

    lines.append("/rename — rename  ·  /remove — delete  ·  /stop — remove all")
    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")

# ── /rename ───────────────────────────────────────────────────────────────────

async def cmd_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wallets = await _db(ctx).get_wallets(update.effective_chat.id)
    if not wallets:
        await update.message.reply_text("No wallets to rename. Use /start to add one.")
        return

    keyboard = [
        [InlineKeyboardButton(f"✏️  {_display(w)}", callback_data=f"ren:{w['wallet']}")]
        for w in wallets
    ]
    keyboard.append([InlineKeyboardButton("— Cancel —", callback_data="ren:cancel")])

    await update.message.reply_text(
        "Which wallet do you want to rename?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def cb_rename(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "ren:cancel":
        ctx.user_data.pop("pending_rename", None)
        await query.edit_message_text("Cancelled.")
        return

    wallet = query.data[len("ren:"):]
    ctx.user_data["pending_rename"] = wallet
    ctx.user_data.pop("pending_wallet", None)

    await query.edit_message_text(
        f"Send a new name for this wallet:\n\n`{wallet}`\n\n"
        "_(Or /cancel to abort)_",
        parse_mode="Markdown",
    )

# ── /remove ───────────────────────────────────────────────────────────────────

async def cmd_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    wallets = await _db(ctx).get_wallets(update.effective_chat.id)
    if not wallets:
        await update.message.reply_text("Nothing to remove. Use /start to add a wallet.")
        return

    keyboard = [
        [InlineKeyboardButton(f"❌  {_display(w)}", callback_data=f"rm:{w['wallet']}")]
        for w in wallets
    ]
    keyboard.append([InlineKeyboardButton("— Cancel —", callback_data="rm:cancel")])

    await update.message.reply_text(
        "Which wallet do you want to remove?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )

async def cb_remove(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()

    if query.data == "rm:cancel":
        await query.edit_message_text("Cancelled.")
        return

    wallet  = query.data[len("rm:"):]
    chat_id = query.message.chat_id
    removed = await _db(ctx).remove_wallet(chat_id, wallet)

    if removed:
        remaining = await _db(ctx).get_wallets(chat_id)
        footer = (
            f"Still tracking *{len(remaining)}* wallet(s)." if remaining
            else "No wallets left. Use /start to add one."
        )
        await query.edit_message_text(
            f"✅ Removed: `{wallet}`\n\n{footer}", parse_mode="Markdown"
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
        f"⏹ *Stopped monitoring {len(wallets)} wallet(s).*\n\nUse /start anytime to resume.",
        parse_mode="Markdown",
    )

# ── Text handler: wallet address OR name/rename input ────────────────────────

async def handle_text(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    raw     = update.message.text.strip()
    chat_id = update.effective_chat.id

    # ── 1. Waiting for a name for a newly submitted wallet ────────────────
    if ctx.user_data.get("pending_wallet") and not _valid(raw):
        wallet = ctx.user_data.pop("pending_wallet")
        label  = raw[:MAX_LABEL_LEN].strip()
        now_ts = int(datetime.now(timezone.utc).timestamp())

        result = await _db(ctx).add_wallet(chat_id, wallet, label, now_ts)
        if result == "added":
            has_hist = await _client(ctx).has_history(wallet)
            note = (
                ""
                if has_hist
                else "\n\n⚠️ No prior activity found — I'll alert you on the first event."
            )
            all_w = await _db(ctx).get_wallets(chat_id)
            await update.message.reply_text(
                f"✅ *Wallet added!* ({len(all_w)}/{MAX_WALLETS_PER_USER} slots used)\n\n"
                f"🏷 *{esc(label)}*\n`{wallet}`{note}\n\n"
                "_Send another address to add more, or /wallets to see all._",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text(
                "Something went wrong. Please send the wallet address again."
            )
        return

    # ── 2. Waiting for a new name (rename flow) ───────────────────────────
    if ctx.user_data.get("pending_rename") and not _valid(raw):
        wallet = ctx.user_data.pop("pending_rename")
        label  = raw[:MAX_LABEL_LEN].strip()
        ok = await _db(ctx).update_label(chat_id, wallet, label)
        if ok:
            await update.message.reply_text(
                f"✅ *Renamed!*\n\n🏷 *{esc(label)}*\n`{wallet}`",
                parse_mode="Markdown",
            )
        else:
            await update.message.reply_text("Wallet not found.")
        return

    # ── 3. New wallet address ─────────────────────────────────────────────
    if _valid(raw):
        wallet = raw.lower()

        # Clear any stale pending state
        ctx.user_data.pop("pending_wallet", None)
        ctx.user_data.pop("pending_rename", None)

        current = await _db(ctx).get_wallets(chat_id)
        if any(w["wallet"] == wallet for w in current):
            await update.message.reply_text(
                f"⚠️ Already tracking `{wallet}`\n\n/wallets to see all.",
                parse_mode="Markdown",
            )
            return
        if len(current) >= MAX_WALLETS_PER_USER:
            await update.message.reply_text(
                f"❌ You've reached the limit of *{MAX_WALLETS_PER_USER} wallets*.\n\n"
                "Use /remove to free up a slot.",
                parse_mode="Markdown",
            )
            return

        ctx.user_data["pending_wallet"] = wallet
        await update.message.reply_text(
            f"Got it! Now give this wallet a name:\n\n`{wallet}`\n\n"
            "_(Use /skip to add it without a name, or /cancel to abort)_",
            parse_mode="Markdown",
        )
        return

    # ── 4. Unrecognised text with no pending state → ignore silently ──────

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
            label     = row.get("label") or shorten(wallet)   # fallback for unlabelled
            last_seen = row["last_seen"]

            try:
                events = await poly.get_activity(wallet, last_seen)
                if not events:
                    continue

                latest_ts = max(e["timestamp"] for e in events)
                await database.update_last_seen(row_id, latest_ts)

                for ev in events:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=format_activity(ev, wallet=wallet, label=label),
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                        )
                    except Forbidden:
                        logger.warning("User %s blocked bot; removing their wallets.", chat_id)
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
    await database.init()

    app.bot_data["db"]        = database
    app.bot_data["client"]    = PolymarketClient()
    app.bot_data["poll_task"] = asyncio.create_task(poll_loop(app))
    logger.info("Bot initialised ✓")


async def post_shutdown(app: Application) -> None:
    task = app.bot_data.get("poll_task")
    if task:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    poly = app.bot_data.get("client")
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
    app.add_handler(CommandHandler("rename",  cmd_rename))
    app.add_handler(CommandHandler("remove",  cmd_remove))
    app.add_handler(CommandHandler("stop",    cmd_stop))
    app.add_handler(CommandHandler("skip",    cmd_skip))
    app.add_handler(CommandHandler("cancel",  cmd_cancel))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CallbackQueryHandler(cb_rename, pattern=r"^ren:"))
    app.add_handler(CallbackQueryHandler(cb_remove, pattern=r"^rm:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    logger.info("Starting bot…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
