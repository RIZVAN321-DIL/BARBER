import asyncio
import re
from time import time
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command, StateFilter
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from config import BOT_TOKEN, ADMIN_ID, MASTER_PHONE
from database import (
    init_db, is_slot_free, book_slot, cancel_order_by_id,
    get_user_active_orders, get_all_future_orders,
    get_pending_reminders, mark_reminder_sent,
    count_active_bookings, is_user_banned, ban_user, unban_user,
    get_order_by_id
)
from keyboards import (
    main_menu, admin_menu, calendar_keyboard, time_slots_buttons,
    confirm_keyboard, cancel_order_inline, confirm_cancel_keyboard
)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Часовые слоты (9 слотов с 8:00 до 17:00)
SLOTS = ["08:00-09:00", "09:00-10:00", "10:00-11:00", "11:00-12:00",
         "12:00-13:00", "13:00-14:00", "14:00-15:00", "15:00-16:00", "16:00-17:00"]

# Rate limit: не более 3 попыток выбора слота за 60 секунд
rate_limit = {}

def check_rate_limit(user_id, limit=3, per=60):
    now = time()
    if user_id not in rate_limit:
        rate_limit[user_id] = []
    # Удаляем старые записи
    rate_limit[user_id] = [t for t in rate_limit[user_id] if now - t < per]
    if len(rate_limit[user_id]) >= limit:
        return False
    rate_limit[user_id].append(now)
    return True

# ---------- СОСТОЯНИЯ FSM ----------
class BookingState(StatesGroup):
    service = State()
    date = State()
    slot = State()
    name = State()
    phone = State()

class AdminCancelState(StatesGroup):
    waiting_for_id = State()

# ---------- КОМАНДА /start ----------
@dp.message(Command("start"))
async def start_cmd(message: Message):
    text = (
        "✂️ **Добро пожаловать в барбершоп!**\n\n"
        "💇‍♂️ **Услуги:** стрижка, борода, комплекс\n"
        "⏰ Часы работы: 08:00 – 17:00 (каждый час)\n"
        f"📞 Связь с мастером: {MASTER_PHONE}\n\n"
        "Запишитесь нажав на кнопку ниже 👇"
    )
    if message.from_user.id == ADMIN_ID:
        await message.answer(text, reply_markup=admin_menu())
    else:
        await message.answer(text, reply_markup=main_menu())

# ---------- ВЫБОР УСЛУГИ ----------
@dp.message(F.text.in_(["💇‍♂️ Стрижка", "🧔 Борода", "💇‍♂️+🧔 Стрижка + Борода"]))
async def service_chosen(message: Message, state: FSMContext):
    # Проверка бана
    if is_user_banned(message.from_user.id):
        await message.answer("❌ Вы заблокированы. Обратитесь к мастеру.")
        return
    # Проверка лимита активных записей
    if count_active_bookings(message.from_user.id) >= 1:
        await message.answer("❌ У вас уже есть активная запись. Отмените её, чтобы записаться снова.")
        return
    service_map = {
        "💇‍♂️ Стрижка": "Стрижка",
        "🧔 Борода": "Борода",
        "💇‍♂️+🧔 Стрижка + Борода": "Стрижка + Борода"
    }
    service = service_map[message.text]
    await state.update_data(service=service)
    await state.set_state(BookingState.date)

    # Определяем занятые дни (все слоты заняты)
    blocked = []
    for i in range(60):
        check_date = (datetime.now() + timedelta(days=i)).strftime("%Y-%m-%d")
        free_count = sum(1 for slot in SLOTS if is_slot_free(check_date, slot))
        if free_count == 0:
            blocked.append(check_date)

    await message.answer("📅 Выберите дату:", reply_markup=calendar_keyboard(blocked))

# ---------- ВЫБОР ДАТЫ ----------
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

