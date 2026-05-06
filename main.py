import asyncio
import logging
import threading
import os
import re
from pyngrok import ngrok
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, ADMIN_ID, TIMEZONE, NGROK_AUTH_TOKEN, WEBAPP_BASE_URL
from database import (
    init_db, get_all_barbers, get_barber, get_all_services, get_service,
    get_free_slots, book_slot, get_user_orders, get_all_future_orders,
    cancel_order, get_order_by_id, is_user_banned, ban_user, unban_user,
    get_orders_for_today, get_orders_for_tomorrow,
    get_orders_for_reminder_24h, mark_reminder_sent, get_active_order_count
)
from keyboards import (
    main_menu, admin_menu, barbers_keyboard, services_keyboard,
    calendar_keyboard, slots_keyboard, confirm_kb, phone_kb,
    cancel_order_inline
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

def now_moscow():
    return datetime.now(TIMEZONE)

def format_date(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")

class BookingState(StatesGroup):
    barber = State()
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()
    ready = State()

# ================== ОБРАБОТЧИКИ КОМАНД ==================
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        await message.answer("❌ Вы заблокированы.")
        return
    if user_id == ADMIN_ID:
        await message.answer("✂️ Барбершоп. Админ-панель.", reply_markup=admin_menu())
    else:
        await message.answer("✂️ Барбершоп. Запись на стрижку и бороду.", reply_markup=main_menu())

@dp.message(Command("help"))
async def help_cmd(message: Message):
    text = "Список команд:\n/start — главное меню\n/cancel — отменить текущее действие"
    await message.answer(text)

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.")
    if message.from_user.id == ADMIN_ID:
        await message.answer("Меню администратора", reply_markup=admin_menu())
    else:
        await message.answer("Главное меню", reply_markup=main_menu())

@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Используйте: /ban 123456789")
        return
    try:
        uid = int(parts[1])
    except:
        await message.answer("ID должен быть числом")
        return
    ban_user(uid)
    await message.answer(f"✅ Пользователь {uid} забанен.")

@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        await message.answer("Используйте: /unban 123456789")
        return
    try:
        uid = int(parts[1])
    except:
        await message.answer("ID должен быть числом")
        return
    unban_user(uid)
    await message.answer(f"✅ Пользователь {uid} разбанен.")

# ================== ЗАПИСЬ КЛИЕНТА ==================
@dp.message(F.text == "✂️ Записаться")
async def start_booking(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        await message.answer("❌ Вы заблокированы.")
        return
    if get_active_order_count(user_id) >= 1:
        await message.answer("❌ У вас уже есть активная запись. Отмените её перед новой.")
        return
    await state.clear()
    barbers = get_all_barbers()
    if not barbers:
        await message.answer("Нет доступных мастеров.")
        return
    await message.answer("Выберите мастера:", reply_markup=barbers_keyboard(barbers))
    await state.set_state(BookingState.barber)

@dp.callback_query(BookingState.barber, F.data.startswith("barber_"))
async def barber_chosen(callback: CallbackQuery, state: FSMContext):
    barber_id = int(callback.data.split("_")[1])
    await state.update_data(barber_id=barber_id)
    services = get_all_services()
    await callback.message.edit_text("Выберите услугу:", reply_markup=services_keyboard(services))
    await state.set_state(BookingState.service)
    await callback.answer()

@dp.callback_query(BookingState.service, F.data.startswith("service_"))
async def service_chosen(callback: CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split("_")[1])
    await state.update_data(service_id=service_id)
    now = now_moscow()
    # Формируем список дат без свободных слотов для этого мастера и услуги
    data = await state.get_data()
    barber_id = data['barber_id']
    service = get_service(service_id)
    blocked = []
    for i in range(90):
        d = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        slots = get_free_slots(d, barber_id, service[2])
        if not slots:
            blocked.append(d)
    await state.update_data(blocked=blocked)
    await callback.message.edit_text("📅 Выберите дату:", reply_markup=calendar_keyboard(now.year, now.month, blocked))
    await state.set_state(BookingState.date)
    await callback.answer()

# Переход по календарю
@dp.callback_query(F.data.startswith("cal_prev_"))
async def cal_prev(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    year, month = int(parts[2]), int(parts[3])
    month -= 1
    if month < 1:
        month = 12
        year -= 1
    data = await state.get_data()
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, data.get('blocked', [])))
    await callback.answer()

@dp.callback_query(F.data.startswith("cal_next_"))
async def cal_next(callback: CallbackQuery, state: FSMContext):
    parts = callback.data.split("_")
    year, month = int(parts[2]), int(parts[3])
    month += 1
    if month > 12:
        month = 1
        year += 1
    data = await state.get_data()
    await callback.message.edit_reply_markup(reply_markup=calendar_keyboard(year, month, data.get('blocked', [])))
    await callback.answer()

@dp.callback_query(BookingState.date, F.data.startswith("date_"))
async def date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    data = await state.get_data()
    barber_id = data['barber_id']
    service = get_service(data['service_id'])
    if not service:
        await callback.answer("Ошибка услуги", show_alert=True)
        return
    slots = get_free_slots(date_str, barber_id, service[2])
    if not slots:
        await callback.answer("Нет свободных окон", show_alert=True)
        return
    await state.update_data(date=date_str)
    await callback.message.edit_text(f"📅 {format_date(date_str)}\nВыберите время:", reply_markup=slots_keyboard(slots))
    await state.set_state(BookingState.slot)
    await callback.answer()

@dp.callback_query(BookingState.slot, F.data.startswith("slot_"))
async def slot_chosen(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split("_", 1)[1]
    data = await state.get_data()
    barber_id = data['barber_id']
    service = get_service(data['service_id'])
    if not service:
        await callback.answer("Ошибка", show_alert=True)
        return
    # Повторная проверка
    if slot not in get_free_slots(data['date'], barber_id, service[2]):
        await callback.answer("Окно только что заняли", show_alert=True)
        return
    await state.update_data(slot=slot)
    await callback.message.edit_text("Введите ваше имя:")
    await state.set_state(BookingState.name)
    await callback.answer()

@dp.message(BookingState.name)
async def name_entered(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Слишком короткое имя.")
        return
    await state.update_data(name=name)
    await message.answer("📞 Отправьте номер телефона:", reply_markup=phone_kb())
    await state.set_state(BookingState.phone)

@dp.message(BookingState.phone, F.contact)
async def phone_contact(message: Message, state: FSMContext):
    await state.update_data(phone=message.contact.phone_number)
    await message.answer("✅ Номер принят.", reply_markup=ReplyKeyboardRemove())
    await show_summary(message, state)

@dp.message(BookingState.phone)
async def phone_manual(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(re.sub(r'\D','',phone)) < 10:
        await message.answer("Некорректный номер.")
        return
    await state.update_data(phone=phone)
    await message.answer("✅ Номер сохранён.", reply_markup=ReplyKeyboardRemove())
    await show_summary(message, state)

async def show_summary(message: Message, state: FSMContext):
    data = await state.get_data()
    barber = get_barber(data['barber_id'])
    service = get_service(data['service_id'])
    text = (
        f"<b>Проверьте данные:</b>\n"
        f"👤 Мастер: {barber[1]}\n"
        f"💇 Услуга: {service[1]} ({service[3]}₽)\n"
        f"📅 {format_date(data['date'])} {data['slot']}\n"
        f"👤 {data['name']}\n"
        f"📞 {data['phone']}"
    )
    await message.answer(text, reply_markup=confirm_kb())
    await state.set_state(BookingState.ready)

@dp.callback_query(F.data == "confirm_yes", StateFilter(BookingState.ready))
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    success = book_slot(data['date'], data['slot'], user_id,
                        data['barber_id'], data['service_id'],
                        data['name'], data['phone'])
    if not success:
        await callback.message.edit_text("❌ Не удалось записать, слот занят.")
        await state.clear()
        return
    await callback.message.edit_text("✅ Вы записаны! Напомним за 24 и 2 часа.")
    # Уведомление админу
    try:
        await bot.send_message(ADMIN_ID, f"Новая запись: {data['name']}, {format_date(data['date'])} {data['slot']}")
    except Exception as e:
        logger.error(f"Не удалось уведомить админа: {e}")
    await state.clear()
    await callback.answer()

@dp.callback_query(F.data == "confirm_no")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Отменено.")
    await state.clear()
    await callback.answer()

# ================== МОИ ЗАПИСИ ==================
@dp.message(F.text == "📋 Мои записи")
async def my_orders(message: Message):
    user_id = message.from_user.id
    orders = get_user_orders(user_id)
    if not orders:
        await message.answer("У вас нет активных записей.")
        return
    for o in orders:
        text = f"<b>Запись #{o[0]}</b>\n{o[1]} у {o[4]}\n📅 {format_date(o[2])} {o[3]}\n👤 {o[5]} | 📞 {o[6]}"
        await message.answer(text, reply_markup=cancel_order_inline(o[0]))

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_order_handler(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    cancel_order(order_id)
    await callback.message.edit_text("✅ Запись отменена.")
    await callback.answer()

# ================== АДМИНСКИЕ КНОПКИ ==================
@dp.message(F.text == "📋 Все записи")
async def admin_all_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    orders = get_all_future_orders()
    if not orders:
        await message.answer("Нет будущих записей.")
        return
    text = "<b>Все записи:</b>\n"
    for o in orders:
        text += f"#{o[0]} {o[6]} ({o[2]}) у {o[5]} {format_date(o[3])} {o[4]}\n"
    await message.answer(text[:4000])

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    today = len(get_orders_for_today())
    tomorrow = len(get_orders_for_tomorrow())
    future = len(get_all_future_orders())
    await message.answer(f"📊 Сегодня: {today}\nЗавтра: {tomorrow}\nВсего будущих: {future}")

@dp.message(F.text == "📞 Запись (звонок)")
async def admin_phone_booking(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Функция записи по звонку будет реализована здесь.")

@dp.message(F.text == "⚙️ Управление")
async def admin_settings(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Используйте веб-панель для управления мастерами и услугами.")

@dp.message(F.text == "📞 Поделиться ботом")
async def share_bot(message: Message):
    bot_username = (await bot.get_me()).username
    await message.answer(f"📣 Ссылка на бота:\nhttps://t.me/{bot_username}")

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.delete()
    except:
        pass
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Меню", reply_markup=admin_menu())
    else:
        await callback.message.answer("Меню", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "ignore")
async def ignore(callback: CallbackQuery):
    await callback.answer()

# ================== НАПОМИНАНИЯ ==================
async def send_reminders():
    for o in get_orders_for_reminder_24h():
        order_id, user_id, date_str, slot, phone = o
        try:
            await bot.send_message(user_id, f"🔔 Завтра в {slot} у вас запись!")
            mark_reminder_sent(order_id, '24h')
        except Exception as e:
            logger.error(f"Ошибка напоминания 24ч: {e}")

# ================== ЗАПУСК ==================
async def main():
    init_db()

    # 1. Запускаем ngrok
    if NGROK_AUTH_TOKEN:
        ngrok.set_auth_token(NGROK_AUTH_TOKEN)
    public_url = ngrok.connect(5000, bind_tls=True).public_url
    logger.info(f"ngrok туннель: {public_url}")
    os.environ["WEBAPP_BASE_URL"] = public_url
    import config
    config.WEBAPP_BASE_URL = public_url
    config.CLIENT_WEBAPP_URL = f"{public_url}/webapp"
    config.ADMIN_WEBAPP_URL  = f"{public_url}/admin"

    # 2. Flask в отдельном потоке
    from server import run_flask
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()

    # 3. Планировщик
    scheduler = AsyncIOScheduler(timezone=str(TIMEZONE))
    scheduler.add_job(send_reminders, 'interval', minutes=5)
    scheduler.start()

    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())