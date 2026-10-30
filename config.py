import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN      = os.getenv("BOT_TOKEN", "")
ADMIN_IDS      = [int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x]
SUPPORT_ID     = os.getenv("SUPPORT_ID", "@cytunn")
DB_PATH        = os.getenv("DB_PATH", "bot.db")
VALIDATE_EMOJI = int(os.getenv("VALIDATE_EMOJI", "1"))
WEB_PORT       = int(os.getenv("WEB_PORT", "5000"))
SITE_NAME      = os.getenv("SITE_NAME", "ᴘʀᴇᴍɪᴜᴍ ʙᴏᴛ sᴛᴀᴛs")

DEFAULT_CHANNEL_ID   = "@whymeyarrr"
DEFAULT_CHANNEL_LINK = "https://t.me/whymeyarrr"

# ₹
REFER_REWARD   = 2.0
MIN_WITHDRAW   = 10.0
