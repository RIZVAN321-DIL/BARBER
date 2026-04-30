from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime, timedelta

# ---------------------- КЛИЕНТСКОЕ МЕНЮ ----------------------
def main_menu():
    buttons = [
        [KeyboardButton(text="⚡ Записаться")],
        [KeyboardButton(text="📋 Мои записи")],
        [KeyboardButton(text="📞 Поделиться ботом")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ---------------------- АДМИНСКОЕ МЕНЮ ----------------------
def admin_menu():
    buttons = [
        [KeyboardButton(text="📋 Все записи")],
        [KeyboardButton(text="📞 Быстрая запись (по звонку)")],
        [KeyboardButton(text="❌ Отменить по ID")],
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📞 Поделиться ботом")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

# ---------------------- INLINE: УСЛУГИ ----------------------
def service_buttons():
    buttons = [
        [InlineKeyboardButton(text="💇‍♂️ Стрижка", callback_data="service_стрижка")],
        [InlineKeyboardButton(text="🧔 Борода", callback_data="service_борода")],
        [InlineKeyboardButton(text="💇‍♂️+🧔 Стрижка+Борода", callback_data="service_стрижка+борода")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------------------- INLINE: ВЫБОР "БЛИЖАЙШЕЕ ВРЕМЯ" ИЛИ "ВРУЧНУЮ" ----------------------
def quick_or_manual():
    buttons = [
        [InlineKeyboardButton(text="⚡ Ближайшее время", callback_data="quick_auto")],
        [InlineKeyboardButton(text="📅 Выбрать вручную", callback_data="manual_date")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ---------------------- INLINE: КАЛЕНДАРЬ (60 ДНЕЙ) ----------------------
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
    # Кнопка "Назад"
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ---------------------- INLINE: ВЫБОР ЧАСА (СЛОТЫ) ----------------------
def time_slots_buttons(free_slots):
    keyboard = []
    for slot in free_slots:
        keyboard.append([InlineKeyboardButton(text=slot, callback_data=f"slot_{slot}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_date")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ---------------------- INLINE: ПОДТВЕРЖДЕНИЕ ЗАПИСИ ----------------------
def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")]
    ])

# ---------------------- INLINE: КНОПКА ОТМЕНЫ ЗАПИСИ ДЛЯ КЛИЕНТА ----------------------
def cancel_order_inline(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{order_id}")]
    ])

# ---------------------- INLINE: ПОДТВЕРЖДЕНИЕ ОТМЕНЫ АДМИНОМ ----------------------
def confirm_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data="cancel_confirm_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_confirm_no")]
    ])