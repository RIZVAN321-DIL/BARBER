import os
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Moscow")
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
CLIENT_WEBAPP_URL = os.getenv("CLIENT_WEBAPP_URL", "")
MAX_SLOTS_PER_DAY = int(os.getenv("MAX_SLOTS_PER_DAY", 0))