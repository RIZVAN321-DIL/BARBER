import os
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Moscow")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# WebApp для клиента (размести webapp.html на любом HTTPS-хостинге)
CLIENT_WEBAPP_URL = os.getenv("CLIENT_WEBAPP_URL", "")