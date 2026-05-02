from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from datetime import datetime, timedelta
from config import WORK_SLOTS

def main_menu():
    buttons = [
        [KeyboardButton(text="⚡ Записаться")],
        [KeyboardButton(text="📋 Мои записи")],
        [KeyboardButton(text="📞 Поделиться ботом")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def admin_menu():
    buttons = [
        [KeyboardButton(text="📋 Все записи")],
        [KeyboardButton(text="📞 Быстрая запись (по звонку)")],
        [KeyboardButton(text="❌ Отменить по ID")],
        [KeyboardButton(text="⛔ Выходной")],          # новая кнопка
        [KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📞 Поделиться ботом")]
    ]
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def service_buttons():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💇‍♂️ Стрижка", callback_data="service_стрижка")],
        [InlineKeyboardButton(text="🧔 Борода", callback_data="service_борода")],
        [InlineKeyboardButton(text="💇‍♂️+🧔 Стрижка+Борода", callback_data="service_стрижка+борода")]
    ])

def quick_or_manual():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⚡ Ближайшее время", callback_data="quick_auto")],
        [InlineKeyboardButton(text="📅 Выбрать вручную", callback_data="manual_date")]
    ])

def calendar_keyboard(blocked_dates, month_name):
    """Компактный календарь: кнопки с числами (без месяца), месяц выводится отдельно."""
    keyboard = []
    start = datetime.now()
    for i in range(0, 60, 7):
        row = []
        for j in range(7):
            if i + j >= 60:
                break
            day = start + timedelta(days=i + j)
            date_str = day.strftime("%Y-%m-%d")
            # Показываем только число (без точки)
            display = str(day.day)
            if date_str in blocked_dates:
                display += " ❌"
            callback = f"date_{date_str}"
            row.append(InlineKeyboardButton(text=display, callback_data=callback))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def time_slots_buttons(free_slots):
    keyboard = []
    for slot in free_slots:
        keyboard.append([InlineKeyboardButton(text=slot, callback_data=f"slot_{slot}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад к дате", callback_data="back_to_date")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")]
    ])

def admin_confirm_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_admin_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")]
    ])

def skip_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⏩ Пропустить", callback_data="skip")]
    ])

def cancel_order_inline(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"client_cancel_{order_id}")]
    ])

def confirm_cancel_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, отменить", callback_data="cancel_confirm_yes")],
        [InlineKeyboardButton(text="❌ Нет", callback_data="cancel_confirm_no")]
    ])

def confirm_block_day_keyboard():
    """Подтверждение блокировки дня (для админа)"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, заблокировать день", callback_data="block_day_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="block_day_no")]
    ])