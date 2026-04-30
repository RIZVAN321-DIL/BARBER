import os
# Токен бота от @BotFather
BOT_TOKEN = os.getenv("BOT_TOKEN", "")

# ID администратора (парикмахера), узнать у @userinfobot
ADMIN_ID = int(os.getenv("ADMIN_ID",0))

# Телефон мастера (для напоминаний и связи)
MASTER_PHONE = os.getenv("MASTER_PHONE", "")
