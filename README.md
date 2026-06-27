# 🤖 Polymarket Activity Monitor Bot

A Telegram bot that monitors any Polymarket wallet and sends real-time notifications for every balance-changing event.

## What it notifies you about

| Event | Trigger |
|-------|---------|
| 🔄 **Trade** | A buy or sell order is filled |
| 🏆 **Liquidity Reward** | Daily reward for providing liquidity |
| 💎 **Maker Rebate** | Rebate credited for maker orders |
| 💰 **Redemption** | Winning position paid out after resolution |
| 🤝 **Referral Reward** | Reward from a referred trader |
| ✂️ **Split / Merge** | Token split or merge operation |

---

## Prerequisites

- A **Telegram Bot Token** (free, from @BotFather)
- A **Railway account** (railway.app — Hobby plan at $5/month recommended for 24/7 uptime)
- A **GitHub account** (to host the code)

> ℹ️ No Polymarket API key needed — the bot uses Polymarket's public API.

---

## Step 1 — Create the Telegram Bot

1. Open Telegram and start a chat with **@BotFather**
2. Send `/newbot`
3. Choose a name (e.g. `My Polymarket Monitor`)
4. Choose a username ending in `bot` (e.g. `mypolymonitor_bot`)
5. Copy the **token** — it looks like `123456789:AABBCCDDaabbccdd_XYZ`

---

## Step 2 — Push code to GitHub

1. Create a new **private** GitHub repository
2. Push all files from this folder:

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

---

## Step 3 — Deploy to Railway

1. Go to [railway.app](https://railway.app) and log in
2. Click **New Project → Deploy from GitHub repo**
3. Select your repository
4. Railway will detect the Dockerfile automatically

### Set the environment variable

In your Railway project:
- Go to your service → **Variables** tab
- Add: `BOT_TOKEN` = *(paste your token from Step 1)*

### (Recommended) Add a persistent volume

Without a volume, the database resets if Railway redeploys your container.

- In your service → **Volumes** tab → **Add Volume**
- Mount path: `/data`
- This ensures registered wallets survive restarts

### Deploy

Click **Deploy** (or it triggers automatically on push). Done!

---

## Bot commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + prompt for wallet address |
| `/status` | Show currently monitored wallet |
| `/stop` | Stop monitoring |
| `/help` | List all commands |

---

## User flow

1. User opens the bot and sees a welcome message explaining what it does
2. User sends their **Polymarket wallet address** (from their Profile page, starts with `0x`)
3. Bot validates the address and confirms monitoring has started
4. From that moment on, the bot checks every 60 seconds and sends a notification for each new event

---

## Running locally (optional)

```bash
# Clone / copy files, then:
pip install -r requirements.txt

# Create .env from the example
cp .env.example .env
# Edit .env and set BOT_TOKEN=your_token_here

# Run
python main.py
```

---

## Architecture

```
main.py          ← Telegram bot handlers + background polling loop
database.py      ← Async SQLite wrapper (stores chat_id → wallet mapping)
polymarket.py    ← Calls Polymarket public Data API (/activity endpoint)
notifications.py ← Formats activity events into Telegram messages
```

The polling loop runs as an asyncio task alongside the Telegram bot.
Every 60 seconds it fetches new activity for each registered wallet
and sends Telegram messages for any events newer than `last_seen`.

---

## Troubleshooting

**Bot doesn't start on Railway**
→ Check the **Logs** tab. Most likely `BOT_TOKEN` is not set.

**Wallet shows "no previous activity"**
→ Normal for new wallets. Notifications will arrive with the first event.

**I'm getting notifications for old events**
→ Impossible by design — the bot sets `last_seen` to *now* when you register,
  so only future events trigger notifications.

**Database resets after redeploy**
→ Add a Railway Volume mounted at `/data` (see Step 3).
