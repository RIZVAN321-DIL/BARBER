import sqlite3
from datetime import datetime, timedelta

DB_NAME = "barber.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Таблица заказов
    cur.execute('''
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            service TEXT,
            date TEXT,
            slot TEXT,
            client_name TEXT,
            phone TEXT,
            status TEXT DEFAULT 'active',
            reminder_sent INTEGER DEFAULT 0
        )
    ''')
    # Таблица занятых слотов
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            date TEXT,
            slot TEXT,
            PRIMARY KEY (date, slot)
        )
    ''')
    # Таблица забаненных пользователей
    cur.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    # Добавляем колонку client_name, если её нет (для старых баз)
    cur.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cur.fetchall()]
    if "client_name" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN client_name TEXT")
    if "reminder_sent" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN reminder_sent INTEGER DEFAULT 0")
    conn.commit()
    conn.close()

def is_slot_free(date_str, slot):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND slot=?", (date_str, slot))
    free = cur.fetchone() is None
    conn.close()
    return free

def book_slot(date_str, slot, user_id, service, client_name, phone):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (date, slot) VALUES (?, ?)", (date_str, slot))
    cur.execute('''
        INSERT INTO orders (user_id, service, date, slot, client_name, phone, reminder_sent)
        VALUES (?, ?, ?, ?, ?, ?, 0)
    ''', (user_id, service, date_str, slot, client_name, phone))
    conn.commit()
    conn.close()

def count_active_bookings(user_id):
    """Количество активных будущих записей у пользователя"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT COUNT(*) FROM orders
        WHERE user_id=? AND status='active' AND date >= date('now')
    ''', (user_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count

def is_user_banned(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,))
    banned = cur.fetchone() is not None
    conn.close()
    return banned

def ban_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

def unban_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM banned_users WHERE user_id=?", (user_id,))
    conn.commit()
    conn.close()

def cancel_order_by_id(order_id, user_id, is_admin=False):
    """Отмена заказа. Для клиента проверяем, что заказ его и можно отменить (до 2 часов)"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT date, slot, user_id FROM orders WHERE id=?", (order_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, None
    date_str, slot, owner_id = row
    if not is_admin and owner_id != user_id:
        conn.close()
        return False, "not_yours"
    # Проверка времени для клиента (нельзя отменить за 2 часа и менее)
    if not is_admin and owner_id == user_id:
        slot_start_hour = int(slot.split(":")[0])
        slot_datetime = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        if (slot_datetime - datetime.now()).total_seconds() < 2 * 3600:
            conn.close()
            return False, "too_late"
    # Освобождаем слот и помечаем заказ отменённым
    cur.execute("DELETE FROM bookings WHERE date=? AND slot=?", (date_str, slot))
    cur.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return True, owner_id

def get_user_active_orders(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, service, date, slot, client_name, phone
        FROM orders
        WHERE user_id=? AND date >= date('now') AND status='active'
        ORDER BY date, slot
    ''', (user_id,))
    orders = cur.fetchall()
    conn.close()
    return orders

def get_all_future_orders():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, user_id, service, date, slot, client_name, phone
        FROM orders
        WHERE date >= date('now') AND status='active'
        ORDER BY date, slot
    ''')
    orders = cur.fetchall()
    conn.close()
    return orders

def get_pending_reminders():
    """Заказы на сегодня, напоминание ещё не отправлено"""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    today = datetime.now().strftime("%Y-%m-%d")
    cur.execute('''
        SELECT id, user_id, date, slot, phone
        FROM orders
        WHERE date = ? AND status='active' AND reminder_sent = 0 AND user_id != 0
    ''', (today,))
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_reminder_sent(order_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE orders SET reminder_sent = 1 WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()

def get_order_by_id(order_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT date, slot, user_id FROM orders WHERE id=?", (order_id,))
    row = cur.fetchone()
    conn.close()
    return row