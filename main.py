import asyncio
import re
import logging
from datetime import datetime, timedelta, date
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, MASTER_PHONE, WORK_SLOTS, TIMEZONE
from database import (
    init_db, is_slot_free, book_slot, get_active_order_count,
    get_user_orders, get_all_future_orders, get_orders_for_today,
    get_orders_for_tomorrow, get_order_by_id, cancel_order,
    get_orders_for_reminder_24h, get_orders_for_reminder_2h,
    mark_reminder_sent, is_user_banned, ban_user, unban_user,
    block_day, is_day_blocked
)
from keyboards import (
    main_menu, admin_menu, service_buttons, quick_or_manual,
    calendar_keyboard, time_slots_buttons, confirm_keyboard, admin_confirm_keyboard,
    skip_keyboard, cancel_order_inline, confirm_cancel_keyboard, confirm_block_day_keyboard
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ---------- ХЕЛПЕРЫ ----------
def now_moscow():
    return datetime.now(TIMEZONE)

def format_date(date_str: str) -> str:
    return datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")

def validate_phone(phone_raw: str) -> bool:
    digits = re.sub(r'\D', '', phone_raw)
    if not digits:
        return True
    return len(digits) >= 10 and digits.startswith(('7', '8'))

def get_month_name(date_obj):
    """Возвращает название месяца на русском."""
    months = {
        1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
        5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
        9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
    }
    return months.get(date_obj.month, "")

# ---------- FSM СОСТОЯНИЯ ----------
class BookingState(StatesGroup):
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()
    ready_to_book = State()

class QuickState(StatesGroup):
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()
    ready = State()

class AdminCancelState(StatesGroup):
    waiting_for_id = State()
    confirm = State()

class AdminBlockDayState(StatesGroup):
    waiting_for_date = State()
    confirm = State()

# ---------- КАЛЕНДАРЬ (компактный, с месяцем) ----------
async def show_calendar(callback: CallbackQuery, state: FSMContext, next_state):
    """Отображает календарь на 60 дней (компактный) с названием текущего месяца."""
    now = now_moscow()
    # Определяем заблокированные даты (все слоты заняты ИЛИ день полностью заблокирован)
    blocked = []
    for i in range(60):
        check_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        # Дата считается заблокированной, если все слоты заняты или целый день заблокирован
        free_count = sum(1 for slot in WORK_SLOTS if is_slot_free(check_date, slot))
        if free_count == 0 or is_day_blocked(check_date):
            blocked.append(check_date)
    # Определяем название текущего месяца (используем первую дату в календаре)
    first_day = now
    month_name = get_month_name(first_day)
    await callback.message.edit_text(f"📅 {month_name}:", reply_markup=calendar_keyboard(blocked, month_name))
    await state.set_state(next_state)

# ---------- УНИВЕРСАЛЬНЫЕ КНОПКИ «НАЗАД» ----------
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    user_id = callback.from_user.id
    if user_id == ADMIN_ID:
        await callback.message.edit_text("Меню администратора", reply_markup=admin_menu())
    else:
        await callback.message.edit_text("Главное меню", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "back_to_date")
async def back_to_date(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "service" not in data:
        await callback.answer("Ошибка, начните заново", show_alert=True)
        await callback.message.edit_text("Главное меню", reply_markup=main_menu())
        await state.clear()
        return
    await show_calendar(callback, state, BookingState.date)
    await callback.answer()

# ---------- СТАРТ ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        await message.answer("❌ Вы заблокированы.")
        logger.warning(f"Заблокированный пользователь {user_id} попытался начать")
        return
    text = "✂️ Барбершоп. Запись на стрижку и бороду."
    if user_id == ADMIN_ID:
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=main_menu())
    logger.info(f"Пользователь {user_id} запустил бота")

# ---------- БАН / РАЗБАН ----------
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
    logger.info(f"Админ {ADMIN_ID} забанил пользователя {uid}")

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
    logger.info(f"Админ {ADMIN_ID} разбанил пользователя {uid}")

# ---------- КЛИЕНТ: ЗАПИСАТЬСЯ ----------
@dp.message(F.text == "⚡ Записаться")
async def client_booking(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        await message.answer("❌ Вы заблокированы.")
        return
    if get_active_order_count(user_id) >= 1:
        await message.answer("❌ У вас уже есть активная запись. Отмените её, чтобы записаться снова.")
        return
    await state.clear()
    await message.answer("Выберите услугу:", reply_markup=service_buttons())
    await state.set_state(BookingState.service)
    logger.info(f"Пользователь {user_id} начал запись")

@dp.callback_query(BookingState.service, F.data.startswith("service_"))
async def service_chosen(callback: CallbackQuery, state: FSMContext):
    service_map = {
        "стрижка": "Стрижка",
        "борода": "Борода",
        "стрижка+борода": "Стрижка+Борода"
    }
    service = service_map.get(callback.data.split("_", 1)[1], "Стрижка")
    await state.update_data(service=service)
    await callback.message.edit_text("Как хотите записаться?", reply_markup=quick_or_manual())
    await state.set_state(BookingState.date)
    await callback.answer()

@dp.callback_query(F.data == "quick_auto")
async def quick_booking(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    if not data.get("service"):
        await callback.message.edit_text("❌ Ошибка: не выбрана услуга. Начните заново.", reply_markup=main_menu())
        await state.clear()
        return
    today = now_moscow().date()
    for i in range(14):
        check_date = (today + timedelta(days=i)).strftime("%Y-%m-%d")
        for slot in WORK_SLOTS:
            if is_slot_free(check_date, slot):
                await state.update_data(date=check_date, slot=slot)
                await callback.message.edit_text("Введите ваше имя (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
                await state.set_state(BookingState.name)
                logger.info(f"Авто-слот найден: {check_date} {slot}")
                return
    await callback.message.edit_text("❌ Свободных слотов в ближайшие 14 дней не найдено.", reply_markup=quick_or_manual())

@dp.callback_query(F.data == "manual_date")
async def manual_date_selection(callback: CallbackQuery, state: FSMContext):
    await show_calendar(callback, state, BookingState.date)
    await callback.answer()

@dp.callback_query(BookingState.date, F.data.startswith("date_"))
async def date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    free_slots = [slot for slot in WORK_SLOTS if is_slot_free(date_str, slot)]
    if not free_slots:
        await callback.answer("На эту дату все часы заняты или день заблокирован", show_alert=True)
        return
    await state.update_data(date=date_str)
    await callback.message.edit_text(f"📅 {format_date(date_str)}\nВыберите час:", reply_markup=time_slots_buttons(free_slots))
    await state.set_state(BookingState.slot)
    await callback.answer()

@dp.callback_query(BookingState.slot, F.data.startswith("slot_"))
async def slot_chosen(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split("_", 1)[1]
    data = await state.get_data()
    if not is_slot_free(data['date'], slot):
        await callback.answer("Это время уже занято или день заблокирован", show_alert=True)
        return
    await state.update_data(slot=slot)
    await callback.message.edit_text("Введите ваше имя (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
    await state.set_state(BookingState.name)
    await callback.answer()

@dp.message(BookingState.name)
async def name_entered(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Введите минимум 2 символа или нажмите «Пропустить».")
        return
    await state.update_data(name=name)
    await message.answer("Введите номер телефона (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
    await state.set_state(BookingState.phone)

@dp.callback_query(BookingState.name, F.data == "skip")
async def skip_name(callback: CallbackQuery, state: FSMContext):
    await state.update_data(name="")
    await callback.message.edit_text("Введите номер телефона (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
    await state.set_state(BookingState.phone)
    await callback.answer()

@dp.message(BookingState.phone)
async def phone_entered(message: Message, state: FSMContext):
    phone_raw = message.text.strip()
    if not validate_phone(phone_raw):
        await message.answer("❌ Введите корректный номер (мин. 10 цифр) или нажмите «Пропустить».")
        return
    await state.update_data(phone=phone_raw)
    await confirm_booking_stage(message, state)

@dp.callback_query(BookingState.phone, F.data == "skip")
async def skip_phone(callback: CallbackQuery, state: FSMContext):
    await state.update_data(phone="")
    await confirm_booking_stage(callback.message, state)
    await callback.answer()

async def confirm_booking_stage(msg, state):
    data = await state.get_data()
    text = (
        f"✅ Проверьте данные:\n"
        f"Услуга: {data['service']}\n"
        f"Дата: {format_date(data['date'])}\n"
        f"Время: {data['slot']}\n"
        f"Имя: {data.get('name', 'не указано')}\n"
        f"Телефон: {data.get('phone', 'не указан')}\n\n"
        f"Подтверждаете запись?"
    )
    await msg.answer(text, reply_markup=confirm_keyboard())
    await state.set_state(BookingState.ready_to_book)

@dp.callback_query(F.data == "confirm_yes", StateFilter(BookingState.ready_to_book))
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    if not is_slot_free(data['date'], data['slot']):
        await callback.message.edit_text("❌ Этот час только что заняли или день заблокирован. Начните заново.")
        await state.clear()
        await callback.answer()
        return

    success = book_slot(data['date'], data['slot'], user_id, data['service'],
                        data.get('name', ''), data.get('phone', ''))
    if not success:
        await callback.message.edit_text("❌ Ошибка при записи. Попробуйте позже.")
        await state.clear()
        await callback.answer()
        return

    date_display = format_date(data['date'])
    await callback.message.edit_text(f"✅ Вы записаны на {date_display} {data['slot']}\n{data['service']}\nНапомним за 2 часа и за 24 часа.")

    admin_text = f"✂️ Новая запись!\n{data['service']}\n{data['date']} {data['slot']}\nКлиент: {data.get('name', 'без имени')} {data.get('phone', '')}"
    try:
        await bot.send_message(ADMIN_ID, admin_text)
    except Exception as e:
        logger.error(f"Не удалось отправить уведомление админу: {e}")

    await state.clear()
    logger.info(f"Запись подтверждена: пользователь {user_id}, {data['date']} {data['slot']}")

    if user_id == ADMIN_ID:
        await callback.message.answer("Меню", reply_markup=admin_menu())
    else:
        await callback.message.answer("Меню", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "confirm_no", StateFilter(BookingState.ready_to_book))
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Запись отменена.")
    await state.clear()
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Меню", reply_markup=admin_menu())
    else:
        await callback.message.answer("Меню", reply_markup=main_menu())
    await callback.answer()

# ---------- МОИ ЗАПИСИ ----------
@dp.message(F.text == "📋 Мои записи")
async def my_orders(message: Message):
    user_id = message.from_user.id
    orders = get_user_orders(user_id)
    if not orders:
        await message.answer("📭 У вас нет активных записей.")
        return
    for order_id, service, date_str, slot, name, phone in orders:
        date_display = format_date(date_str)
        text = f"🗓 {date_display} {slot}\n💇 {service}\n👤 {name if name else 'не указано'}"
        slot_start_hour = int(slot.split(":")[0])
        slot_dt = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        now_no_tz = now_moscow().replace(tzinfo=None)
        if (slot_dt - now_no_tz).total_seconds() > 2 * 3600:
            await message.answer(text, reply_markup=cancel_order_inline(order_id))
        else:
            await message.answer(text + "\n\n⚠️ Отмена недоступна – менее 2 часов.")

@dp.callback_query(F.data.startswith("client_cancel_"))
async def cancel_my_order(callback: CallbackQuery):
    parts = callback.data.split("_")
    if len(parts) != 3:
        await callback.answer("Ошибка формата", show_alert=True)
        await callback.answer()
        return
    try:
        order_id = int(parts[2])
    except ValueError:
        await callback.answer("Неверный ID заказа", show_alert=True)
        await callback.answer()
        return
    user_id = callback.from_user.id
    success, info = cancel_order(order_id, user_id, is_admin=False)
    if success:
        await callback.message.edit_text("✅ Ваша запись отменена.")
        try:
            await bot.send_message(ADMIN_ID, f"❌ Клиент отменил запись #{order_id}")
        except Exception as e:
            logger.error(f"Ошибка уведомления админа: {e}")
    else:
        if info == "too_late":
            await callback.answer("❌ Отмена невозможна – менее 2 часов.", show_alert=True)
        elif info == "not_yours":
            await callback.answer("❌ Это не ваша запись.", show_alert=True)
        else:
            await callback.answer("❌ Запись не найдена.", show_alert=True)
    await callback.answer()

# ---------- АДМИН: ВСЕ ЗАПИСИ ----------
@dp.message(F.text == "📋 Все записи")
async def admin_all_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    orders = get_all_future_orders()
    if not orders:
        await message.answer("Нет будущих записей.")
        return
    text = "📋 **Все будущие записи:**\n\n"
    for o in orders:
        order_id, user_id, service, date_str, slot, name, phone = o
        date_display = format_date(date_str)
        client = name if name else (f"user_{user_id}" if user_id else "По телефону")
        text += f"ID {order_id}: {service} | {date_display} {slot} | {client} | тел:{phone}\n"
    await message.answer(text[:4000])
    logger.info(f"Админ просмотрел список записей ({len(orders)} шт.)")

# ---------- АДМИН: БЫСТРАЯ ЗАПИСЬ ПО ЗВОНКУ ----------
@dp.message(F.text == "📞 Быстрая запись (по звонку)")
async def admin_booking_phone(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("Выберите услугу:", reply_markup=service_buttons())
    await state.set_state(QuickState.service)

@dp.callback_query(QuickState.service, F.data.startswith("service_"))
async def admin_service_chosen(callback: CallbackQuery, state: FSMContext):
    service_map = {
        "стрижка": "Стрижка",
        "борода": "Борода",
        "стрижка+борода": "Стрижка+Борода"
    }
    service = service_map.get(callback.data.split("_", 1)[1], "Стрижка")
    await state.update_data(service=service)
    # показать календарь (компактный)
    now = now_moscow()
    blocked = []
    for i in range(60):
        check_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        free_count = sum(1 for slot in WORK_SLOTS if is_slot_free(check_date, slot))
        if free_count == 0 or is_day_blocked(check_date):
            blocked.append(check_date)
    month_name = get_month_name(now)
    await callback.message.edit_text(f"📅 {month_name}:", reply_markup=calendar_keyboard(blocked, month_name))
    await state.set_state(QuickState.date)
    await callback.answer()

@dp.callback_query(QuickState.date, F.data.startswith("date_"))
async def admin_date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    free_slots = [slot for slot in WORK_SLOTS if is_slot_free(date_str, slot)]
    if not free_slots:
        await callback.answer("На эту дату все часы заняты или день заблокирован", show_alert=True)
        return
    await state.update_data(date=date_str)
    await callback.message.edit_text(f"📅 {format_date(date_str)}\nВыберите час:", reply_markup=time_slots_buttons(free_slots))
    await state.set_state(QuickState.slot)
    await callback.answer()

@dp.callback_query(QuickState.slot, F.data.startswith("slot_"))
async def admin_slot_chosen(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split("_", 1)[1]
    data = await state.get_data()
    if not is_slot_free(data['date'], slot):
        await callback.answer("Это время уже занято или день заблокирован", show_alert=True)
        return
    await state.update_data(slot=slot)
    await callback.message.edit_text("Введите имя клиента (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
    await state.set_state(QuickState.name)
    await callback.answer()

@dp.message(QuickState.name)
async def admin_name_entered(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("Введите телефон клиента (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
    await state.set_state(QuickState.phone)

@dp.callback_query(QuickState.name, F.data == "skip")
async def admin_skip_name(callback: CallbackQuery, state: FSMContext):
    await state.update_data(name="")
    await callback.message.edit_text("Введите телефон клиента (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
    await state.set_state(QuickState.phone)
    await callback.answer()

@dp.message(QuickState.phone)
async def admin_phone_entered(message: Message, state: FSMContext):
    phone_raw = message.text.strip()
    if not validate_phone(phone_raw):
        await message.answer("❌ Введите корректный номер или нажмите «Пропустить».")
        return
    await state.update_data(phone=phone_raw)
    data = await state.get_data()
    confirm_text = (
        f"✅ Данные клиента:\n"
        f"Услуга: {data['service']}\n"
        f"Дата: {format_date(data['date'])}\n"
        f"Время: {data['slot']}\n"
        f"Имя: {data.get('name', 'не указано')}\n"
        f"Телефон: {data.get('phone', 'не указан')}\n\n"
        f"Сохранить запись?"
    )
    await message.answer(confirm_text, reply_markup=admin_confirm_keyboard())
    await state.set_state(QuickState.ready)

@dp.callback_query(QuickState.phone, F.data == "skip")
async def admin_skip_phone(callback: CallbackQuery, state: FSMContext):
    await state.update_data(phone="")
    data = await state.get_data()
    confirm_text = (
        f"✅ Данные клиента:\n"
        f"Услуга: {data['service']}\n"
        f"Дата: {format_date(data['date'])}\n"
        f"Время: {data['slot']}\n"
        f"Имя: {data.get('name', 'не указано')}\n"
        f"Телефон: {data.get('phone', 'не указан')}\n\n"
        f"Сохранить запись?"
    )
    await callback.message.edit_text(confirm_text, reply_markup=admin_confirm_keyboard())
    await state.set_state(QuickState.ready)
    await callback.answer()

@dp.callback_query(F.data == "confirm_admin_yes", StateFilter(QuickState.ready))
async def admin_save_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if not is_slot_free(data['date'], data['slot']):
        await callback.message.edit_text("❌ Слот уже занят или день заблокирован. Запись не сохранена.")
        await state.clear()
        await callback.answer()
        return

    success = book_slot(data['date'], data['slot'], 0, data['service'],
                        data.get('name', 'По телефону'), data.get('phone', 'звонок'))
    if not success:
        await callback.message.edit_text("❌ Ошибка при сохранении. Попробуйте позже.")
        await state.clear()
        await callback.answer()
        return

    date_display = format_date(data['date'])
    await callback.message.edit_text(f"✅ Запись добавлена: {data['service']}, {date_display} {data['slot']}\n(По телефону)")
    await state.clear()
    await callback.message.answer("Меню администратора", reply_markup=admin_menu())
    logger.info(f"Админ создал запись по звонку: {data['date']} {data['slot']}")
    await callback.answer()

@dp.callback_query(F.data == "confirm_no", StateFilter(QuickState.ready))
async def admin_cancel_booking(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Запись отменена.")
    await state.clear()
    await callback.message.answer("Меню администратора", reply_markup=admin_menu())
    await callback.answer()

# ---------- АДМИН: ОТМЕНА ПО ID ----------
@dp.message(F.text == "❌ Отменить по ID")
async def admin_cancel_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите ID записи для отмены (цифру). ID можно посмотреть в «Все записи».")
    await state.set_state(AdminCancelState.waiting_for_id)

@dp.message(AdminCancelState.waiting_for_id)
async def admin_cancel_id(message: Message, state: FSMContext):
    try:
        order_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Введите число")
        return
    order = get_order_by_id(order_id)
    if not order or order[7] != 'active':
        await message.answer("❌ Заказ не найден или уже отменён.")
        await state.clear()
        return
    await state.update_data(order_id=order_id)
    await state.set_state(AdminCancelState.confirm)
    await message.answer(f"Вы уверены, что хотите отменить заказ #{order_id}?", reply_markup=confirm_cancel_keyboard())

@dp.callback_query(F.data == "cancel_confirm_yes")
async def admin_confirm_cancel(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    current_state = await state.get_state()
    if current_state != AdminCancelState.confirm:
        await callback.message.edit_text("❌ Операция не активна. Начните отмену заново.")
        await state.clear()
        return
    data = await state.get_data()
    order_id = data.get('order_id')
    if not order_id:
        await callback.message.edit_text("❌ ID заказа не найден.")
        await state.clear()
        return
    success, owner_id = cancel_order(order_id, ADMIN_ID, is_admin=True)
    if success:
        await callback.message.edit_text(f"✅ Заказ #{order_id} отменён.")
        if owner_id and owner_id != 0:
            try:
                await bot.send_message(owner_id, "😔 Ваш заказ был отменён мастером.")
            except Exception as e:
                logger.error(f"Не удалось уведомить клиента об отмене: {e}")
    else:
        await callback.message.edit_text("❌ Не удалось отменить.")
    await state.clear()
    await callback.message.answer("Меню администратора", reply_markup=admin_menu())
    logger.info(f"Админ отменил заказ #{order_id}")

@dp.callback_query(F.data == "cancel_confirm_no")
async def admin_cancel_no(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("❌ Отмена заказа отменена.")
    await state.clear()
    await callback.message.answer("Меню администратора", reply_markup=admin_menu())

# ---------- АДМИН: ВЫХОДНОЙ (БЛОКИРОВКА ДНЯ) ----------
@dp.message(F.text == "⛔ Выходной")
async def admin_block_day_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await state.set_state(AdminBlockDayState.waiting_for_date)
    # Показываем календарь для выбора даты
    now = now_moscow()
    blocked = []  # для календаря не нужно показывать блокировки, просто выбор даты
    month_name = get_month_name(now)
    await message.answer(f"📅 {month_name} — выберите день, который хотите закрыть (сделать выходным):",
                         reply_markup=calendar_keyboard([], month_name))

@dp.callback_query(AdminBlockDayState.waiting_for_date, F.data.startswith("date_"))
async def admin_block_day_date(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    # Проверяем, есть ли активные записи на эту дату
    from database import get_all_future_orders  # нужно импортировать
    orders = get_all_future_orders()
    has_bookings = any(o[3] == date_str for o in orders)  # o[3] — дата
    if has_bookings:
        await callback.message.edit_text("❌ На эту дату есть активные записи. Сначала отмените их или перенесите.")
        await state.clear()
        await callback.message.answer("Меню администратора", reply_markup=admin_menu())
        return
    await state.update_data(block_date=date_str)
    await callback.message.edit_text(f"Вы уверены, что хотите заблокировать все часы на {format_date(date_str)}?",
                                     reply_markup=confirm_block_day_keyboard())
    await state.set_state(AdminBlockDayState.confirm)

@dp.callback_query(F.data == "block_day_yes", StateFilter(AdminBlockDayState.confirm))
async def confirm_block_day(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    date_str = data.get('block_date')
    if not date_str:
        await callback.message.edit_text("❌ Ошибка, дата не выбрана.")
        await state.clear()
        return
    success, msg = block_day(date_str)
    if success:
        await callback.message.edit_text(f"✅ День {format_date(date_str)} полностью заблокирован (выходной).")
    else:
        if msg == "has_bookings":
            await callback.message.edit_text("❌ На эту дату есть активные записи. Сначала отмените их.")
        else:
            await callback.message.edit_text("❌ Ошибка при блокировке.")
    await state.clear()
    await callback.message.answer("Меню администратора", reply_markup=admin_menu())
    await callback.answer()

@dp.callback_query(F.data == "block_day_no", StateFilter(AdminBlockDayState.confirm))
async def cancel_block_day(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Блокировка отменена.")
    await state.clear()
    await callback.message.answer("Меню администратора", reply_markup=admin_menu())
    await callback.answer()

# ---------- СТАТИСТИКА ----------
@dp.message(F.text == "📊 Статистика")
async def stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    today_cnt = len(get_orders_for_today())
    tomorrow_cnt = len(get_orders_for_tomorrow())
    future_cnt = len(get_all_future_orders())
    await message.answer(f"📊 Статистика:\nСегодня: {today_cnt}\nЗавтра: {tomorrow_cnt}\nВсего будущих: {future_cnt}")
    logger.info(f"Админ запросил статистику: {today_cnt}/{tomorrow_cnt}/{future_cnt}")

# ---------- ПОДЕЛИТЬСЯ ----------
@dp.message(F.text == "📞 Поделиться ботом")
async def share_bot(message: Message):
    bot_username = (await bot.get_me()).username
    await message.answer(f"📣 Поделитесь ботом с друзьями:\nhttps://t.me/{bot_username}")

# ---------- НАПОМИНАНИЯ ----------
async def send_reminders():
    now = now_moscow().replace(tzinfo=None)
    for o in get_orders_for_reminder_24h():
        order_id, user_id, date_str, slot, phone = o
        try:
            await bot.send_message(user_id, f"🔔 Напоминание: завтра, {format_date(date_str)} в {slot}, у вас запись.")
            mark_reminder_sent(order_id, '24h')
            logger.info(f"Отправлено напоминание 24ч пользователю {user_id}")
        except Exception as e:
            logger.error(f"Ошибка отправки напоминания 24ч: {e}")
    for o in get_orders_for_reminder_2h():
        order_id, user_id, date_str, slot, phone = o
        slot_start = int(slot.split(":")[0])
        slot_dt = datetime.strptime(f"{date_str} {slot_start:02d}:00", "%Y-%m-%d %H:%M")
        diff_h = (slot_dt - now).total_seconds() / 3600
        if 0 < diff_h <= 2:
            try:
                await bot.send_message(user_id, f"🔔 Напоминание: через ~2 часа, {format_date(date_str)} в {slot}, у вас запись.")
                mark_reminder_sent(order_id, '2h')
                logger.info(f"Отправлено напоминание 2ч пользователю {user_id}")
            except Exception as e:
                logger.error(f"Ошибка отправки напоминания 2ч: {e}")

# ---------- ЗАПУСК ----------
async def main():
    init_db()
    scheduler = AsyncIOScheduler(timezone=str(TIMEZONE))
    scheduler.add_job(send_reminders, 'interval', minutes=5)
    scheduler.start()
    logger.info("Бот запущен")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())