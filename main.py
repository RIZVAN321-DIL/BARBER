import asyncio
import re
import sqlite3
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, MASTER_PHONE, WORK_SLOTS
from database import (
    init_db, is_slot_free, book_slot, get_active_order_count,
    get_user_orders, get_all_future_orders, get_orders_for_today,
    get_orders_for_tomorrow, get_order_by_id, cancel_order,
    get_orders_for_reminder_24h, get_orders_for_reminder_2h,
    mark_reminder_sent, is_user_banned
)
from keyboards import (
    main_menu, admin_menu, service_buttons, quick_or_manual,
    calendar_keyboard, time_slots_buttons, confirm_keyboard, skip_keyboard,
    cancel_order_inline, confirm_cancel_keyboard
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Состояния для обычной записи
class BookingState(StatesGroup):
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()
    ready_to_book = State()   # промежуточное состояние перед подтверждением

# Состояния для быстрой записи (админ)
class QuickState(StatesGroup):
    service = State()
    date = State()
    slot = State()

# Состояния для отмены по ID (админ)
class AdminCancelState(StatesGroup):
    waiting_for_id = State()
    confirm = State()

# -------------------------------------------------------------------
# Функция ручного выбора даты (определена до использования)
# -------------------------------------------------------------------
async def manual_date_choice(callback: CallbackQuery, state: FSMContext):
    blocked = []
    for i in range(60):
        check_date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        free_count = sum(1 for slot in WORK_SLOTS if is_slot_free(check_date, slot))
        if free_count == 0:
            blocked.append(check_date)
    await callback.message.edit_text("📅 Выберите дату:", reply_markup=calendar_keyboard(blocked))
    await state.set_state(BookingState.date)

# -------------------------------------------------------------------
# Обработчики кнопок «Назад»
# -------------------------------------------------------------------
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    if callback.from_user.id == ADMIN_ID:
        await callback.message.edit_text("Меню администратора", reply_markup=admin_menu())
    else:
        await callback.message.edit_text("Главное меню", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "back_to_date")
async def back_to_date(callback: CallbackQuery, state: FSMContext):
    # Возврат к выбору даты
    data = await state.get_data()
    service = data.get("service")
    if not service:
        await callback.answer("Ошибка: не выбрана услуга")
        return
    await manual_date_choice(callback, state)

# -------------------------------------------------------------------
# СТАРТ / РАЗДЕЛЕНИЕ РОЛЕЙ
# -------------------------------------------------------------------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        await message.answer("❌ Вы заблокированы. Обратитесь к мастеру.")
        return
    text = (
        "✂️ **Добро пожаловать в барбершоп!**\n\n"
        "Быстрая запись без лишних данных.\n"
        f"📞 Мастер: {MASTER_PHONE}\n\n"
        "Нажмите кнопку ниже, чтобы записаться."
    )
    if user_id == ADMIN_ID:
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=main_menu())

# -------------------------------------------------------------------
# КЛИЕНТ: ЗАПИСАТЬСЯ
# -------------------------------------------------------------------
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

@dp.callback_query(BookingState.service, F.data.startswith("service_"))
async def service_chosen(callback: CallbackQuery, state: FSMContext):
    service_raw = callback.data.split("_", 1)[1]
    service_map = {
        "стрижка": "Стрижка",
        "борода": "Борода",
        "стрижка+борода": "Стрижка + Борода"
    }
    service = service_map.get(service_raw, "Стрижка")
    await state.update_data(service=service)
    await callback.message.edit_text("Как хотите записаться?", reply_markup=quick_or_manual())
    await state.set_state(BookingState.date)

