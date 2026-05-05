import os
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Moscow")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
MASTER_PHONE = os.getenv("MASTER_PHONE", "+7 (900) 123-45-67")

WORK_START_HOUR = 9
WORK_END_HOUR = 19
WORK_SLOT_MINUTES = 60
WORK_SLOTS = [f"{h:02d}:00-{(h+1):02d}:00" for h in range(WORK_START_HOUR, WORK_END_HOUR)]

BLOCK_SYMBOL = "❌"

SERVICES = ["Стрижка", "Борода", "Стрижка + Борода"]

# ⚠️ ЗАМЕНИТЕ НА РЕАЛЬНЫЕ HTTPS-АДРЕСА ВАШИХ WEBAPP
CLIENT_WEBAPP_URL = "https://ваш-домен.com/webapp.html"
ADMIN_WEBAPP_URL = "https://ваш-домен.com/admin.html"