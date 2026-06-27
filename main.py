"""
Polymarket Activity Monitor — Telegram Bot

Monitors a Polymarket wallet and sends instant Telegram notifications for:
  • Trades (buy / sell)
  • Liquidity rewards
  • Maker rebates
  • Position redemptions
  • Referral rewards
  • Token splits / merges / conversions

Requires only one environment variable: BOT_TOKEN
"""

import asyncio
import logging
import os
import re
from datetime import datetime, timezone

from telegram import Update
from telegram.error import BadRequest, Forbidden
from telegram.ext import (
    Application,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import Database
from notifications import format_activity
from polymarket import PolymarketClient

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────────────────────

AWAIT_WALLET  = 1                   # ConversationHandler state
POLL_INTERVAL = 60                  # seconds between Polymarket checks
_ETH_RE       = re.compile(r"^0x[a-fA-F0-9]{40}$", re.I)

# ── Tiny helpers ─────────────────────────────────────────────────────────────

def _db(ctx: ContextTypes.DEFAULT_TYPE) -> Database:
    return ctx.bot_data["db"]

def _client(ctx: ContextTypes.DEFAULT_TYPE) -> PolymarketClient:
    return ctx.bot_data["client"]

def _valid(addr: str) -> bool:
    return bool(_ETH_RE.match(addr.strip()))

# ── Bot command handlers ──────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    user = await _db(ctx).get_user(update.effective_chat.id)

    if user:
        text = (
            "👋 *Polymarket Activity Monitor*\n\n"
            f"Currently tracking:\n`{user['wallet']}`\n\n"
            "Send a new wallet address to update it, or use:\n"
            "/status — Show monitored wallet\n"
            "/stop — Stop monitoring\n"
            "/help — All commands\n\n"
            "_To change wallet, send its address now:_"
        )
    else:
        text = (
            "👋 *Welcome to Polymarket Activity Monitor!*\n\n"
            "I send instant notifications whenever your Polymarket account sees:\n\n"
            "🔄 *Trade executed* — buy or sell order filled\n"
            "🏆 *Liquidity reward* — reward for providing liquidity\n"
            "💎 *Maker rebate* — rebate credited for maker orders\n"
            "💰 *Redemption* — winning position paid out\n"
            "🤝 *Referral reward* — reward from referred trader\n"
            "✂️ *Split / Merge / Conversion* — token operations\n\n"
            "──────────────────────\n"
            "To get started, send me your *Polymarket wallet address*.\n\n"
            "ℹ️ You can find it on your Polymarket profile page "
            "(top-right corner → Profile). It starts with `0x`."
        )

    await update.message.reply_text(text, parse_mode="Markdown")
    return AWAIT_WALLET


async def recv_wallet(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    raw = update.message.text.strip()

    if not _valid(raw):
        await update.message.reply_text(
            "❌ *Invalid address format.*\n\n"
            "A Polymarket wallet address looks like this:\n"
            "`0x56687bf447db6ffa42ffe2204a05edaa20f55839`\n\n"
            "Please send the address from your Polymarket profile and try again:",
            parse_mode="Markdown",
        )
        return AWAIT_WALLET

    wallet  = raw.lower()
    chat_id = update.effective_chat.id
    now_ts  = int(datetime.now(timezone.utc).timestamp())

    await _db(ctx).upsert_user(chat_id, wallet, now_ts)

    has_hist = await _client(ctx).has_history(wallet)
    note = (
        ""
        if has_hist
        else (
            "\n\n⚠️ No previous activity found for this wallet — "
            "I'll alert you as soon as the first event occurs."
        )
    )

    await update.message.reply_text(
        f"✅ *Monitoring started!*\n\n"
        f"📍 Wallet: `{wallet}`\n"
        f"🔔 You'll receive a notification for every new event.{note}\n\n"
        "_Use /stop to stop or /start to change wallet._",
        parse_mode="Markdown",
    )
    return ConversationHandler.END


async def cancel(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Cancelled. Use /start anytime.")
    return ConversationHandler.END


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    user = await _db(ctx).get_user(update.effective_chat.id)
    if user:
        await update.message.reply_text(
            f"📍 *Currently monitoring:*\n`{user['wallet']}`\n\n"
            "_Use /stop to stop or /start to change wallet._",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "No wallet registered. Use /start to begin monitoring."
        )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    chat_id = update.effective_chat.id
    if await _db(ctx).get_user(chat_id):
        await _db(ctx).delete_user(chat_id)
        await update.message.reply_text(
            "⏹ *Monitoring stopped.*\n\nUse /start to resume anytime.",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text("Nothing to stop. Use /start to begin.")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "🤖 *Polymarket Activity Monitor*\n\n"
        "*Commands:*\n"
        "/start — Set up or change wallet monitoring\n"
        "/status — Show currently monitored wallet\n"
        "/stop — Stop monitoring\n"
        "/help — This help message\n\n"
        "ℹ️ The bot polls Polymarket every 60 seconds for new activity.",
        parse_mode="Markdown",
    )

# ── Background polling loop ───────────────────────────────────────────────────

async def poll_loop(app: Application) -> None:
    """
    Runs forever, polling Polymarket activity for every registered wallet.
    Sends Telegram notifications for any events newer than last_seen.
    """
    database: Database        = app.bot_data["db"]
    poly:     PolymarketClient = app.bot_data["client"]

    logger.info("Polling loop started (interval = %ds)", POLL_INTERVAL)

    while True:
        users = await database.all_users()
        logger.debug("Polling %d user(s)…", len(users))

        for u in users:
            chat_id   = u["chat_id"]
            wallet    = u["wallet"]
            last_seen = u["last_seen"]

            try:
                events = await poly.get_activity(wallet, last_seen)
                if not events:
                    continue

                # Update cursor BEFORE sending so a crash doesn't re-notify
                latest_ts = max(e["timestamp"] for e in events)
                await database.update_last_seen(chat_id, latest_ts)

                for ev in events:
                    try:
                        await app.bot.send_message(
                            chat_id=chat_id,
                            text=format_activity(ev),
                            parse_mode="Markdown",
                            disable_web_page_preview=True,
                        )
                    except Forbidden:
                        # User blocked the bot — clean up
                        logger.warning("User %s blocked the bot; removing.", chat_id)
                        await database.delete_user(chat_id)
                        break
                    except BadRequest as exc:
                        logger.error("BadRequest sending to %s: %s", chat_id, exc)
                    except Exception as exc:
                        logger.error("Unexpected send error to %s: %s", chat_id, exc)

                    await asyncio.sleep(0.3)   # ~3 msgs/sec max

            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Poll error wallet=%s…: %s", wallet[:10], exc)

            await asyncio.sleep(0.5)   # small gap between users

        await asyncio.sleep(POLL_INTERVAL)

# ── App lifecycle ─────────────────────────────────────────────────────────────

async def post_init(app: Application) -> None:
    db_path = os.getenv("DB_PATH", "data/bot.db")
    db_dir  = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    database = Database(db_path)
    await database.init()

    app.bot_data["db"]     = database
    app.bot_data["client"] = PolymarketClient()

    task = asyncio.create_task(poll_loop(app))
    app.bot_data["poll_task"] = task
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
        raise SystemExit("ERROR: BOT_TOKEN environment variable is not set.")

    app = (
        Application.builder()
        .token(token)
        .post_init(post_init)
        .post_shutdown(post_shutdown)
        .build()
    )

    # Conversation: /start → user sends wallet → done
    conv = ConversationHandler(
        entry_points=[CommandHandler("start", cmd_start)],
        states={
            AWAIT_WALLET: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, recv_wallet),
            ]
        },
        fallbacks=[
            CommandHandler("cancel", cancel),
            CommandHandler("stop",   cmd_stop),
            CommandHandler("status", cmd_status),
            CommandHandler("help",   cmd_help),
        ],
        allow_reentry=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("stop",   cmd_stop))
    app.add_handler(CommandHandler("help",   cmd_help))

    logger.info("Starting Polymarket bot…")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