# -------------------------------------------------------------------
# БЛИЖАЙШЕЕ ВРЕМЯ (автоматический поиск)
# -------------------------------------------------------------------
@dp.callback_query(F.data == "quick_auto")
async def quick_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service = data.get("service")
    now = datetime.now()
    found = False
    for i in range(14):  # ищем в течение 14 дней
        check_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        for slot in WORK_SLOTS:
            if is_slot_free(check_date, slot):
                # Нашли свободный слот, предлагаем записаться.
                await state.update_data(date=check_date, slot=slot)
                await callback.message.edit_text(
                    f"⚡ Нашёл свободное время:\n{check_date} {slot}\n\n"
                    "Теперь укажите имя и телефон (или пропустите)."
                )
                await callback.message.answer("Введите ваше имя (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
                await state.set_state(BookingState.name)
                found = True
                return
    if not found:
        await callback.message.edit_text("❌ Свободных слотов в ближайшие 14 дней не найдено. Попробуйте выбрать вручную.")
        await manual_date_choice(callback, state)

# -------------------------------------------------------------------
# РУЧНОЙ ВЫБОР ДАТЫ И ВРЕМЕНИ
# -------------------------------------------------------------------
@dp.callback_query(F.data == "manual_date")
async def manual_date_selection(callback: CallbackQuery, state: FSMContext):
    await manual_date_choice(callback, state)

@dp.callback_query(BookingState.date, F.data.startswith("date_"))
async def date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    free_slots = [slot for slot in WORK_SLOTS if is_slot_free(date_str, slot)]
    if not free_slots:
        await callback.answer("На эту дату все часы заняты, выберите другую", show_alert=True)
        return
    await state.update_data(date=date_str)
    await callback.message.edit_text(f"📅 {date_str}\nВыберите час:", reply_markup=time_slots_buttons(free_slots))
    await state.set_state(BookingState.slot)

@dp.callback_query(BookingState.slot, F.data.startswith("slot_"))
async def slot_chosen(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split("_", 1)[1]
    data = await state.get_data()
    if not is_slot_free(data['date'], slot):
        await callback.answer("Это время уже занято", show_alert=True)
        return
    await state.update_data(slot=slot)
    await callback.message.edit_text("Введите ваше имя (или нажмите «Пропустить»):", reply_markup=skip_keyboard())
    await state.set_state(BookingState.name)

# -------------------------------------------------------------------
# ИМЯ (опционально)
# -------------------------------------------------------------------
@dp.message(BookingState.name)
async def name_entered(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Слишком короткое имя. Введите хотя бы 2 символа или нажмите «Пропустить».")
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

# -------------------------------------------------------------------
# ТЕЛЕФОН (опционально)
# -------------------------------------------------------------------
@dp.message(BookingState.phone)
async def phone_entered(message: Message, state: FSMContext):
    phone_raw = message.text.strip()
    digits_only = re.sub(r'\D', '', phone_raw)
    if len(digits_only) < 5 and len(digits_only) > 0:
        await message.answer("❌ Слишком короткий номер. Введите хотя бы 5 цифр или нажмите «Пропустить».")
        return
    await state.update_data(phone=phone_raw)
    await confirm_booking_stage(message, state)

@dp.callback_query(BookingState.phone, F.data == "skip")
async def skip_phone(callback: CallbackQuery, state: FSMContext):
    await state.update_data(phone="")
    await confirm_booking_stage(callback.message, state)
    await callback.answer()

async def confirm_booking_stage(message: Message, state: FSMContext):
    data = await state.get_data()
    date_display = datetime.strptime(data['date'], "%Y-%m-%d").strftime("%d.%m")
    confirm_text = (
        f"✅ **Проверьте данные:**\n"
        f"Услуга: {data['service']}\n"
        f"Дата: {date_display}\n"
        f"Время: {data['slot']}\n"
        f"Имя: {data.get('name', 'не указано')}\n"
        f"Телефон: {data.get('phone', 'не указан')}\n\n"
        f"Подтверждаете запись?"
    )
    await message.answer(confirm_text, reply_markup=confirm_keyboard())
    await state.set_state(BookingState.ready_to_book)

# -------------------------------------------------------------------
# ФИНАЛЬНОЕ ПОДТВЕРЖДЕНИЕ ЗАПИСИ
# -------------------------------------------------------------------
@dp.callback_query(F.data == "confirm_yes", StateFilter(BookingState.ready_to_book))
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    user_id = callback.from_user.id
    # повторная проверка слота
    if not is_slot_free(data['date'], data['slot']):
        await callback.message.edit_text("❌ Этот час только что заняли. Попробуйте другой.")
        await state.clear()
        return
    book_slot(data['date'], data['slot'], user_id, data['service'],
              data.get('name', ''), data.get('phone', ''))
    date_display = datetime.strptime(data['date'], "%Y-%m-%d").strftime("%d.%m")
    await callback.message.edit_text(f"✅ Вы записаны на {date_display} {data['slot']}\n{data['service']}\nНапомним за 24 часа и за 2 часа.")
    admin_text = f"✂️ **Новая запись!**\n{data['service']}\n{data['date']} {data['slot']}\nКлиент: {data.get('name', 'без имени')} {data.get('phone', '')}"
    await bot.send_message(ADMIN_ID, admin_text)
    await state.clear()
    # Выведем меню заново
    if user_id == ADMIN_ID:
        await callback.message.answer("Меню администратора", reply_markup=admin_menu())
    else:
        await callback.message.answer("Главное меню", reply_markup=main_menu())
    await callback.answer()

@dp.callback_query(F.data == "confirm_no", StateFilter(BookingState.ready_to_book))
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Запись отменена.")
    await state.clear()
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Меню администратора", reply_markup=admin_menu())
    else:
        await callback.message.answer("Главное меню", reply_markup=main_menu())

# -------------------------------------------------------------------
# КЛИЕНТ: МОИ ЗАПИСИ И ОТМЕНА
# -------------------------------------------------------------------
@dp.message(F.text == "📋 Мои записи")
async def my_orders(message: Message):
    user_id = message.from_user.id
    orders = get_user_orders(user_id)
    if not orders:
        await message.answer("📭 У вас нет активных записей.")
        return
    for order_id, service, date_str, slot, name, phone in orders:
        date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
        text = f"🗓 {date_display} {slot}\n💇 {service}\n👤 {name if name else 'не указано'}"
        # проверка возможности отмены (за 2+ часа)
        slot_start_hour = int(slot.split(":")[0])
        slot_dt = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        if (slot_dt - datetime.now()).total_seconds() > 2 * 3600:
            await message.answer(text, reply_markup=cancel_order_inline(order_id))
        else:
            await message.answer(text + "\n\n⚠️ Отмена недоступна – осталось менее 2 часов.")

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_my_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    success, info = cancel_order(order_id, user_id, is_admin=False)
    if success:
        await callback.message.edit_text("✅ Ваша запись отменена.")
        await bot.send_message(ADMIN_ID, f"❌ Клиент отменил запись #{order_id}")
    else:
        if info == "too_late":
            await callback.answer("❌ Отмена невозможна – менее 2 часов до записи.", show_alert=True)
        elif info == "not_yours":
            await callback.answer("❌ Это не ваша запись.", show_alert=True)
        else:
            await callback.answer("❌ Запись не найдена.", show_alert=True)
    await callback.answer()

# -------------------------------------------------------------------
# АДМИН: ВСЕ ЗАПИСИ
# -------------------------------------------------------------------
@dp.message(F.text == "📋 Все записи")
async def all_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    orders = get_all_future_orders()
    if not orders:
        await message.answer("Нет будущих записей.")
        return
    text = "📋 **Все будущие записи:**\n\n"
    for order_id, user_id, service, date_str, slot, name, phone in orders:
        date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
        client = name if name else (f"user_{user_id}" if user_id else "По телефону")
        text += f"ID {order_id}: {service} | {date_display} {slot} | {client}\n"
    await message.answer(text[:4000])

# -------------------------------------------------------------------
# АДМИН: БЫСТРАЯ ЗАПИСЬ ПО ЗВОНКУ (без имени/телефона)
# -------------------------------------------------------------------
@dp.message(F.text == "📞 Быстрая запись (по звонку)")
async def quick_phone_booking(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await state.clear()
    await message.answer("Выберите услугу:", reply_markup=service_buttons())
    await state.set_state(QuickState.service)

@dp.callback_query(QuickState.service, F.data.startswith("service_"))
async def quick_service_chosen(callback: CallbackQuery, state: FSMContext):
    service_raw = callback.data.split("_", 1)[1]
    service_map = {
        "стрижка": "Стрижка",
        "борода": "Борода",
        "стрижка+борода": "Стрижка + Борода"
    }
    service = service_map.get(service_raw, "Стрижка")
    await state.update_data(service=service)
    # генерируем календарь
    blocked = []
    for i in range(60):
        check_date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        free_count = sum(1 for slot in WORK_SLOTS if is_slot_free(check_date, slot))
        if free_count == 0:
            blocked.append(check_date)
    await callback.message.edit_text("📅 Выберите дату:", reply_markup=calendar_keyboard(blocked))
    await state.set_state(QuickState.date)

@dp.callback_query(QuickState.date, F.data.startswith("date_"))
async def quick_date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    free_slots = [slot for slot in WORK_SLOTS if is_slot_free(date_str, slot)]
    if not free_slots:
        await callback.answer("На эту дату все часы заняты", show_alert=True)
        return
    await state.update_data(date=date_str)
    await callback.message.edit_text(f"📅 {date_str}\nВыберите час:", reply_markup=time_slots_buttons(free_slots))
    await state.set_state(QuickState.slot)

@dp.callback_query(QuickState.slot, F.data.startswith("slot_"))
async def quick_slot_chosen(callback: CallbackQuery, state: FSMContext):
    slot = callback.data.split("_", 1)[1]
    data = await state.get_data()
    if not is_slot_free(data['date'], slot):
        await callback.answer("Это время уже занято", show_alert=True)
        return
    book_slot(data['date'], slot, 0, data['service'], "По телефону", "звонок")
    date_display = datetime.strptime(data['date'], "%Y-%m-%d").strftime("%d.%m")
    await callback.message.edit_text(f"✅ Запись добавлена: {data['service']}, {date_display} {slot}\n(По телефону)")
    await state.clear()

# -------------------------------------------------------------------
# АДМИН: ОТМЕНА ПО ID
# -------------------------------------------------------------------
@dp.message(F.text == "❌ Отменить по ID")
async def admin_cancel_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите ID записи, которую нужно отменить.\nID можно посмотреть в «Все записи».")
    await state.set_state(AdminCancelState.waiting_for_id)

@dp.message(AdminCancelState.waiting_for_id)
async def admin_cancel_id(message: Message, state: FSMContext):
    try:
        order_id = int(message.text.strip())
    except:
        await message.answer("❌ Введите число")
        return
    order = get_order_by_id(order_id)
    if not order or order[7] != 'active':
        await message.answer("❌ Заказ не найден или уже отменён.")
        await state.clear()
        return
    await state.update_data(order_id=order_id)
    await message.answer(f"Вы уверены, что хотите отменить заказ #{order_id}?", reply_markup=confirm_cancel_keyboard())
    await state.set_state(AdminCancelState.confirm)

@dp.callback_query(F.data == "cancel_confirm_yes", StateFilter(AdminCancelState.confirm))
async def admin_confirm_cancel(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data['order_id']
    success, owner_id = cancel_order(order_id, ADMIN_ID, is_admin=True)
    if success:
        await callback.message.edit_text(f"✅ Заказ #{order_id} отменён.")
        if owner_id and owner_id != 0:
            try:
                await bot.send_message(owner_id, "😔 Ваш заказ был отменён мастером.")
            except:
                pass
    else:
        await callback.message.edit_text("❌ Не удалось отменить.")
    await state.clear()

@dp.callback_query(F.data == "cancel_confirm_no", StateFilter(AdminCancelState.confirm))
async def admin_cancel_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Отмена отменена.")
    await state.clear()

# -------------------------------------------------------------------
# АДМИН: СТАТИСТИКА
# -------------------------------------------------------------------
@dp.message(F.text == "📊 Статистика")
async def stats(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    today_orders = get_orders_for_today()
    tomorrow_orders = get_orders_for_tomorrow()
    all_future = get_all_future_orders()
    text = f"📊 **Статистика**\n\n"
    text += f"👤 **Сегодня:** {len(today_orders)} записей\n"
    for o in today_orders:
        _, name, service, slot, phone = o
        text += f"  - {slot} | {service} | {name if name else 'без имени'}\n"
    text += f"\n📅 **Завтра:** {len(tomorrow_orders)} записей\n"
    for o in tomorrow_orders:
        _, name, service, slot, phone = o
        text += f"  - {slot} | {service} | {name if name else 'без имени'}\n"
    text += f"\n📋 **Всего будущих:** {len(all_future)} записей"
    await message.answer(text)

# -------------------------------------------------------------------
# ПОДЕЛИТЬСЯ
# -------------------------------------------------------------------
@dp.message(F.text == "📞 Поделиться ботом")
async def share_bot(message: Message):
    bot_username = (await bot.get_me()).username
    await message.answer(f"📣 Поделитесь ботом с друзьями:\nhttps://t.me/{bot_username}")

# -------------------------------------------------------------------
# НАПОМИНАНИЯ (за 24 часа и за 2 часа)
# -------------------------------------------------------------------
async def send_reminders():
    now = datetime.now()

    # Напоминания за 24 часа (завтрашние записи)
    for order_id, user_id, date_str, slot, phone in get_orders_for_reminder_24h():
        try:
            date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
            await bot.send_message(user_id, f"🔔 **Напоминание!**\nЗавтра, {date_display} в {slot}, у вас запись.\nПриходите вовремя.")
            mark_reminder_sent(order_id, '24h')
        except Exception:
            pass

    # Напоминания за 2 часа (сегодняшние записи, до которых осталось 2 часа)
    for order_id, user_id, date_str, slot, phone in get_orders_for_reminder_2h():
        slot_start_hour = int(slot.split(":")[0])
        slot_dt = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        diff = (slot_dt - now).total_seconds() / 3600
        if 1.9 <= diff <= 2.1:
            try:
                date_display = datetime.strptime(date_str, "%Y-%m-%d").strftime("%d.%m")
                await bot.send_message(user_id, f"🔔 **Скоро запись!**\nЧерез 2 часа, {date_display} в {slot}.\nЖдём вас.")
                mark_reminder_sent(order_id, '2h')
            except Exception:
                pass

# -------------------------------------------------------------------
# ЗАПУСК
# -------------------------------------------------------------------
async def main():
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, 'interval', minutes=5)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())