import os
import asyncio
import sqlite3
from datetime import datetime, timedelta

from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.utils.keyboard import InlineKeyboardBuilder

from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ---------------- CONFIG ----------------

TOKEN = os.getenv("TOKEN", "PUT_YOUR_TOKEN_HERE")
ADMIN_ID = int(os.getenv("ADMIN_ID", "123456789"))
ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+10000000000")

if not TOKEN or TOKEN == "PUT_YOUR_TOKEN_HERE":
    raise ValueError("TOKEN is not set")

# ---------------- INIT ----------------

bot = Bot(TOKEN)
dp = Dispatcher()
scheduler = AsyncIOScheduler()

db = sqlite3.connect("barber_v3.db")
cur = db.cursor()

# ---------------- DB ----------------

cur.execute("""
CREATE TABLE IF NOT EXISTS bookings(
id INTEGER PRIMARY KEY AUTOINCREMENT,
user_id INTEGER,
service TEXT,
date TEXT,
time TEXT,
status TEXT
)
""")

cur.execute("""
CREATE TABLE IF NOT EXISTS blocked_slots(
date TEXT,
time TEXT
)
""")

db.commit()

# ---------------- CONFIG BUSINESS ----------------

SERVICES = ["Стрижка", "Борода", "Стрижка + борода"]

WORK_START = 8
WORK_END = 17

# ---------------- HELPERS ----------------

def get_active(user_id):
    cur.execute("SELECT * FROM bookings WHERE user_id=? AND status='active'", (user_id,))
    return cur.fetchone()

def set_cancel(booking_id):
    cur.execute("UPDATE bookings SET status='cancelled' WHERE id=?", (booking_id,))
    db.commit()

def update_booking(booking_id, date, time):
    cur.execute("""
    UPDATE bookings
    SET date=?, time=?
    WHERE id=?
    """, (date, time, booking_id))
    db.commit()

def is_blocked(date, time):
    cur.execute("SELECT 1 FROM blocked_slots WHERE date=? AND time=?", (date, time))
    return cur.fetchone()

def save_booking(user_id, service, date, time):
    cur.execute("""
    INSERT INTO bookings(user_id, service, date, time, status)
    VALUES (?, ?, ?, ?, 'active')
    """, (user_id, service, date, time))
    db.commit()

def gen_slots():
    return [f"{h:02d}:00" for h in range(WORK_START, WORK_END)]

# ---------------- START ----------------

@dp.message(Command("start"))
async def start(m: Message):
    kb = InlineKeyboardBuilder()
    kb.button(text="✂ Запись", callback_data="book")
    kb.button(text="📋 Мои записи", callback_data="my")

    await m.answer("Barber CRM", reply_markup=kb.as_markup())

# ---------------- BOOKING ----------------

@dp.callback_query(F.data == "book")
async def book(c: CallbackQuery):
    kb = InlineKeyboardBuilder()
    for s in SERVICES:
        kb.button(text=s, callback_data=f"service:{s}")

    await c.message.answer("Выбери услугу:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("service:"))
async def service(c: CallbackQuery):
    service = c.data.split(":")[1]

    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data=f"date:0:{service}")
    kb.button(text="Завтра", callback_data=f"date:1:{service}")

    await c.message.answer("Выбери дату:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("date:"))
async def date(c: CallbackQuery):
    _, d, service = c.data.split(":")
    date = (datetime.now() + timedelta(days=int(d))).strftime("%Y-%m-%d")

    await show_times(c, date, service)

async def show_times(c, date, service, mode="new"):
    kb = InlineKeyboardBuilder()

    for t in gen_slots():
        if not is_blocked(date, t):
            kb.button(text=t, callback_data=f"time:{date}:{t}:{service}:{mode}")

    await c.message.answer(f"Слоты {date}", reply_markup=kb.as_markup())

# ---------------- CREATE / RESCHEDULE ----------------

@dp.callback_query(F.data.startswith("time:"))
async def time(c: CallbackQuery):
    _, date, t, service, mode = c.data.split(":")

    uid = c.from_user.id
    booking = get_active(uid)

    # ---------------- NEW BOOKING ----------------
    if mode == "new":
        if booking:
            await c.message.answer("У тебя уже есть запись. Используй перенос.")
            return

        save_booking(uid, service, date, t)
        await c.message.answer(f"Запись создана:\n{service}\n{date} {t}")
        schedule_reminders(uid, service, date, t)
        return

    # ---------------- RESCHEDULE ----------------
    if mode == "reschedule":
        if not booking:
            await c.message.answer("Нет активной записи.")
            return

        update_booking(booking[0], date, t)

        await c.message.answer(f"Запись перенесена:\n{date} {t}")
        schedule_reminders(uid, booking[2], date, t)

# ---------------- MY BOOKINGS ----------------

@dp.callback_query(F.data == "my")
async def my(c: CallbackQuery):
    cur.execute("SELECT id,service,date,time FROM bookings WHERE user_id=? AND status='active'", (c.from_user.id,))
    r = cur.fetchone()

    if not r:
        await c.message.answer("Нет записей")
        return

    kb = InlineKeyboardBuilder()
    kb.button(text="🔁 Перенести", callback_data=f"reschedule:{r[0]}:{r[2]}")
    kb.button(text="❌ Отменить", callback_data=f"cancel:{r[0]}")

    await c.message.answer(
        f"{r[1]}\n{r[2]} {r[3]}",
        reply_markup=kb.as_markup()
    )

# ---------------- RESCHEDULE FLOW ----------------

@dp.callback_query(F.data.startswith("reschedule:"))
async def reschedule(c: CallbackQuery):
    _, bid, service_date = c.data.split(":")

    kb = InlineKeyboardBuilder()
    kb.button(text="Сегодня", callback_data=f"rs_date:0:{bid}")
    kb.button(text="Завтра", callback_data=f"rs_date:1:{bid}")

    await c.message.answer("Выбери новую дату:", reply_markup=kb.as_markup())

@dp.callback_query(F.data.startswith("rs_date:"))
async def rs_date(c: CallbackQuery):
    _, d, bid = c.data.split(":")
    date = (datetime.now() + timedelta(days=int(d))).strftime("%Y-%m-%d")

    cur.execute("SELECT service FROM bookings WHERE id=?", (bid,))
    service = cur.fetchone()[0]

    await show_times_for_reschedule(c, date, service, bid)

async def show_times_for_reschedule(c, date, service, bid):
    kb = InlineKeyboardBuilder()

    for t in gen_slots():
        if not is_blocked(date, t):
            kb.button(text=t, callback_data=f"time:{date}:{t}:{service}:reschedule:{bid}")

    await c.message.answer(f"Перенос на {date}", reply_markup=kb.as_markup())

# ---------------- CANCEL ----------------

@dp.callback_query(F.data.startswith("cancel:"))
async def cancel(c: CallbackQuery):
    _, bid = c.data.split(":")
    set_cancel(bid)
    await c.message.answer("Запись отменена")

# ---------------- REMINDERS ----------------

def schedule_reminders(uid, service, date, time):
    dt = datetime.strptime(f"{date} {time}", "%Y-%m-%d %H:%M")

    async def send(h):
        await asyncio.sleep(max(0, (dt - timedelta(hours=h) - datetime.now()).total_seconds()))
        await bot.send_message(uid, f"Напоминание: {service} через {h} часов")

    asyncio.create_task(send(24))
    asyncio.create_task(send(3))

# ---------------- RUN ----------------

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())