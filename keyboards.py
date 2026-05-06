from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, WebAppInfo
from datetime import datetime
from config import CLIENT_WEBAPP_URL

def main_menu():
    buttons = [
        [KeyboardButton(text="✂️ Записаться")],
        [KeyboardButton(text="📋 Мои записи")],
    ]
    if CLIENT_WEBAPP_URL:
        buttons.append([KeyboardButton(text="🌐 Запись через сайт", web_app=WebAppInfo(url=CLIENT_WEBAPP_URL))])
    buttons.append([KeyboardButton(text="📞 Поделиться ботом")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def admin_menu():
    buttons = [
        [KeyboardButton(text="📋 Все записи"), KeyboardButton(text="📞 Запись (звонок)")],
        [KeyboardButton(text="❌ Отменить/Перенести"), KeyboardButton(text="⛔ Выходной")],
        [KeyboardButton(text="🗓 Открыть день"), KeyboardButton(text="📊 Статистика")],
        [KeyboardButton(text="📜 История отмен")],
    ]
    if CLIENT_WEBAPP_URL:
        buttons.append([KeyboardButton(text="🌐 Запись через сайт", web_app=WebAppInfo(url=CLIENT_WEBAPP_URL))])
    buttons.append([KeyboardButton(text="📞 Поделиться ботом")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def barbers_keyboard(barbers):
    kb = [[InlineKeyboardButton(text=b[1], callback_data=f"barber_{b[0]}")] for b in barbers]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def services_keyboard(services):
    kb = [[InlineKeyboardButton(text=f"{s[1]} ({s[3]}₽ / {s[2]} мин)", callback_data=f"service_{s[0]}")] for s in services]
    return InlineKeyboardMarkup(inline_keyboard=kb)

def calendar_keyboard(year, month, blocked_dates=None):
    if blocked_dates is None:
        blocked_dates = []
    first_day = datetime(year, month, 1)
    start_weekday = first_day.weekday()
    if month == 12:
        next_month = datetime(year+1, 1, 1)
    else:
        next_month = datetime(year, month+1, 1)
    days_in_month = (next_month - first_day).days
    months = ["Январь","Февраль","Март","Апрель","Май","Июнь","Июль","Август","Сентябрь","Октябрь","Ноябрь","Декабрь"]
    keyboard = []
    nav = [
        InlineKeyboardButton(text="◀️", callback_data=f"cal_prev_{year}_{month}"),
        InlineKeyboardButton(text=f"{months[month-1]} {year}", callback_data="ignore"),
        InlineKeyboardButton(text="▶️", callback_data=f"cal_next_{year}_{month}")
    ]
    keyboard.append(nav)
    week_days = ["Пн","Вт","Ср","Чт","Пт","Сб","Вс"]
    keyboard.append([InlineKeyboardButton(text=d, callback_data="ignore") for d in week_days])
    row = []
    for _ in range(start_weekday):
        row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
    for day in range(1, days_in_month+1):
        date_str = f"{year:04d}-{month:02d}-{day:02d}"
        display = str(day)
        if date_str in blocked_dates:
            display += " ❌"
        row.append(InlineKeyboardButton(text=display, callback_data=f"date_{date_str}"))
        if len(row) == 7:
            keyboard.append(row)
            row = []
    if row:
        while len(row) < 7:
            row.append(InlineKeyboardButton(text=" ", callback_data="ignore"))
        keyboard.append(row)
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def slots_keyboard(slots):
    kb = [[InlineKeyboardButton(text=s, callback_data=f"slot_{s}")] for s in slots]
    kb.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_date")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def confirm_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Подтвердить", callback_data="confirm_yes")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="confirm_no")]
    ])

def phone_kb():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Отправить номер", request_contact=True)], [KeyboardButton(text="✍️ Ввести вручную")]],
        resize_keyboard=True,
        one_time_keyboard=True
    )

def cancel_order_inline(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="❌ Отменить", callback_data=f"cancel_{order_id}")]])

def admin_orders_list_keyboard(orders):
    """Список записей, сгруппированных по дням."""
    from collections import defaultdict
    grouped = defaultdict(list)
    for o in orders:
        grouped[o[3]].append(o)
    keyboard = []
    for date_str in sorted(grouped.keys()):
        keyboard.append([InlineKeyboardButton(text=f"📅 {date_str}", callback_data="ignore")])
        for o in grouped[date_str]:
            order_id = o[0]
            time_str = o[4]
            service = o[2]
            client = o[6]
            barber = o[5]
            btn_text = f"{time_str} {service} | {client} ({barber})"
            keyboard.append([InlineKeyboardButton(text=btn_text, callback_data=f"adm_sel_{order_id}")])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_to_menu")])
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

def admin_cancel_move_keyboard(order_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="❌ Отменить", callback_data=f"admin_cancel_{order_id}")],
        [InlineKeyboardButton(text="🔄 Перенести", callback_data=f"admin_move_{order_id}")]
    ])

def admin_move_confirm_keyboard(order_id, new_date, new_slot):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Перенести", callback_data=f"confirm_move_{order_id}_{new_date}_{new_slot}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
    ])

def block_day_confirm_keyboard(date_str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Заблокировать", callback_data=f"block_confirm_{date_str}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
    ])

def unblock_day_confirm_keyboard(date_str):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Открыть", callback_data=f"unblock_confirm_{date_str}")],
        [InlineKeyboardButton(text="❌ Отмена", callback_data="back_to_menu")]
    ])