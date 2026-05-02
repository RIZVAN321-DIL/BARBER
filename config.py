import os
from zoneinfo import ZoneInfo

TIMEZONE = ZoneInfo("Europe/Moscow")

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
MASTER_PHONE = os.getenv("MASTER_PHONE", "+7 (900) 123-45-67")

# График работы: 8:00 – 17:00 (слоты по 1 часу)
WORK_START_HOUR = 8
WORK_END_HOUR = 17
WORK_SLOT_MINUTES = 60

WORK_SLOTS = []
for h in range(WORK_START_HOUR, WORK_END_HOUR):
    start = f"{h:02d}:00"
    end = f"{h+1:02d}:00"
    WORK_SLOTS.append(f"{start}-{end}")

# Символ для заблокированной даты (если ❌ обрезается – замените на "🚫")
BLOCK_SYMBOL = "❌"