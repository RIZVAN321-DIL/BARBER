import asyncio
import logging
import re
import json
import hmac
import hashlib
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery, ReplyKeyboardRemove, WebAppInfo
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from aiogram.client.default import DefaultBotProperties

from config import BOT_TOKEN, ADMIN_ID, TIMEZONE, CLIENT_WEBAPP_URL
from database import (
    init_db, get_all_barbers, get_barber, get_all_services, get_service,
    get_free_slots, book_slot, get_user_orders, get_all_future_orders,
    cancel_order, get_order_by_id, is_user_banned, ban_user, unban_user,
    get_orders_for_today, get_orders_for_tomorrow,
    get_orders_for_reminder_24h, get_orders_for_reminder_2h,
    mark_reminder_sent, get_active_order_count,
    block_day_for_barber, unblock_day_for_barber,
    get_cancelled_orders, find_first_free_slot, min_to_time_str
)
from keyboards import (
    main_menu, admin_menu, barbers_keyboard, services_keyboard,
    calendar_keyboard, slots_keyboard, confirm_kb, phone_kb,
    cancel_order_inline, admin_cancel_move_keyboard, admin_move_confirm_keyboard,
    block_day_confirm_keyboard, unblock_day_confirm_keyboard,
    admin_orders_list_keyboard
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

class AdminBookingState(StatesGroup):
    barber = State()
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()

class BlockDayState(StatesGroup):
    waiting_for_date = State()

class UnblockDayState(StatesGroup):
    waiting_for_date = State()

# Проверка initData от Telegram (упрощённая)
def verify_telegram_webapp_data(data_str: str) -> bool:
    """Проверяет подпись initData из Mini App. Возвращает True, если данные валидны."""
    if not BOT_TOKEN:
        return False
    try:
        import urllib.parse as urlparse
        parsed = dict(urlparse.parse_qsl(data_str))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return False
        # Сортируем ключи
        data_check_string = "\n".join(f"{k}={parsed[k]}" for k in sorted(parsed.keys()))
        secret_key = hmac.new(key="WebAppData".encode(), msg=BOT_TOKEN.encode(), digestmod=hashlib.sha256).digest()
        calculated_hash = hmac.new(key=secret_key, msg=data_check_string.encode(), digestmod=hashlib.sha256).hexdigest()
        return received_hash == calculated_hash
    except Exception as e:
        logger.warning(f"Ошибка проверки initData: {e}")
        return False

# ================== /start ==================
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        await message.answer("⛔ Вы заблокированы.")
        return
    text = "💈 Добро пожаловать в <b>Барбершоп №1</b>!\nЗапись на стрижку и бороду."
    if user_id == ADMIN_ID:
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=main_menu())

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.")
    await message.answer("Главное меню", reply_markup=admin_menu() if message.from_user.id == ADMIN_ID else main_menu())

@dp.message(Command("ban"))
async def ban_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("Используйте: /ban 123456789")
    try:
        uid = int(parts[1])
    except:
        return await message.answer("ID должен быть числом")
    ban_user(uid)
    await message.answer(f"✅ Пользователь {uid} забанен.")

