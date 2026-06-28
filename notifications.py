"""
Formats Polymarket activity events into Telegram messages.
"""

from datetime import datetime, timezone
from typing import Any, Dict

_ICON = {
    "TRADE":           "🔄",
    "SPLIT":           "✂️",
    "MERGE":           "🔗",
    "REDEEM":          "💰",
    "REWARD":          "🏆",
    "CONVERSION":      "🔄",
    "MAKER_REBATE":    "💎",
    "REFERRAL_REWARD": "🤝",
}

_LABEL = {
    "TRADE":           "Trade Executed",
    "SPLIT":           "Tokens Split",
    "MERGE":           "Tokens Merged",
    "REDEEM":          "Position Redeemed",
    "REWARD":          "Liquidity Reward",
    "CONVERSION":      "Token Conversion",
    "MAKER_REBATE":    "Maker Rebate",
    "REFERRAL_REWARD": "Referral Reward",
}


def shorten(addr: str) -> str:
    """0x1234…abcd"""
    return f"{addr[:6]}…{addr[-4:]}"


def esc(text: str) -> str:
    """Escape Telegram Markdown special characters in user-supplied strings."""
    for ch in ("*", "_", "`", "[", "]"):
        text = text.replace(ch, f"\\{ch}")
    return text


def _fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d, %Y  %H:%M UTC")


def format_activity(a: Dict[str, Any], wallet: str = "", label: str = "") -> str:
    """
    Return a Markdown-formatted Telegram message for one activity event.

    First line is always the wallet identifier:
      - label  → 👛 *My Wallet Name*
      - no label → 👛 `0x1234…abcd`
    """
    atype    = a.get("type", "UNKNOWN")
    icon     = _ICON.get(atype, "📌")
    ev_label = _LABEL.get(atype, atype)
    title    = esc(a.get("title") or "Unknown Market")
    outcome  = a.get("outcome") or ""
    ts       = a.get("timestamp", 0)

    lines = []

    # ── First line: wallet name / address ─────────────────────────────────
    if label:
        lines.append(f"👛 *{esc(label)}*")
    elif wallet:
        lines.append(f"👛 `{shorten(wallet)}`")

    # ── Event type ────────────────────────────────────────────────────────
    lines.append(f"{icon} *{ev_label}*")
    lines.append(f"📊 {title}")

    # ── Per-type details ──────────────────────────────────────────────────
    if atype == "TRADE":
        side  = a.get("side", "")
        price = a.get("price")
        size  = a.get("size")
        usdc  = a.get("usdcSize")

        side_mark   = "🟢 BUY" if side == "BUY" else "🔴 SELL"
        outcome_txt = f"  ·  {outcome}" if outcome else ""
        lines.append(f"{side_mark}{outcome_txt}")
        if price is not None:
            lines.append(f"💲 Price: *${price:.3f}*")
        if size is not None:
            lines.append(f"📦 Shares: {size:.2f}")
        if usdc is not None:
            lines.append(f"💵 USDC: *${usdc:.2f}*")

    elif atype in ("REWARD", "MAKER_REBATE", "REFERRAL_REWARD"):
        usdc = a.get("usdcSize")
        size = a.get("size")
        if usdc is not None and usdc > 0:
            lines.append(f"💰 Amount: *${usdc:.4f} USDC*")
        elif size is not None:
            lines.append(f"💰 Tokens: {size:.4f}")

    elif atype == "REDEEM":
        usdc = a.get("usdcSize")
        if outcome:
            lines.append(f"🎯 Winning outcome: *{outcome}*")
        if usdc is not None:
            lines.append(f"💵 Received: *${usdc:.2f} USDC*")

    elif atype in ("SPLIT", "MERGE", "CONVERSION"):
        usdc = a.get("usdcSize")
        size = a.get("size")
        if usdc is not None:
            lines.append(f"💵 USDC: ${usdc:.2f}")
        if size is not None:
            lines.append(f"📦 Tokens: {size:.2f}")

    # ── Footer ────────────────────────────────────────────────────────────
    lines.append(f"\n⏰ {_fmt_ts(ts)}")

    tx = a.get("transactionHash")
    if tx:
        lines.append(f"[View on Polygonscan](https://polygonscan.com/tx/{tx})")

    slug = a.get("eventSlug") or a.get("slug")
    if slug:
        lines.append(f"[Open on Polymarket](https://polymarket.com/event/{slug})")

    return "\n".join(lines)
