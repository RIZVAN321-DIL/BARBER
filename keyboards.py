from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime, timedelta

# ГЛАВНОЕ МЕНЮ КЛИЕНТА
def main_menu():
    buttons = [
        [KeyboardButton(text="💇‍♂️ Стрижка")],
        [KeyboardButton(text="🧔 Борода")],
        [KeyboardButton(text="💇‍♂️+🧔 Стрижка + Борода")],
        [KeyboardButton(text="📋 Мои записи")],
        [KeyboardButton(text="📞 Поделиться ботом")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# АДМИНСКОЕ МЕНЮ
def admin_menu():
    buttons = [
        [KeyboardButton(text="📊 Аналитика")],
        [KeyboardButton(text="📋 Все будущие записи")],
        [KeyboardButton(text="✏️ Ручной ввод (по телефону)")],
        [KeyboardButton(text="❌ Отменить запись (админ)")],
        [KeyboardButton(text="💇‍♂️ Стрижка")],
        [KeyboardButton(text="🧔 Борода")],
        [KeyboardButton(text="💇‍♂️+🧔 Стрижка + Борода")],
        [KeyboardButton(text="📞 Поделиться ботом")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# КАЛЕНДАРЬ НА 60 ДНЕЙ
def calendar_keyboard(blocked_dates):
    keyboard = []
    start = datetime.now()
    for i in range(0, 60, 7):
        row = []
        for j in range(7):
            if i + j >= 60:
                break
            day = start + timedelta(days=i + j)
            date_str = day.strftime("%Y-%m-%d")
            display = day.strftime("%d.%m")
            if date_str in blocked_dates:
                display += " ❌"
            callback = f"date_{date_str}"
            row.append(InlineKeyboardButton(text=display, callback_data=callback))
        keyboard.append(row)
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# КНОПКИ ВРЕМЕНИ (слоты по часам)
def time_slots_buttons(free_slots):
    keyboard = []
    for slot in free_slots:
        keyboard.append([InlineKeyboardButton(text=slot, callback_data=f"slot_{slot}")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ПОДТВЕРЖДЕНИЕ ЗАПИСИ
def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, записаться", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")]
    ])

# КНОПКИ ДЛЯ ОТМЕНЫ ЗАПИСИ КЛИЕНТОМ (внутри списка)
def cancel_order_inline(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить запись", callback_data=f"cancel_{order_id}")]
    ])

# ПОДТВЕРЖДЕНИЕ ОТМЕНЫ
def confirm_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data="cancel_confirm_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_confirm_no")]
    ])