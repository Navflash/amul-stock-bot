# Amul High Protein Stock Tracker Bot

A Telegram bot that checks [shop.amul.com](https://shop.amul.com) for Amul High Protein products and notifies you the moment they come back in stock for your delivery pincode.

**Tracked products:**
- Amul High Protein Plain Lassi, 200 mL (Pack of 30)
- Amul High Protein Blueberry Shake, 200 mL (Pack of 30)

**Check schedule:** 9:00 AM, 11:00 AM, 1:00 PM, 7:00 PM IST daily.

---

## Bot Commands

| Command | Description |
|---|---|
| `/start` | Welcome message |
| `/setpincode 500046` | Set your delivery pincode (required before alerts work) |
| `/status` | Check current stock for your pincode |
| `/stop` | Unsubscribe from alerts |
| `/help` | Show all commands |

---

## Local Setup

**Prerequisites:** Python 3.10+

```bash
git clone https://github.com/your-username/amul-stock-bot.git
cd amul-stock-bot

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your BOT_TOKEN from @BotFather on Telegram

python bot.py
```

Then open your bot on Telegram, send `/setpincode 500046` and you're subscribed.

---

## Deploy on Railway (Free)

Railway gives **$5 free credit per month** — enough to run this bot continuously.

### 1. Push to GitHub

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/your-username/amul-stock-bot.git
git push -u origin main
```

### 2. Create Railway project

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your `amul-stock-bot` repository
4. Railway will detect the `Procfile` and configure automatically

### 3. Set environment variables

In your Railway project, go to **Variables** and add:

| Variable | Value |
|---|---|
| `BOT_TOKEN` | Your token from @BotFather |

### 4. Deploy

Railway deploys automatically on every push to `main`. Check the **Logs** tab to confirm the bot started:

```
Bot ready. 0 substore session(s) active.
Application started
```

### 5. Start using it

Open your bot on Telegram and send `/setpincode 500046`.

---

## How It Works

1. On `/setpincode`, the bot calls the Amul shop API to resolve your pincode to a delivery region (e.g. Telangana)
2. A session is created for that region with the correct store preferences
3. At each scheduled time, the bot fetches the protein product catalogue for your region and checks `available` and `inventory_quantity` fields
4. When a product transitions from out-of-stock to in-stock, all subscribers in that region are notified instantly

State (subscribed users + last known stock status) is saved to `state.json` locally. On Railway, this resets on each redeploy — subscribers will need to `/setpincode` again after a redeploy. For persistence across deploys, consider adding a Railway Postgres or Redis add-on.

---

## Tech Stack

- **Python 3.10+**
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v21 — Telegram bot framework
- [aiohttp](https://docs.aiohttp.org) — async HTTP client for Amul shop API
- APScheduler (via `python-telegram-bot[job-queue]`) — scheduled stock checks