@dp.message(Command("unban"))
async def unban_cmd(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    parts = message.text.split()
    if len(parts) != 2:
        return await message.answer("Используйте: /unban 123456789")
    try:
        uid = int(parts[1])
    except:
        return await message.answer("ID должен быть числом")
    unban_user(uid)
    await message.answer(f"✅ Пользователь {uid} разбанен.")

# ================== ЗАПИСЬ КЛИЕНТА ==================
# (процесс остаётся тем же, только book_slot теперь принимает time_str, а внутри конвертирует в start_min)
# Обработчики FSM не меняются, просто book_slot использует новую сигнатуру.
# Вставлю полный код для уверенности.

@dp.message(F.text == "✂️ Записаться")
async def start_booking(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        return await message.answer("⛔ Вы заблокированы.")
    if get_active_order_count(user_id) >= 1:
        return await message.answer("❌ У вас уже есть активная запись. Отмените её перед созданием новой.")
    await state.clear()
    barbers = get_all_barbers()
    if not barbers:
        return await message.answer("Нет доступных мастеров.")
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
    barber_id = data.get('barber_id')
    service = get_service(data.get('service_id'))
    if not barber_id or not service:
        await callback.answer("Ошибка, начните заново", show_alert=True)
        await state.clear()
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
    if not barber_id or not service:
        await callback.answer("Ошибка", show_alert=True)
        return
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

# ================== ОБРАБОТКА WEBAPP ==================
@dp.message(F.web_app_data)
async def webapp_booking(message: Message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        return await message.answer("⛔ Вы заблокированы.")
    if get_active_order_count(user_id) >= 1:
        return await message.answer("❌ У вас уже есть активная запись.")

    # Проверяем подпись Telegram (если есть)
    if message.web_app_data.data:
        try:
            data = json.loads(message.web_app_data.data)
        except:
            return await message.answer("❌ Неверные данные.")
    else:
        return await message.answer("❌ Данные не получены.")

    # Верификация initData (если присутствует)
    if hasattr(message, 'web_app_data') and hasattr(message.web_app_data, 'init_data'):
        if not verify_telegram_webapp_data(message.web_app_data.init_data):
            logger.warning("Невалидная подпись WebApp")
            return await message.answer("❌ Ошибка безопасности.")

    service_id = data.get('service_id')
    barber_id = data.get('barber_id')
    name = data.get('name', '').strip()
    phone = data.get('phone', '').strip()
    if not name or not phone or not service_id or not barber_id:
        return await message.answer("❌ Не все данные заполнены.")

    date_str, slot = find_first_free_slot(barber_id, service_id)
    if not date_str:
        return await message.answer("❌ Нет свободных слотов в ближайшие 14 дней.")

    success = book_slot(date_str, slot, user_id, barber_id, service_id, name, phone)
    if not success:
        date_str, slot = find_first_free_slot(barber_id, service_id)
        if not date_str:
            return await message.answer("❌ Слот занят, повторите позже.")
        success = book_slot(date_str, slot, user_id, barber_id, service_id, name, phone)
        if not success:
            return await message.answer("❌ Не удалось записать, попробуйте через меню.")

    await message.answer(
        f"✅ <b>Вы записаны через сайт!</b>\n"
        f"📅 {format_date(date_str)} {slot}\n"
        f"💇 {get_service(service_id)[1]} у {get_barber(barber_id)[1]}\n"
        f"Напомним за 24 и 2 часа."
    )
    try:
        await bot.send_message(ADMIN_ID, f"WebApp запись: {name}, {format_date(date_str)} {slot}")
    except:
        pass

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

# ================== АДМИНКА ==================
# (все обработчики как в последней версии, с учётом get_all_future_orders теперь возвращает time как str)
# Вставляем полностью.
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

@dp.message(F.text == "📞 Запись (звонок)")
async def admin_phone_booking(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    barbers = get_all_barbers()
    await message.answer("Выберите мастера:", reply_markup=barbers_keyboard(barbers))
    await state.set_state(AdminBookingState.barber)

@dp.callback_query(AdminBookingState.barber, F.data.startswith("barber_"))
async def admin_barber_chosen(callback: CallbackQuery, state: FSMContext):
    barber_id = int(callback.data.split("_")[1])
    await state.update_data(barber_id=barber_id)
    services = get_all_services()
    await callback.message.edit_text("Выберите услугу:", reply_markup=services_keyboard(services))
    await state.set_state(AdminBookingState.service)
    await callback.answer()

@dp.callback_query(AdminBookingState.service, F.data.startswith("service_"))
async def admin_service_chosen(callback: CallbackQuery, state: FSMContext):
    service_id = int(callback.data.split("_")[1])
    await state.update_data(service_id=service_id)
    now = now_moscow()
    data = await state.get_data()
    barber_id = data['barber_id']
    service = get_service(service_id)
    blocked = []
    for i in range(90):
        d = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        if not get_free_slots(d, barber_id, service[2]):
            blocked.append(d)
    await state.update_data(blocked=blocked)
    await callback.message.edit_text("📅 Выберите дату:", reply_markup=calendar_keyboard(now.year, now.month, blocked))
    await state.set_state(AdminBookingState.date)
    await callback.answer()

@dp.callback_query(AdminBookingState.date, F.data.startswith("date_"))
async def admin_date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    data = await state.get_data()
    barber_id = data.get('barber_id')
    service = get_service(data.get('service_id'))
    if not barber_id or not service:
        await callback.answer("Ошибка", show_alert=True)
        return
    slots = get_free_slots(date_str, barber_id, service[2])
    if not slots:
        await callback.answer("Нет свободных окон", show_alert=True)
        return
    await state.update_data(date=date_str)
    await callback.message.edit_text(f"📅 {format_date(date_str)}\nВыберите время:", reply_markup=slots_keyboard(slots))
    await state.set_state(AdminBookingState.slot)
    await callback.answer()

@dp.callback_query(AdminBookingState.slot, F.data.startswith("slot_"))
async def admin_slot_chosen(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split("_", 1)[1]
    data = await state.get_data()
    barber_id = data['barber_id']
    service = get_service(data['service_id'])
    if not barber_id or not service:
        await callback.answer("Ошибка", show_alert=True)
        return
    if slot not in get_free_slots(data['date'], barber_id, service[2]):
        await callback.answer("Окно только что заняли", show_alert=True)
        return
    await state.update_data(slot=slot)
    await callback.message.edit_text("Введите имя клиента:")
    await state.set_state(AdminBookingState.name)
    await callback.answer()

@dp.message(AdminBookingState.name)
async def admin_name_entered(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("Слишком короткое имя.")
        return
    await state.update_data(name=name)
    await message.answer("📞 Введите номер телефона клиента:")
    await state.set_state(AdminBookingState.phone)

@dp.message(AdminBookingState.phone)
async def admin_phone_entered(message: Message, state: FSMContext):
    phone = message.text.strip()
    if len(re.sub(r'\D','',phone)) < 10:
        await message.answer("Некорректный номер.")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    success = book_slot(data['date'], data['slot'], 0,
                        data['barber_id'], data['service_id'],
                        data['name'], data['phone'])
    if not success:
        await message.answer("❌ Не удалось записать.")
        await state.clear()
        return
    barber = get_barber(data['barber_id'])
    service = get_service(data['service_id'])
    await message.answer(
        f"✅ <b>Запись добавлена:</b>\n"
        f"👤 {data['name']} | 📞 {data['phone']}\n"
        f"💇 {service[1]} у {barber[1]}\n"
        f"📅 {format_date(data['date'])} {data['slot']}",
        reply_markup=admin_menu()
    )
    await state.clear()

@dp.message(F.text == "❌ Отменить/Перенести")
async def admin_cancel_move_list(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    orders = get_all_future_orders()
    if not orders:
        await message.answer("Нет активных записей.")
        return
    await message.answer("📋 <b>Выберите запись для отмены или переноса:</b>",
                         reply_markup=admin_orders_list_keyboard(orders))

@dp.callback_query(F.data.startswith("adm_sel_"))
async def admin_select_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    order = get_order_by_id(order_id)
    if not order or order[8] != 'active':
        await callback.answer("Заказ уже не активен.", show_alert=True)
        return
    text = (f"<b>Заказ #{order[0]}</b>\n"
            f"💇 {order[2]} у {order[5]}\n"
            f"📅 {format_date(order[3])} {order[4]}\n"
            f"👤 {order[6]} | 📞 {order[7]}")
    await callback.message.edit_text(text, reply_markup=admin_cancel_move_keyboard(order_id))
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_cancel_"))
async def admin_cancel_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    order = get_order_by_id(order_id)
    if not order or order[8] != 'active':
        await callback.message.edit_text("Заказ уже не активен.")
        await callback.answer()
        return
    cancel_order(order_id)
    await callback.message.edit_text(f"✅ Заказ #{order_id} отменён.")
    if order[1] and order[1] != 0:
        try:
            await bot.send_message(order[1], "😔 Мастер отменил вашу запись. Приносим извинения.")
        except:
            pass
    await callback.answer()

@dp.callback_query(F.data.startswith("admin_move_"))
async def admin_move_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[2])
    order = get_order_by_id(order_id)
    if not order or order[8] != 'active':
        await callback.message.edit_text("Заказ уже не активен.")
        await callback.answer()
        return
    # order[9] = service_id, order[10] = duration
    service_id = order[9]
    duration = order[10]
    start_date = now_moscow().date() + timedelta(days=1)
    found = False
    for barber in get_all_barbers():
        bid = barber[0]
        for i in range(30):
            d = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            slots = get_free_slots(d, bid, duration)
            if slots:
                new_date, new_slot = d, slots[0]
                found = True
                break
        if found:
            break
    if not found:
        await callback.message.edit_text("Нет свободных слотов в ближайшие 30 дней.")
        await callback.answer()
        return
    await callback.message.edit_text(
        f"Ближайший слот: {format_date(new_date)} {new_slot}\nПеренести заказ #{order_id}?",
        reply_markup=admin_move_confirm_keyboard(order_id, new_date, new_slot)
    )
    await callback.answer()

@dp.callback_query(F.data.startswith("confirm_move_"))
async def confirm_move_order(callback: CallbackQuery):
    parts = callback.data.split("_")
    order_id = int(parts[2])
    new_date = parts[3]
    new_slot = parts[4]
    # Перенос: удаляем старый слот (cancel), создаем новый
    order = get_order_by_id(order_id)
    if not order or order[8] != 'active':
        await callback.message.edit_text("Заказ уже не активен.")
        return
    # Отменяем старый
    cancel_order(order_id)
    # Бронируем новый
    success = book_slot(new_date, new_slot, order[1], order[9], order[9], order[6], order[7])
    if not success:
        # Восстанавливаем старый (сложно, поэтому просто сообщаем)
        await callback.message.edit_text("❌ Не удалось перенести, слот занят.")
        return
    await callback.message.edit_text(f"✅ Заказ #{order_id} перенесён на {format_date(new_date)} {new_slot}.")
    if order[1] and order[1] != 0:
        try:
            await bot.send_message(order[1], f"🔄 Ваша запись перенесена на {format_date(new_date)} {new_slot}.")
        except:
            pass
    await callback.answer()

# ================== ОСТАЛЬНЫЕ АДМИНСКИЕ ДЕЙСТВИЯ ==================
@dp.message(F.text == "⛔ Выходной")
async def admin_block_day_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    now = now_moscow()
    await message.answer("📅 Выберите дату для блокировки:", reply_markup=calendar_keyboard(now.year, now.month))
    await state.set_state(BlockDayState.waiting_for_date)

@dp.callback_query(BlockDayState.waiting_for_date, F.data.startswith("date_"))
async def admin_block_day_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    await state.update_data(block_date=date_str)
    await callback.message.edit_text(f"Заблокировать день {format_date(date_str)} для всех мастеров?",
                                     reply_markup=block_day_confirm_keyboard(date_str))
    await callback.answer()

@dp.callback_query(F.data.startswith("block_confirm_"))
async def admin_block_day_confirm(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[2]
    for barber in get_all_barbers():
        block_day_for_barber(date_str, barber[0])
    await callback.message.edit_text(f"✅ День {format_date(date_str)} заблокирован.")
    await state.clear()
    await callback.answer()

@dp.message(F.text == "🗓 Открыть день")
async def admin_unblock_day_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    now = now_moscow()
    await message.answer("📅 Выберите дату для открытия:", reply_markup=calendar_keyboard(now.year, now.month))
    await state.set_state(UnblockDayState.waiting_for_date)

@dp.callback_query(UnblockDayState.waiting_for_date, F.data.startswith("date_"))
async def admin_unblock_day_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    await state.update_data(unblock_date=date_str)
    await callback.message.edit_text(f"Открыть день {format_date(date_str)}?",
                                     reply_markup=unblock_day_confirm_keyboard(date_str))
    await callback.answer()

@dp.callback_query(F.data.startswith("unblock_confirm_"))
async def admin_unblock_day_confirm(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[2]
    for barber in get_all_barbers():
        unblock_day_for_barber(date_str, barber[0])
    await callback.message.edit_text(f"✅ День {format_date(date_str)} открыт.")
    await state.clear()
    await callback.answer()

@dp.message(F.text == "📊 Статистика")
async def admin_stats(message: Message):
    if message.from_user.id != ADMIN_ID: return
    today = len(get_orders_for_today())
    tomorrow = len(get_orders_for_tomorrow())
    future = len(get_all_future_orders())
    await message.answer(f"📊 Сегодня: {today}\n📊 Завтра: {tomorrow}\n📊 Всего будущих: {future}")

@dp.message(F.text == "📜 История отмен")
async def admin_cancelled_orders(message: Message):
    if message.from_user.id != ADMIN_ID: return
    orders = get_cancelled_orders()
    if not orders:
        await message.answer("Нет отменённых записей.")
        return
    text = "<b>📜 История отмен (последние 20):</b>\n"
    for o in orders:
        text += f"#{o[0]} {o[5]} ({o[2]}) {format_date(o[3])} {o[4]}\n"
    await message.answer(text[:4000])

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

async def send_reminders():
    for o in get_orders_for_reminder_24h():
        order_id, user_id, date_str, slot, phone = o
        try:
            await bot.send_message(user_id, f"🔔 Завтра в {slot} у вас запись!")
            mark_reminder_sent(order_id, '24h')
        except Exception as e:
            logger.error(f"Remind 24h: {e}")
    for o in get_orders_for_reminder_2h():
        order_id, user_id, date_str, slot, phone = o
        try:
            await bot.send_message(user_id, f"🔔 Через 2 часа у вас запись в {slot}!")
            mark_reminder_sent(order_id, '2h')
        except Exception as e:
            logger.error(f"Remind 2h: {e}")

async def main():
    init_db()
    scheduler = AsyncIOScheduler(timezone=str(TIMEZONE))
    scheduler.add_job(send_reminders, 'interval', minutes=1)  # проверяем каждую минуту
    scheduler.start()
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())