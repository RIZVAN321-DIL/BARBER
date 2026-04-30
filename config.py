import os

# Токен бота от @BotFather (обязательно задать в переменных окружения)
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID администратора (парикмахера), узнать у @userinfobot
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# Номер телефона мастера (для напоминаний и связи)
MASTER_PHONE = os.getenv("MASTER_PHONE", "+7 (900) 123-45-67")