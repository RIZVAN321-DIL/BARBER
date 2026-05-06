import os
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Moscow")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# База для WebApp (будет переопределена через ngrok)
WEBAPP_BASE_URL = os.getenv("WEBAPP_BASE_URL", "http://localhost:5000")
CLIENT_WEBAPP_URL = f"{WEBAPP_BASE_URL}/webapp"
ADMIN_WEBAPP_URL  = f"{WEBAPP_BASE_URL}/admin"

NGROK_AUTH_TOKEN = os.getenv("NGROK_AUTH_TOKEN", "")