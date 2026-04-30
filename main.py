import asyncio
import re
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, MASTER_PHONE
from database import (
    init_db, is_slot_free, book_slot, get_active_order_count,
    get_user_orders, get_all_future_orders, get_orders_for_today,
    get_orders_for_tomorrow, get_order_by_id, cancel_order,
    get_pending_reminders, mark_reminder_sent, is_user_banned
)
from keyboards import (
    main_menu, admin_menu, service_buttons, quick_or_manual,
    calendar_keyboard, time_slots_buttons, confirm_keyboard,
    cancel_order_inline, confirm_cancel_keyboard
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Часовые слоты (9:00-17:00, каждый час)
SLOTS = ["09:00-10:00", "10:00-11:00", "11:00-12:00", "12:00-13:00",
         "13:00-14:00", "14:00-15:00", "15:00-16:00", "16:00-17:00"]

# Состояния для обычной записи
class BookingState(StatesGroup):
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()

# Состояния для быстрой записи (админ или клиент "ближайшее время")
class QuickState(StatesGroup):
    service = State()
    date = State()
    slot = State()

# Состояния для ручной отмены по ID
class AdminCancelState(StatesGroup):
    waiting_for_id = State()

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
# КЛИЕНТ: ЗАПИСАТЬСЯ (выбор услуги)
# -------------------------------------------------------------------
@dp.message(F.text == "⚡ Записаться")
async def client_booking(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if is_user_banned(user_id):
        await message.answer("❌ Вы заблокированы. Обратитесь к мастеру.")
        return
    # Проверка на уже активную запись
    active = get_active_order_count(user_id)
    if active >= 1:
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
    # Предлагаем "Ближайшее время" или ручной выбор
    await callback.message.edit_text("Как хотите записаться?", reply_markup=quick_or_manual())
    await state.set_state(BookingState.date)

# -------------------------------------------------------------------
# БЛИЖАЙШЕЕ ВРЕМЯ (автоматический подбор)
# -------------------------------------------------------------------
@dp.callback_query(F.data == "quick_auto")
async def quick_booking(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    service = data.get("service")
    # Ищем ближайший свободный слот
    now = datetime.now()
    for i in range(7):  # ищем в течение 7 дней
        check_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        for slot in SLOTS:
            if is_slot_free(check_date, slot):
                # Нашли свободный слот
                await state.update_data(date=check_date, slot=slot)
                await callback.message.edit_text(f"✅ Найдено: {check_date} {slot}\nЗаписать без имени и телефона?")
                # Для клиента можно пропустить ввод данных, сохраним с пустыми полями
                # Сразу сохраняем
                user_id = callback.from_user.id
                book_slot(check_date, slot, user_id, service, "", "")
                text = f"✅ Вы записаны на {check_date} {slot}\n{service}\nНапомним за 2 часа."
                await callback.message.edit_text(text)
                # Уведомление админу
                admin_text = f"✂️ **Новая запись!**\n{service}\n{check_date} {slot}\nКлиент: @{callback.from_user.username or 'без username'}"
                await bot.send_message(ADMIN_ID, admin_text)
                await state.clear()
                return
    await callback.message.edit_text("❌ Свободных слотов в ближайшие 7 дней не найдено. Попробуйте выбрать вручную.")
    # Перенаправим на ручной выбор
    await manual_date_choice(callback, state)

async def manual_date_choice(callback: CallbackQuery, state: FSMContext):
    # Генерируем календарь
    blocked = []
    for i in range(60):
        check_date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        free_count = sum(1 for slot in SLOTS if is_slot_free(check_date, slot))
        if free_count == 0:
            blocked.append(check_date)
    await callback.message.edit_text("📅 Выберите дату:", reply_markup=calendar_keyboard(blocked))
    await state.set_state(BookingState.date)

# -------------------------------------------------------------------
# РУЧНОЙ ВЫБОР ДАТЫ / СЛОТА (для клиента и админа в режиме обычной записи)
# -------------------------------------------------------------------
@dp.callback_query(F.data == "manual_date")
async def manual_date_selection(callback: CallbackQuery, state: FSMContext):
    await manual_date_choice(callback, state)

@dp.callback_query(BookingState.date, F.data.startswith("date_"))
async def date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    free_slots = [slot for slot in SLOTS if is_slot_free(date_str, slot)]
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
        await callback.answer("Это время уже занято, выберите другое", show_alert=True)
        return
    await state.update_data(slot=slot)
    # Для клиента (или админа через обычную запись) можно пропустить ввод имени/телефона, но мы сохраним как есть.
    user_id = callback.from_user.id
    service = data.get("service")
    book_slot(data['date'], slot, user_id, service, "", "")
    await callback.message.edit_text(f"✅ Вы записаны на {data['date']} {slot}\n{service}\nНапомним за 2 часа.")
    admin_text = f"✂️ **Новая запись!**\n{service}\n{data['date']} {slot}\nКлиент: @{callback.from_user.username or 'без username'}"
    await bot.send_message(ADMIN_ID, admin_text)
    await state.clear()

# -------------------------------------------------------------------
# КЛИЕНТ: МОИ ЗАПИСИ
# -------------------------------------------------------------------
@dp.message(F.text == "📋 Мои записи")
async def my_orders(message: Message):
    user_id = message.from_user.id
    orders = get_user_orders(user_id)
    if not orders:
        await message.answer("📭 У вас нет активных записей.")
        return
    for order in orders:
        order_id, service, date_str, slot, name, phone = order
        text = f"🗓 {date_str} {slot}\n💇 {service}"
        # Проверим, можно ли отменить (за 2+ часа)
        slot_start_hour = int(slot.split(":")[0])
        slot_dt = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        can_cancel = (slot_dt - datetime.now()).total_seconds() > 2 * 3600
        if can_cancel:
            await message.answer(text, reply_markup=cancel_order_inline(order_id))
        else:
            await message.answer(text + "\n\n⚠️ Отмена недоступна – менее 2 часов до записи.")

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_my_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    success, info = cancel_order(order_id, user_id, is_admin=False)
    if not success:
        if info == "not_yours":
            await callback.answer("❌ Это не ваша запись!", show_alert=True)
        elif info == "too_late":
            await callback.answer("❌ Отмена невозможна – до записи менее 2 часов.", show_alert=True)
        else:
            await callback.answer("❌ Запись не найдена", show_alert=True)
        return
    await callback.message.edit_text("✅ Ваша запись отменена. Слот освобождён.")
    await bot.send_message(ADMIN_ID, f"❌ Клиент отменил запись #{order_id}")

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
    for o in orders:
        order_id, user_id, service, date_str, slot, name, phone = o
        client_info = f"{name}" if name else f"user_{user_id}"
        if not name and user_id == 0:
            client_info = "По телефону"
        text += f"ID {order_id}: {service} | {date_str} {slot} | {client_info}\n"
    await message.answer(text[:4000])

# -------------------------------------------------------------------
# АДМИН: БЫСТРАЯ ЗАПИСЬ ПО ЗВОНКУ (без имени и телефона)
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
    # Показать календарь
    blocked = []
    for i in range(60):
        check_date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        free_count = sum(1 for slot in SLOTS if is_slot_free(check_date, slot))
        if free_count == 0:
            blocked.append(check_date)
    await callback.message.edit_text("📅 Выберите дату:", reply_markup=calendar_keyboard(blocked))
    await state.set_state(QuickState.date)

@dp.callback_query(QuickState.date, F.data.startswith("date_"))
async def quick_date_chosen(callback: CallbackQuery, state: FSMContext):
    date_str = callback.data.split("_")[1]
    free_slots = [slot for slot in SLOTS if is_slot_free(date_str, slot)]
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
    # Сохраняем заказ с user_id=0 и пустыми именем/телефоном
    book_slot(data['date'], slot, 0, data['service'], "По телефону", "звонок")
    await callback.message.edit_text(f"✅ Запись добавлена: {data['service']}, {data['date']} {slot}\n(По телефону)")
    await state.clear()
    # Оповещение админу не нужно, он сам добавил

# -------------------------------------------------------------------
# АДМИН: ОТМЕНА ПО ID
# -------------------------------------------------------------------
@dp.message(F.text == "❌ Отменить по ID")
async def admin_cancel_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите ID записи, которую нужно отменить (цифру).\nID можно посмотреть в «Все записи».")
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
    # Запрашиваем подтверждение
    await state.update_data(order_id=order_id)
    confirm_text = f"Вы уверены, что хотите отменить заказ #{order_id}?"
    await message.answer(confirm_text, reply_markup=confirm_cancel_keyboard())
    await state.set_state("admin_confirm_cancel")

@dp.callback_query(F.data == "cancel_confirm_yes", StateFilter("admin_confirm_cancel"))
async def admin_confirm_cancel(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    order_id = data['order_id']
    success, owner_id = cancel_order(order_id, ADMIN_ID, is_admin=True)
    if success:
        await callback.message.edit_text(f"✅ Заказ #{order_id} отменён. Слот освобождён.")
        if owner_id and owner_id != 0:
            try:
                await bot.send_message(owner_id, "😔 Извините, ваш заказ был отменён мастером.")
            except:
                pass
    else:
        await callback.message.edit_text("❌ Не удалось отменить заказ.")
    await state.clear()

@dp.callback_query(F.data == "cancel_confirm_no", StateFilter("admin_confirm_cancel"))
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
        text += f"  - {o[3]} | {o[1]} {o[2]}\n"
    text += f"\n📅 **Завтра:** {len(tomorrow_orders)} записей\n"
    for o in tomorrow_orders:
        text += f"  - {o[3]} | {o[1]} {o[2]}\n"
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
# НАПОМИНАНИЯ (ЗА 24 ЧАСА И ЗА 2 ЧАСА)
# -------------------------------------------------------------------
async def send_reminders():
    now = datetime.now()
    # Напоминания за 24 часа до записи (для завтрашних записей)
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute('''
        SELECT id, user_id, date, slot, phone
        FROM orders
        WHERE date = ? AND status='active' AND reminder_sent = 0 AND user_id != 0
    ''', (tomorrow,))
    rows = cur.fetchall()
    for order_id, user_id, date_str, slot, phone in rows:
        try:
            await bot.send_message(user_id, f"🔔 **Напоминание!**\nЗавтра в {slot} у вас запись.\nПриходите вовремя.")
            mark_reminder_sent(order_id)
        except:
            pass
    # Напоминания за 2 часа
    for order_id, user_id, date_str, slot, phone in rows:
        slot_start_hour = int(slot.split(":")[0])
        slot_dt = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        diff = (slot_dt - now).total_seconds() / 3600
        if 1.9 <= diff <= 2.1:
            try:
                await bot.send_message(user_id, f"🔔 **Скоро запись!**\nЧерез 2 часа {slot}.\nЖдём вас.")
            except:
                pass
    conn.close()

# -------------------------------------------------------------------
# ЗАПУСК
# -------------------------------------------------------------------
async def main():
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, 'interval', minutes=5)  # каждые 5 минут
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())