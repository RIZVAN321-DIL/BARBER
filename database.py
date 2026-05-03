import asyncio
import sqlite3
from datetime import datetime, timedelta
import logging
from contextlib import asynccontextmanager
import aiosqlite
from config import TIMEZONE, WORK_SLOTS

logger = logging.getLogger(__name__)
DB_NAME = "barber.db"

def now_moscow():
    return datetime.now(TIMEZONE)

def today_str():
    return now_moscow().strftime("%Y-%m-%d")

@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_NAME, timeout=30.0) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA cache_size=-10000")  # 10MB cache
        yield db

async def init_db():
    async with get_db() as db:
        # Таблицы
        await db.execute('''
            CREATE TABLE IF NOT EXISTS orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                service TEXT,
                date TEXT,
                slot TEXT,
                client_name TEXT DEFAULT '',
                phone TEXT DEFAULT '',
                status TEXT DEFAULT 'active',
                reminder_sent24 INTEGER DEFAULT 0,
                reminder_sent2 INTEGER DEFAULT 0
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS bookings (
                date TEXT,
                slot TEXT,
                PRIMARY KEY (date, slot)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS blocked_slots (
                date TEXT,
                slot TEXT,
                PRIMARY KEY (date, slot)
            )
        ''')
        await db.execute('''
            CREATE TABLE IF NOT EXISTS banned_users (
                user_id INTEGER PRIMARY KEY
            )
        ''')
        # Индексы для ускорения
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_date_status ON orders(date, status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_orders_reminder ON orders(date, status, reminder_sent24, reminder_sent2)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bookings_date ON bookings(date)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_blocked_slots_date ON blocked_slots(date)")
        await db.commit()
    logger.info("База данных инициализирована с индексами и WAL")

# ---------- ОСНОВНЫЕ ФУНКЦИИ ----------
async def is_slot_free(date_str: str, slot: str) -> bool:
    async with get_db() as db:
        cur = await db.execute("SELECT 1 FROM bookings WHERE date=? AND slot=?", (date_str, slot))
        if await cur.fetchone():
            return False
        cur = await db.execute("SELECT 1 FROM blocked_slots WHERE date=? AND slot=?", (date_str, slot))
        blocked = await cur.fetchone() is not None
        return not blocked

# Семафор для контроля параллельных бронирований (не более 5 одновременных)
_booking_semaphore = asyncio.Semaphore(5)

async def book_slot(date_str, slot, user_id, service, client_name="", phone=""):
    async with _booking_semaphore:
        for attempt in range(3):
            try:
                async with get_db() as db:
                    # Проверка
                    cur = await db.execute("SELECT 1 FROM bookings WHERE date=? AND slot=?", (date_str, slot))
                    if await cur.fetchone():
                        return False
                    cur = await db.execute("SELECT 1 FROM blocked_slots WHERE date=? AND slot=?", (date_str, slot))
                    if await cur.fetchone():
                        return False
                    # Бронируем
                    await db.execute("INSERT INTO bookings (date, slot) VALUES (?, ?)", (date_str, slot))
                    await db.execute('''
                        INSERT INTO orders (user_id, service, date, slot, client_name, phone)
                        VALUES (?, ?, ?, ?, ?, ?)
                    ''', (user_id, service, date_str, slot, client_name, phone))
                    await db.commit()
                    logger.info(f"Запись создана: {date_str} {slot}, пользователь {user_id}")
                    return True
            except aiosqlite.OperationalError as e:
                if "database is locked" in str(e) and attempt < 2:
                    await asyncio.sleep(0.1 * (attempt + 1))
                    continue
                logger.error(f"Ошибка бронирования: {e}")
                return False
        return False

async def block_day(date_str):
    async with get_db() as db:
        cur = await db.execute("SELECT 1 FROM orders WHERE date=? AND status='active'", (date_str,))
        if await cur.fetchone():
            return False, "has_bookings"
        for slot in WORK_SLOTS:
            await db.execute("INSERT OR IGNORE INTO blocked_slots (date, slot) VALUES (?, ?)", (date_str, slot))
        await db.commit()
        return True, "ok"

async def unblock_day(date_str):
    async with get_db() as db:
        cur = await db.execute("SELECT 1 FROM orders WHERE date=? AND status='active'", (date_str,))
        if await cur.fetchone():
            return False, "has_bookings"
        await db.execute("DELETE FROM blocked_slots WHERE date=?", (date_str,))
        await db.commit()
        return True, "ok"

async def is_day_blocked(date_str) -> bool:
    async with get_db() as db:
        cur = await db.execute("SELECT 1 FROM blocked_slots WHERE date=?", (date_str,))
        return await cur.fetchone() is not None

async def get_active_order_count(user_id):
    async with get_db() as db:
        cur = await db.execute('''
            SELECT COUNT(*) FROM orders
            WHERE user_id=? AND status='active' AND date >= ?
        ''', (user_id, today_str()))
        row = await cur.fetchone()
        return row[0] if row else 0

async def get_user_orders(user_id):
    async with get_db() as db:
        cur = await db.execute('''
            SELECT id, service, date, slot, client_name, phone
            FROM orders
            WHERE user_id=? AND date >= ? AND status='active'
            ORDER BY date, slot
        ''', (user_id, today_str()))
        rows = await cur.fetchall()
        return [(row['id'], row['service'], row['date'], row['slot'], row['client_name'], row['phone']) for row in rows]

async def get_all_future_orders():
    async with get_db() as db:
        cur = await db.execute('''
            SELECT id, user_id, service, date, slot, client_name, phone
            FROM orders
            WHERE date >= ? AND status='active'
            ORDER BY date, slot
        ''', (today_str(),))
        rows = await cur.fetchall()
        return [(row['id'], row['user_id'], row['service'], row['date'], row['slot'], row['client_name'], row['phone']) for row in rows]

async def get_orders_for_today():
    async with get_db() as db:
        cur = await db.execute('''
            SELECT id, client_name, service, slot, phone
            FROM orders
            WHERE date=? AND status='active'
            ORDER BY slot
        ''', (today_str(),))
        rows = await cur.fetchall()
        return [(row['id'], row['client_name'], row['service'], row['slot'], row['phone']) for row in rows]

async def get_orders_for_tomorrow():
    tomorrow = (now_moscow() + timedelta(days=1)).strftime("%Y-%m-%d")
    async with get_db() as db:
        cur = await db.execute('''
            SELECT id, client_name, service, slot, phone
            FROM orders
            WHERE date=? AND status='active'
            ORDER BY slot
        ''', (tomorrow,))
        rows = await cur.fetchall()
        return [(row['id'], row['client_name'], row['service'], row['slot'], row['phone']) for row in rows]

async def get_order_by_id(order_id):
    async with get_db() as db:
        cur = await db.execute('''
            SELECT id, user_id, service, date, slot, client_name, phone, status
            FROM orders WHERE id=?
        ''', (order_id,))
        row = await cur.fetchone()
        if row:
            return (row['id'], row['user_id'], row['service'], row['date'], row['slot'], row['client_name'], row['phone'], row['status'])
        return None

async def cancel_order(order_id, user_id, is_admin=False):
    async with get_db() as db:
        cur = await db.execute("SELECT date, slot, user_id FROM orders WHERE id=? AND status='active'", (order_id,))
        row = await cur.fetchone()
        if not row:
            return False, "not_found"
        date_str, slot, owner_id = row
        if not is_admin and owner_id != user_id:
            return False, "not_yours"
        if not is_admin:
            slot_start_hour = int(slot.split(":")[0])
            slot_dt = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
            if (slot_dt - now_moscow().replace(tzinfo=None)).total_seconds() < 2 * 3600:
                return False, "too_late"
        await db.execute("DELETE FROM bookings WHERE date=? AND slot=?", (date_str, slot))
        await db.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
        await db.commit()
        logger.info(f"Запись #{order_id} отменена (админ: {is_admin})")
        return True, owner_id

async def get_orders_for_reminder_24h():
    tomorrow = (now_moscow() + timedelta(days=1)).strftime("%Y-%m-%d")
    async with get_db() as db:
        cur = await db.execute('''
            SELECT id, user_id, date, slot, phone
            FROM orders
            WHERE date = ? AND status='active' AND reminder_sent24 = 0 AND user_id != 0
        ''', (tomorrow,))
        rows = await cur.fetchall()
        return [(row['id'], row['user_id'], row['date'], row['slot'], row['phone']) for row in rows]

async def get_orders_for_reminder_2h():
    today = today_str()
    now_hour = now_moscow().hour
    async with get_db() as db:
        # вытаскиваем все активные записи на сегодня без напоминания 2ч
        cur = await db.execute('''
            SELECT id, user_id, date, slot, phone
            FROM orders
            WHERE date = ? AND status='active' AND reminder_sent2 = 0 AND user_id != 0
        ''', (today,))
        rows = await cur.fetchall()
    # Фильтруем по времени в Python (нагрузка мала)
    result = []
    for row in rows:
        slot_hour = int(row['slot'].split("-")[0].split(":")[0])
        if slot_hour - now_hour == 2:
            result.append((row['id'], row['user_id'], row['date'], row['slot'], row['phone']))
    return result

async def mark_reminder_sent(order_id, type_):
    async with get_db() as db:
        if type_ == '24h':
            await db.execute("UPDATE orders SET reminder_sent24 = 1 WHERE id = ?", (order_id,))
        elif type_ == '2h':
            await db.execute("UPDATE orders SET reminder_sent2 = 1 WHERE id = ?", (order_id,))
        await db.commit()

async def is_user_banned(user_id):
    async with get_db() as db:
        cur = await db.execute("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,))
        return await cur.fetchone() is not None

async def ban_user(user_id):
    async with get_db() as db:
        await db.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
        await db.commit()
    logger.info(f"Пользователь {user_id} забанен")

async def unban_user(user_id):
    async with get_db() as db:
        await db.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
        await db.commit()
    logger.info(f"Пользователь {user_id} разбанен")

# ---------- ПЕРЕНОС ЗАПИСИ ----------
async def move_booking(order_id, new_date, new_slot):
    async with get_db() as db:
        cur = await db.execute("SELECT date, slot FROM orders WHERE id=?", (order_id,))
        row = await cur.fetchone()
        if not row:
            return None, None
        old_date, old_slot = row['date'], row['slot']
        await db.execute("DELETE FROM bookings WHERE date=? AND slot=?", (old_date, old_slot))
        await db.execute("INSERT INTO bookings (date, slot) VALUES (?, ?)", (new_date, new_slot))
        await db.execute("UPDATE orders SET date=?, slot=? WHERE id=?", (new_date, new_slot, order_id))
        await db.commit()
        return old_date, old_slot