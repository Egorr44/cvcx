"""
Formats Polymarket activity events into clean Telegram messages.

Supported types: TRADE, REWARD, MAKER_REBATE, REDEEM, REFERRAL_REWARD,
                 SPLIT, MERGE, CONVERSION
"""

from datetime import datetime, timezone
from typing import Any, Dict

# ── Labels & icons ────────────────────────────────────────────────────────────

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

# ── Helpers ───────────────────────────────────────────────────────────────────

def _esc(text: str) -> str:
    """Escape Telegram Markdown special characters in user-supplied strings."""
    for ch in ("*", "_", "`", "[", "]"):
        text = text.replace(ch, f"\\{ch}")
    return text


def _fmt_ts(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d, %Y  %H:%M UTC")


# ── Main formatter ────────────────────────────────────────────────────────────

def format_activity(a: Dict[str, Any]) -> str:
    """Return a Markdown-formatted message for a single Polymarket activity."""
    atype  = a.get("type", "UNKNOWN")
    icon   = _ICON.get(atype,  "📌")
    label  = _LABEL.get(atype, atype)
    title  = _esc(a.get("title") or "Unknown Market")
    outcome = a.get("outcome") or ""
    ts     = a.get("timestamp", 0)

    lines = [
        f"{icon} *{label}*",
        f"📊 {title}",
    ]

    # ── Per-type fields ───────────────────────────────────────────────────
    if atype == "TRADE":
        side    = a.get("side", "")
        price   = a.get("price")
        size    = a.get("size")
        usdc    = a.get("usdcSize")

        side_mark = "🟢 BUY" if side == "BUY" else "🔴 SELL"
        outcome_txt = f"  ·  {outcome}" if outcome else ""
        lines.append(f"{side_mark}{outcome_txt}")

        if price is not None:
            lines.append(f"💲 Price: *${price:.3f}*")
        if size is not None:
            lines.append(f"📦 Shares: {size:.2f}")
        if usdc is not None:
            lines.append(f"💵 USDC value: *${usdc:.2f}*")

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

    elif atype in ("SPLIT", "MERGE"):
        usdc = a.get("usdcSize")
        size = a.get("size")
        if usdc is not None:
            lines.append(f"💵 USDC: ${usdc:.2f}")
        if size is not None:
            lines.append(f"📦 Tokens: {size:.2f}")

    elif atype == "CONVERSION":
        usdc = a.get("usdcSize")
        if usdc is not None:
            lines.append(f"💵 USDC: ${usdc:.2f}")

    # ── Footer ────────────────────────────────────────────────────────────
    lines.append(f"\n⏰ {_fmt_ts(ts)}")

    tx = a.get("transactionHash")
    if tx:
        lines.append(f"[View on Polygonscan](https://polygonscan.com/tx/{tx})")

    slug = a.get("eventSlug") or a.get("slug")
    if slug:
        lines.append(f"[Open on Polymarket](https://polymarket.com/event/{slug})")

    return "\n".join(lines)
