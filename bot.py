"""
Amul High Protein product stock tracker bot.
Each user sets their own pincode; the bot notifies them when any tracked
product comes back in stock for their delivery region.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

from dotenv import load_dotenv
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CommandHandler, ContextTypes

from amul_client import AmulClient

load_dotenv()

BOT_TOKEN = os.environ["BOT_TOKEN"]
STATE_FILE = Path(os.environ.get("STATE_DIR", ".")) / "state.json"
CHECK_INTERVAL_SECONDS = 300  # every 5 minutes

TRACKED_PRODUCTS = [
    {
        "alias": "amul-high-protein-plain-lassi-200-ml-or-pack-of-30",
        "url": "https://shop.amul.com/en/product/amul-high-protein-plain-lassi-200-ml-or-pack-of-30",
    },
    {
        "alias": "amul-high-protein-blueberry-shake-200-ml-or-pack-of-30",
        "url": "https://shop.amul.com/en/product/amul-high-protein-blueberry-shake-200-ml-or-pack-of-30",
    },
]

class _RedactTokenFilter(logging.Filter):
    _pattern = re.compile(r"bot\d+:[A-Za-z0-9_-]+")

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = self._pattern.sub("bot<REDACTED>", str(record.msg))
        return True


logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
    stream=sys.stdout,
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpx").addFilter(_RedactTokenFilter())
logger = logging.getLogger(__name__)


# ------------------------------------------------------------------ #
# State helpers                                                        #
# ------------------------------------------------------------------ #
# state.json schema:
# {
#   "users": {
#     "<chat_id>": {"pincode": "500046", "substore": "telangana"}
#   },
#   "substore_stock": {
#     "telangana": false
#   }
# }

def _load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text())
    return {"users": {}, "substore_stock": {}}


def _save_state(state: dict):
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _get_user(chat_id: int) -> dict | None:
    return _load_state()["users"].get(str(chat_id))


# ------------------------------------------------------------------ #
# Command handlers                                                     #
# ------------------------------------------------------------------ #

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update.effective_chat.id)
    if user:
        await update.message.reply_text(
            f"👋 Welcome back! You're tracking stock for pincode *{user['pincode']}*.\n\n"
            "/status — check current stock\n"
            "/setpincode — change your pincode\n"
            "/stop — unsubscribe",
            parse_mode="Markdown",
        )
    else:
        await update.message.reply_text(
            "👋 *Amul High Protein Lassi Stock Tracker*\n\n"
            "I'll notify you the moment it comes back in stock for your delivery area.\n\n"
            "To get started, set your pincode:\n"
            "`/setpincode 500046`",
            parse_mode="Markdown",
        )


async def cmd_setpincode(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not ctx.args or not ctx.args[0].isdigit() or len(ctx.args[0]) != 6:
        await update.message.reply_text(
            "Please provide a 6-digit pincode.\n"
            "Example: `/setpincode 500046`",
            parse_mode="Markdown",
        )
        return

    pincode = ctx.args[0]
    chat_id = update.effective_chat.id
    msg = await update.message.reply_text("⏳ Validating pincode…")

    clients: dict[str, AmulClient] = ctx.bot_data["amul_clients"]

    # Create a temporary client just to resolve the pincode → substore
    temp = AmulClient()
    try:
        await temp.init(pincode)
        substore = temp._pincode_record["substore"]
    except ValueError:
        await temp.close()
        await msg.edit_text(
            "❌ Pincode *not found* in Amul's delivery network.\n"
            "Please check the pincode and try again.",
            parse_mode="Markdown",
        )
        return
    except Exception as e:
        logger.error("Pincode validation failed for %s: %s", pincode, e)
        await temp.close()
        await msg.edit_text("⚠️ Could not reach Amul shop. Please try again later.")
        return

    # Reuse an existing session for this substore if we already have one
    if substore in clients:
        await temp.close()
    else:
        clients[substore] = temp

    # Save / update user record
    state = _load_state()
    state["users"][str(chat_id)] = {"pincode": pincode, "substore": substore}
    _save_state(state)

    region = substore.replace("-", " ").title()
    product_list = "\n".join(f"• `{p['alias']}`" for p in TRACKED_PRODUCTS)
    await msg.edit_text(
        f"✅ Pincode set to *{pincode}* ({region})\n\n"
        f"Tracking {len(TRACKED_PRODUCTS)} products:\n{product_list}\n\n"
        "You'll be notified when any of them comes back in stock.\n"
        "Use /status to check right now.",
        parse_mode="Markdown",
    )


async def cmd_stop(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    chat_id = str(update.effective_chat.id)
    state = _load_state()
    if chat_id in state["users"]:
        del state["users"][chat_id]
        _save_state(state)
        await update.message.reply_text(
            "❌ Unsubscribed. You won't receive any more alerts.\n"
            "Use /start to subscribe again."
        )
    else:
        await update.message.reply_text("You are not subscribed.")


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update.effective_chat.id)
    if not user:
        await update.message.reply_text(
            "You haven't set a pincode yet.\nUse `/setpincode 500046` to get started.",
            parse_mode="Markdown",
        )
        return

    clients: dict[str, AmulClient] = ctx.bot_data["amul_clients"]
    client = clients.get(user["substore"])
    if not client:
        await update.message.reply_text(
            "⚠️ No active session for your region. "
            "Try `/setpincode " + user["pincode"] + "` to re-initialise.",
            parse_mode="Markdown",
        )
        return

    msg = await update.message.reply_text("⏳ Checking stock…")
    try:
        all_products = await client.get_protein_products()
    except Exception as e:
        logger.error("Status check failed: %s", e)
        await msg.edit_text("⚠️ Could not reach Amul shop. Please try again later.")
        return

    tracked_aliases = {p["alias"]: p["url"] for p in TRACKED_PRODUCTS}
    found = [p for p in all_products if p.get("alias") in tracked_aliases]

    if not found:
        await msg.edit_text("⚠️ No tracked products found in the catalogue.")
        return

    lines = [f"Pincode: *{user['pincode']}*\n"]
    keyboard_buttons = []
    for product in found:
        available = bool(product.get("available"))
        icon = "✅" if available else "❌"
        label = "IN STOCK" if available else "OUT OF STOCK"
        lines.append(
            f"{icon} *{product['name']}*\n"
            f"   Status: *{label}* | ₹{product.get('price', 0)} | Qty: {product.get('inventory_quantity', 0)}"
        )
        if available:
            keyboard_buttons.append(
                InlineKeyboardButton(f"Buy {product['name'][:20]}… 🛒",
                                     url=tracked_aliases[product["alias"]])
            )

    markup = InlineKeyboardMarkup([[btn] for btn in keyboard_buttons]) if keyboard_buttons else None
    await msg.edit_text("\n".join(lines), parse_mode="Markdown", reply_markup=markup)


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = _get_user(update.effective_chat.id)
    pincode_info = f"Your pincode: `{user['pincode']}`" if user else "Pincode: _not set_"
    await update.message.reply_text(
        "*Amul Stock Tracker Bot*\n\n"
        "/start — Welcome & current status\n"
        "/setpincode `<pincode>` — Set your delivery pincode\n"
        "/status — Check current stock\n"
        "/stop — Unsubscribe from alerts\n"
        "/help — This message\n\n"
        f"{pincode_info}\n"
        "Checks every 5 minutes.",
        parse_mode="Markdown",
    )


# ------------------------------------------------------------------ #
# Background polling job                                               #
# ------------------------------------------------------------------ #

async def _stock_check_job(ctx: ContextTypes.DEFAULT_TYPE):
    clients: dict[str, AmulClient] = ctx.bot_data["amul_clients"]
    state = _load_state()

    # Collect unique substores that have at least one subscriber
    substore_users: dict[str, list[str]] = {}
    for chat_id, user in state["users"].items():
        sub = user.get("substore")
        if sub:
            substore_users.setdefault(sub, []).append(chat_id)

    for substore, chat_ids in substore_users.items():
        client = clients.get(substore)
        if not client:
            logger.warning("No client for substore %r, skipping", substore)
            continue

        # Session reinit disabled — re-enable if sessions expire after long uptime
        # if client.session_age_days > 4:
        #     pincode = state["users"][chat_ids[0]]["pincode"]
        #     logger.info("Reinitialising session for substore %s (pincode %s)", substore, pincode)
        #     try:
        #         await client.reinit(pincode)
        #     except Exception as e:
        #         logger.error("Session reinit failed for %s: %s", substore, e)
        #         continue

        try:
            all_products = await client.get_protein_products()
        except Exception as e:
            logger.error("Stock check failed for substore %s: %s", substore, e)
            continue

        tracked_aliases = {p["alias"]: p["url"] for p in TRACKED_PRODUCTS}
        substore_stock = state.setdefault("substore_stock", {})
        # Migrate old flat bool format to per-product dict if needed
        if not isinstance(substore_stock.get(substore), dict):
            substore_stock[substore] = {}

        for product in all_products:
            alias = product.get("alias")
            if alias not in tracked_aliases:
                continue

            available = bool(product.get("available"))
            was_available = substore_stock[substore].get(alias, False)

            logger.info(
                "[%s][%s] available=%s (was %s), qty=%s",
                substore, alias, available, was_available,
                product.get("inventory_quantity"),
            )

            if available == was_available:
                continue

            substore_stock[substore][alias] = available
            _save_state(state)

            if not available:
                logger.info("[%s][%s] Went out of stock", substore, alias)
                continue

            # --- Back in stock! Notify subscribers ---
            qty = product.get("inventory_quantity", 0)
            price = product.get("price", 0)
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("Buy Now 🛒", url=tracked_aliases[alias])]]
            )
            for chat_id in chat_ids:
                pincode = state["users"][chat_id]["pincode"]
                text = (
                    "🚨 *BACK IN STOCK!*\n\n"
                    f"*{product['name']}*\n"
                    f"Price: ₹{price}\n"
                    f"Qty available: {qty}\n"
                    f"Pincode: {pincode}\n\n"
                    "Hurry — grab it before it sells out!"
                )
                try:
                    await ctx.bot.send_message(
                        int(chat_id), text, parse_mode="Markdown", reply_markup=markup
                    )
                    logger.info("Telegram → stock alert sent to chat %s for %r", chat_id, alias)
                except Exception as e:
                    logger.error("Failed to notify chat %s: %s", chat_id, e)


# ------------------------------------------------------------------ #
# Application lifecycle                                                #
# ------------------------------------------------------------------ #

async def _post_init(app: Application):
    state = _load_state()
    clients: dict[str, AmulClient] = {}

    # Re-create one session per unique substore from saved state
    substore_pincodes: dict[str, str] = {}
    for user in state["users"].values():
        sub = user.get("substore")
        if sub and sub not in substore_pincodes:
            substore_pincodes[sub] = user["pincode"]

    for substore, pincode in substore_pincodes.items():
        logger.info("Restoring session for substore %s (pincode %s)…", substore, pincode)
        client = AmulClient()
        try:
            await client.init(pincode)
            clients[substore] = client
        except Exception as e:
            logger.error("Could not restore session for %s: %s", substore, e)

    app.bot_data["amul_clients"] = clients
    logger.info("Bot ready. %d substore session(s) active.", len(clients))


async def _post_shutdown(app: Application):
    for client in app.bot_data.get("amul_clients", {}).values():
        await client.close()


def main():
    app = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(_post_init)
        .post_shutdown(_post_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("setpincode", cmd_setpincode))
    app.add_handler(CommandHandler("stop", cmd_stop))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("help", cmd_help))

    assert app.job_queue, "Job queue unavailable — install python-telegram-bot[job-queue]"
    app.job_queue.run_repeating(_stock_check_job, interval=CHECK_INTERVAL_SECONDS, first=10)

    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
