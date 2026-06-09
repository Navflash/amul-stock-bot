# Amul High Protein Stock Tracker Bot

A Telegram bot that polls [shop.amul.com](https://shop.amul.com) every 5 minutes and notifies you the moment Amul High Protein products come back in stock for your delivery pincode.

**Tracked products:**
- Amul High Protein Plain Lassi, 200 mL (Pack of 30)
- Amul High Protein Blueberry Shake, 200 mL (Pack of 30)

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

**Prerequisites:** Python 3.12, Docker (optional)

### Without Docker

```bash
git clone https://github.com/Navflash/amul-stock-bot.git
cd amul-stock-bot

python3 -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env and add your BOT_TOKEN from @BotFather on Telegram

python bot.py
```

### With Docker

```bash
cp .env.example .env
# Edit .env and add your BOT_TOKEN

docker build -t amul-bot .
docker run --env-file .env amul-bot
```

Then open your bot on Telegram, send `/setpincode 500046` and you're subscribed.

---

## Deploy on Railway

Railway gives **$5 free credit per month** — enough to run this bot continuously.

### 1. Push to GitHub

```bash
git remote add origin https://github.com/Navflash/amul-stock-bot.git
git push -u origin main
```

### 2. Create Railway project

1. Go to [railway.app](https://railway.app) and sign in with GitHub
2. Click **New Project → Deploy from GitHub repo**
3. Select your repository — Railway will detect the `Dockerfile` automatically

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
3. Every 5 minutes, the bot fetches the protein product catalogue for each subscribed region and checks `available` and `inventory_quantity` fields
4. When a product transitions from out-of-stock to in-stock, all subscribers in that region are notified instantly

State (subscribed users + last known stock status) is saved to `state.json`. On Railway, this resets on each redeploy — subscribers will need to `/setpincode` again after a redeploy.

---

## Tech Stack

- **Python 3.12**
- [python-telegram-bot](https://github.com/python-telegram-bot/python-telegram-bot) v21 — Telegram bot framework
- [aiohttp](https://docs.aiohttp.org) — async HTTP client for Amul shop API
- APScheduler (via `python-telegram-bot[job-queue]`) — repeating stock checks
