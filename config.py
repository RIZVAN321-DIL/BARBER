import os

# Токен бота от @BotFather (обязательно)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID администратора (парикмахера)
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Номер телефона мастера (для напоминаний и связи)
MASTER_PHONE = os.getenv("MASTER_PHONE", "+7 (900) 123-45-67")

# Гибкий график работы: с 9:00 до 18:00, шаг 60 минут.
# Можно изменить по желанию.
WORK_START_HOUR = 9
WORK_END_HOUR = 18
WORK_SLOT_MINUTES = 60

# Автоматически генерируем список слотов (например, "09:00-10:00", "10:00-11:00", ...)
WORK_SLOTS = []
for h in range(WORK_START_HOUR, WORK_END_HOUR):
    start = f"{h:02d}:00"
    end = f"{h+1:02d}:00"
    WORK_SLOTS.append(f"{start}-{end}")