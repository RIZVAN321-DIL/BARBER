import sqlite3
import logging
from datetime import datetime, timedelta
from config import TIMEZONE

logger = logging.getLogger(__name__)
DB_NAME = "barber.db"

def now_moscow():
    return datetime.now(TIMEZONE)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.executescript('''
        CREATE TABLE IF NOT EXISTS barbers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            work_start TEXT DEFAULT '09:00',
            work_end TEXT DEFAULT '19:00'
        );
        CREATE TABLE IF NOT EXISTS services (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            duration_min INTEGER NOT NULL,
            price INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            barber_id INTEGER,
            service_id INTEGER,
            date TEXT,
            time TEXT,
            client_name TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            reminder_sent24 INTEGER DEFAULT 0,
            reminder_sent2 INTEGER DEFAULT 0,
            rating INTEGER DEFAULT 0,
            review TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS blocked_slots (
            date TEXT,
            time TEXT,
            barber_id INTEGER,
            PRIMARY KEY (date, time, barber_id)
        );
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY
        );
        -- Начальные данные, если таблицы пустые
        INSERT OR IGNORE INTO barbers (id, name) VALUES (1, 'Мастер 1');
        INSERT OR IGNORE INTO services (id, name, duration_min, price) VALUES
            (1, 'Стрижка', 60, 1500),
            (2, 'Борода', 30, 800),
            (3, 'Стрижка + Борода', 90, 2000);
    ''')
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована")

def get_all_barbers():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM barbers")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_barber(barber_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, name, work_start, work_end FROM barbers WHERE id=?", (barber_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_all_services():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, name, duration_min, price FROM services")
    rows = cur.fetchall()
    conn.close()
    return rows

def get_service(service_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, name, duration_min, price FROM services WHERE id=?", (service_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_free_slots(date_str, barber_id, service_duration):
    """Возвращает список свободных временных окон для конкретного барбера и услуги"""
    barber = get_barber(barber_id)
    if not barber:
        return []
    start_h, start_m = map(int, barber[2].split(':'))
    end_h, end_m = map(int, barber[3].split(':'))
    step = 60  # минимальный шаг слота в минутах
    slots = []
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    current_minutes = start_h * 60 + start_m
    end_minutes = end_h * 60 + end_m
    now = now_moscow()
    while current_minutes + service_duration <= end_minutes:
        time_str = f"{current_minutes//60:02d}:{current_minutes%60:02d}"
        # Проверка на прошедшее время (только для сегодняшнего дня)
        if date_str == now.strftime("%Y-%m-%d"):
            if current_minutes <= now.hour * 60 + now.minute:
                current_minutes += step
                continue
        # Проверка занятости
        cur.execute("SELECT 1 FROM orders WHERE date=? AND time=? AND barber_id=? AND status='active'",
                    (date_str, time_str, barber_id))
        if cur.fetchone():
            current_minutes += step
            continue
        cur.execute("SELECT 1 FROM blocked_slots WHERE date=? AND time=? AND barber_id=?",
                    (date_str, time_str, barber_id))
        if cur.fetchone():
            current_minutes += step
            continue
        slots.append(time_str)
        current_minutes += step
    conn.close()
    return slots

def book_slot(date_str, time_str, user_id, barber_id, service_id, name, phone):
    conn = sqlite3.connect(DB_NAME)
    try:
        cur = conn.cursor()
        # Двойная проверка перед бронированием
        cur.execute("SELECT 1 FROM orders WHERE date=? AND time=? AND barber_id=? AND status='active'",
                    (date_str, time_str, barber_id))
        if cur.fetchone():
            return False
        cur.execute("INSERT INTO orders (user_id, barber_id, service_id, date, time, client_name, phone) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (user_id, barber_id, service_id, date_str, time_str, name, phone))
        conn.commit()
        logger.info(f"Запись создана: {date_str} {time_str}, пользователь {user_id}")
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Ошибка бронирования: {e}")
        return False
    finally:
        conn.close()

def get_user_orders(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT o.id, s.name, o.date, o.time, b.name, o.client_name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.user_id=? AND o.date >= date('now','localtime') AND o.status='active'
        ORDER BY o.date, o.time
    ''', (user_id,))
    orders = cur.fetchall()
    conn.close()
    return orders

def get_all_future_orders():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT o.id, o.user_id, s.name, o.date, o.time, b.name, o.client_name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.date >= date('now','localtime') AND o.status='active'
        ORDER BY o.date, o.time
    ''')
    orders = cur.fetchall()
    conn.close()
    return orders

def cancel_order(order_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    return True

def get_order_by_id(order_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT o.id, o.user_id, s.name, o.date, o.time, b.name, o.client_name, o.phone, o.status
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.id=?
    ''', (order_id,))
    order = cur.fetchone()
    conn.close()
    return order

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

def get_orders_for_today():
    today = now_moscow().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, client_name, (SELECT name FROM services WHERE id=o.service_id), time, (SELECT name FROM barbers WHERE id=o.barber_id), phone FROM orders o WHERE date=? AND status='active' ORDER BY time", (today,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_orders_for_tomorrow():
    tomorrow = (now_moscow() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, client_name, (SELECT name FROM services WHERE id=o.service_id), time, (SELECT name FROM barbers WHERE id=o.barber_id), phone FROM orders o WHERE date=? AND status='active' ORDER BY time", (tomorrow,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_orders_for_reminder_24h():
    tomorrow = (now_moscow() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, user_id, date, time, phone FROM orders WHERE date=? AND status='active' AND reminder_sent24=0 AND user_id!=0", (tomorrow,))
    rows = cur.fetchall()
    conn.close()
    return rows

def mark_reminder_sent(order_id, type_):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if type_ == '24h':
        cur.execute("UPDATE orders SET reminder_sent24=1 WHERE id=?", (order_id,))
    elif type_ == '2h':
        cur.execute("UPDATE orders SET reminder_sent2=1 WHERE id=?", (order_id,))
    conn.commit()
    conn.close()

def get_active_order_count(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='active' AND date >= date('now','localtime')", (user_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count