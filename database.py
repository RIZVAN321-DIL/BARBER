import sqlite3
from datetime import datetime, timedelta

DB_NAME = "barber.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
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
    cur.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            date TEXT,
            slot TEXT,
            PRIMARY KEY (date, slot)
        )
    ''')
    cur.execute('''
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY
        )
    ''')
    # Миграция для старых таблиц
    cur.execute("PRAGMA table_info(orders)")
    columns = [col[1] for col in cur.fetchall()]
    if "client_name" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN client_name TEXT DEFAULT ''")
    if "phone" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN phone TEXT DEFAULT ''")
    if "reminder_sent24" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN reminder_sent24 INTEGER DEFAULT 0")
    if "reminder_sent2" not in columns:
        cur.execute("ALTER TABLE orders ADD COLUMN reminder_sent2 INTEGER DEFAULT 0")
    conn.commit()
    conn.close()

def is_slot_free(date_str, slot):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM bookings WHERE date=? AND slot=?", (date_str, slot))
    free = cur.fetchone() is None
    conn.close()
    return free

def book_slot(date_str, slot, user_id, service, client_name="", phone=""):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO bookings (date, slot) VALUES (?, ?)", (date_str, slot))
    cur.execute('''
        INSERT INTO orders (user_id, service, date, slot, client_name, phone)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (user_id, service, date_str, slot, client_name, phone))
    conn.commit()
    conn.close()

def get_active_order_count(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT COUNT(*) FROM orders
        WHERE user_id=? AND status='active' AND date >= date('now')
    ''', (user_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count

def get_user_orders(user_id):
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

def get_orders_for_today():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, client_name, service, slot, phone
        FROM orders
        WHERE date = ? AND status='active'
        ORDER BY slot
    ''', (today,))
    orders = cur.fetchall()
    conn.close()
    return orders

def get_orders_for_tomorrow():
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, client_name, service, slot, phone
        FROM orders
        WHERE date = ? AND status='active'
        ORDER BY slot
    ''', (tomorrow,))
    orders = cur.fetchall()
    conn.close()
    return orders

def get_order_by_id(order_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, user_id, service, date, slot, client_name, phone, status
        FROM orders WHERE id=?
    ''', (order_id,))
    order = cur.fetchone()
    conn.close()
    return order

def cancel_order(order_id, user_id, is_admin=False):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT date, slot, user_id FROM orders WHERE id=? AND status='active'", (order_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return False, "not_found"
    date_str, slot, owner_id = row
    if not is_admin and owner_id != user_id:
        conn.close()
        return False, "not_yours"
    if not is_admin:
        slot_start_hour = int(slot.split(":")[0])
        slot_dt = datetime.strptime(f"{date_str} {slot_start_hour:02d}:00", "%Y-%m-%d %H:%M")
        if (slot_dt - datetime.now()).total_seconds() < 2 * 3600:
            conn.close()
            return False, "too_late"
    cur.execute("DELETE FROM bookings WHERE date=? AND slot=?", (date_str, slot))
    cur.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return True, owner_id

def get_orders_for_reminder_24h():
    """Заказы на завтра, у которых ещё не отправлено напоминание за 24 часа."""
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, user_id, date, slot, phone
        FROM orders
        WHERE date = ? AND status='active' AND reminder_sent24 = 0 AND user_id != 0
    ''', (tomorrow,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_orders_for_reminder_2h():
    """Заказы на сегодня, у которых ещё не отправлено напоминание за 2 часа."""
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT id, user_id, date, slot, phone
        FROM orders
        WHERE date = ? AND status='active' AND reminder_sent2 = 0 AND user_id != 0
    ''', (today,))
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_reminder_sent(order_id, type_):
    """type_: '24h' или '2h'."""
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if type_ == '24h':
        cur.execute("UPDATE orders SET reminder_sent24 = 1 WHERE id = ?", (order_id,))
    elif type_ == '2h':
        cur.execute("UPDATE orders SET reminder_sent2 = 1 WHERE id = ?", (order_id,))
    conn.commit()
    conn.close()

def is_user_banned(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM banned_users WHERE user_id=?", (user_id,))
    banned = cur.fetchone() is not None
    conn.close()
    return banned