# ---------- ВЫБОР ВРЕМЕНИ (с защитой rate limit) ----------
@dp.callback_query(BookingState.slot, F.data.startswith("slot_"))
async def slot_chosen(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    if not check_rate_limit(user_id):
        await callback.answer("❌ Слишком много попыток. Подождите минуту.", show_alert=True)
        return
    slot = callback.data.split("_", 1)[1]
    data = await state.get_data()
    if not is_slot_free(data['date'], slot):
        await callback.answer("Это время уже занято, выберите другое", show_alert=True)
        return
    await state.update_data(slot=slot)
    await callback.message.edit_text("✍️ Введите ваше **имя** (как к вам обращаться):")
    await state.set_state(BookingState.name)

# ---------- ИМЯ ----------
@dp.message(BookingState.name)
async def name_entered(message: Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2:
        await message.answer("❌ Введите имя (минимум 2 символа):")
        return
    await state.update_data(name=name)
    await message.answer("📞 Введите **номер телефона** (для связи):")
    await state.set_state(BookingState.phone)

# ---------- ТЕЛЕФОН ----------
@dp.message(BookingState.phone)
async def phone_entered(message: Message, state: FSMContext):
    phone_raw = message.text.strip()
    digits_only = re.sub(r'\D', '', phone_raw)
    if len(digits_only) < 5 or len(digits_only) > 15:
        await message.answer("❌ Введите корректный номер (от 5 до 15 цифр):")
        return
    await state.update_data(phone=phone_raw)
    data = await state.get_data()
    confirm_text = (
        f"✅ **Проверьте данные:**\n"
        f"Услуга: {data['service']}\n"
        f"Дата: {data['date']}\n"
        f"Время: {data['slot']}\n"
        f"Имя: {data['name']}\n"
        f"Телефон: {phone_raw}\n\n"
        f"Подтверждаете запись?"
    )
    await message.answer(confirm_text, reply_markup=confirm_keyboard())

# ---------- ПОДТВЕРЖДЕНИЕ ЗАПИСИ ----------
@dp.callback_query(F.data == "confirm_yes")
async def confirm_booking(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    data = await state.get_data()

    # Повторные проверки на бан и лимит
    if is_user_banned(user_id):
        await callback.message.edit_text("❌ Вы заблокированы.")
        await state.clear()
        return
    if count_active_bookings(user_id) >= 1:
        await callback.message.edit_text("❌ У вас уже есть активная запись.")
        await state.clear()
        return
    if not is_slot_free(data['date'], data['slot']):
        await callback.message.edit_text("❌ Извините, этот час только что заняли. Выберите другое время.")
        await state.clear()
        return

    book_slot(
        date_str=data['date'],
        slot=data['slot'],
        user_id=user_id,
        service=data['service'],
        client_name=data['name'],
        phone=data['phone']
    )
    await callback.message.edit_text("✅ Вы записаны! Приходите вовремя. Напомним за час.")

    admin_text = (
        f"✂️ **Новая запись!**\n"
        f"{data['service']}\n"
        f"{data['date']} {data['slot']}\n"
        f"Клиент: {data['name']}\n"
        f"Тел: {data['phone']}"
    )
    await bot.send_message(ADMIN_ID, admin_text)

    await state.clear()
    if user_id == ADMIN_ID:
        await callback.message.answer("Меню", reply_markup=admin_menu())
    else:
        await callback.message.answer("Меню", reply_markup=main_menu())

@dp.callback_query(F.data == "confirm_no")
async def cancel_booking(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("❌ Запись отменена.")
    await state.clear()
    if callback.from_user.id == ADMIN_ID:
        await callback.message.answer("Меню", reply_markup=admin_menu())
    else:
        await callback.message.answer("Меню", reply_markup=main_menu())

# ---------- МОИ ЗАПИСИ (с возможностью отмены, если до записи >2 часов) ----------
@dp.message(F.text == "📋 Мои записи")
async def my_orders(message: Message):
    user_id = message.from_user.id
    orders = get_user_active_orders(user_id)
    if not orders:
        await message.answer("📭 У вас нет активных записей.")
        return
    for order in orders:
        order_id, service, date_str, slot, client_name, phone = order
        # Проверяем, можно ли отменить (до записи больше 2 часов)
        slot_start_hour = int(slot.split(":")[0])
        slot_datetime = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        can_cancel = (slot_datetime - datetime.now()).total_seconds() > 2 * 3600
        text = f"🗓 {date_str} {slot}\n💇 {service}\n👤 {client_name}\n📞 {phone}"
        if can_cancel:
            await message.answer(text, reply_markup=cancel_order_inline(order_id))
        else:
            await message.answer(text + "\n\n⚠️ Отмена недоступна – до записи менее 2 часов.")

@dp.callback_query(F.data.startswith("cancel_"))
async def cancel_my_order(callback: CallbackQuery):
    order_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    success, info = cancel_order_by_id(order_id, user_id, is_admin=(user_id == ADMIN_ID))
    if not success:
        if info == "not_yours":
            await callback.answer("❌ Это не ваша запись!", show_alert=True)
        elif info == "too_late":
            await callback.answer("❌ Отмена невозможна – до записи осталось менее 2 часов.", show_alert=True)
        else:
            await callback.answer("❌ Заказ не найден", show_alert=True)
        return
    await callback.message.edit_text("✅ Ваша запись отменена. Слот освобождён.")
    if user_id != ADMIN_ID:
        await bot.send_message(ADMIN_ID, f"❌ Клиент отменил запись #{order_id}")

# ---------- ПОДЕЛИТЬСЯ ----------
@dp.message(F.text == "📞 Поделиться ботом")
async def share_bot(message: Message):
    bot_username = (await bot.get_me()).username
    await message.answer(f"📣 Поделитесь ботом с друзьями:\nhttps://t.me/{bot_username}")

# ---------- АДМИН: АНАЛИТИКА ----------
@dp.message(F.text == "📊 Аналитика")
async def analytics(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    orders = get_all_future_orders()
    total = len(orders)
    await message.answer(f"📈 Всего будущих записей: {total}")

# ---------- АДМИН: ВСЕ БУДУЩИЕ ЗАПИСИ ----------
@dp.message(F.text == "📋 Все будущие записи")
async def list_orders(message: Message):
    if message.from_user.id != ADMIN_ID:
        return
    orders = get_all_future_orders()
    if not orders:
        await message.answer("Нет записей.")
        return
    text = "🗓 Будущие записи:\n\n"
    for o in orders:
        text += f"ID {o[0]}: {o[2]} | {o[3]} {o[4]} | {o[5]}, тел:{o[6]}\n"
    await message.answer(text[:4000])

# ---------- АДМИН: РУЧНОЙ ВВОД (по телефону) ----------
@dp.message(F.text == "✏️ Ручной ввод (по телефону)")
async def manual_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите **услугу** (Стрижка / Борода / Стрижка+Борода):")
    await state.set_state("manual_service")

@dp.message(StateFilter("manual_service"))
async def manual_service(message: Message, state: FSMContext):
    text = message.text.strip()
    if text not in ["Стрижка", "Борода", "Стрижка+Борода"]:
        await message.answer("❌ Введите ровно: Стрижка, Борода или Стрижка+Борода")
        return
    await state.update_data(service=text)
    await message.answer("📅 Введите дату (ГГГГ-ММ-ДД):")
    await state.set_state("manual_date")

@dp.message(StateFilter("manual_date"))
async def manual_date(message: Message, state: FSMContext):
    date_str = message.text.strip()
    try:
        datetime.strptime(date_str, "%Y-%m-%d")
    except:
        await message.answer("❌ Неверный формат. Пишите ГГГГ-ММ-ДД, например 2026-05-20")
        return
    free_slots = [slot for slot in SLOTS if is_slot_free(date_str, slot)]
    if not free_slots:
        await message.answer("❌ На эту дату все часы заняты.")
        await state.clear()
        return
    await state.update_data(date=date_str)
    await message.answer(f"Свободные часы: {', '.join(free_slots)}\nВведите час (например 10:00-11:00):")
    await state.set_state("manual_slot")

@dp.message(StateFilter("manual_slot"))
async def manual_slot(message: Message, state: FSMContext):
    slot = message.text.strip()
    data = await state.get_data()
    if slot not in SLOTS or not is_slot_free(data['date'], slot):
        await message.answer("❌ Такой час недоступен. Выберите из списка свободных.")
        return
    await state.update_data(slot=slot)
    await message.answer("👤 Введите имя клиента:")
    await state.set_state("manual_name")

@dp.message(StateFilter("manual_name"))
async def manual_name(message: Message, state: FSMContext):
    await state.update_data(name=message.text.strip())
    await message.answer("📞 Введите телефон клиента:")
    await state.set_state("manual_phone")

@dp.message(StateFilter("manual_phone"))
async def manual_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    digits = re.sub(r'\D', '', phone)
    if len(digits) < 5:
        await message.answer("❌ Слишком короткий номер")
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    book_slot(data['date'], data['slot'], 0, data['service'], data['name'], data['phone'])
    await message.answer(f"✅ Заказ добавлен: {data['service']}, {data['date']} {data['slot']}, {data['name']}, {data['phone']}")
    await state.clear()

# ---------- АДМИН: ОТМЕНИТЬ ПО ID ----------
@dp.message(F.text == "❌ Отменить запись (админ)")
async def admin_cancel_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("Введите ID записи для отмены (цифру). Посмотреть ID можно в «Все будущие записи».")
    await state.set_state(AdminCancelState.waiting_for_id)

@dp.message(AdminCancelState.waiting_for_id)
async def admin_cancel_id(message: Message, state: FSMContext):
    try:
        order_id = int(message.text.strip())
    except:
        await message.answer("❌ Введите число")
        return
    success, _ = cancel_order_by_id(order_id, ADMIN_ID, is_admin=True)
    if success:
        await message.answer(f"✅ Заказ #{order_id} отменён. Слот освобождён.")
    else:
        await message.answer("❌ Заказ не найден или уже отменён.")
    await state.clear()

# ---------- КОМАНДЫ /ban и /unban для админа ----------
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

# ---------- НАПОМИНАНИЯ за 1 час ----------
async def send_reminders():
    now = datetime.now()
    for order_id, user_id, date_str, slot, phone in get_pending_reminders():
        start_hour = int(slot.split(":")[0])
        slot_start = datetime.strptime(f"{date_str} {start_hour:02d}:00", "%Y-%m-%d %H:%M")
        diff_hours = (slot_start - now).total_seconds() / 3600
        if 0.9 <= diff_hours <= 1.1:
            reminder_text = (
                f"✂️ **Напоминание!**\n"
                f"Через час ваша запись на {slot}\n"
                f"Мастер ждёт вас. Телефон мастера: {MASTER_PHONE}"
            )
            try:
                await bot.send_message(user_id, reminder_text)
                mark_reminder_sent(order_id)
            except:
                pass

# ---------- ЗАПУСК ----------
async def main():
    init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(send_reminders, 'interval', minutes=1)
    scheduler.start()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())