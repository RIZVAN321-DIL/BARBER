import sqlite3
import logging
from datetime import datetime, timedelta
from config import TIMEZONE, MAX_SLOTS_PER_DAY

logger = logging.getLogger(__name__)
DB_NAME = "barber.db"

def now_moscow():
    return datetime.now(TIMEZONE)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Включаем WAL и синхронизацию NORMAL для конкурентности
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
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
            start_min INTEGER NOT NULL,
            end_min INTEGER NOT NULL,
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
            start_min INTEGER,
            barber_id INTEGER,
            PRIMARY KEY (date, start_min, barber_id)
        );
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id INTEGER PRIMARY KEY
        );
    ''')
    # Индексы для ускорения
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_date_barber ON orders(date, barber_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_user ON orders(user_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)")
    # Уникальный индекс по активным слотам
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_active_slot ON orders(date, start_min, barber_id) WHERE status='active'")
    # Начальные данные
    cur.execute("INSERT OR IGNORE INTO barbers (id, name) VALUES (1, 'Мастер 1')")
    cur.execute("INSERT OR IGNORE INTO services (id, name, duration_min, price) VALUES (1, 'Стрижка', 60, 1500), (2, 'Борода', 30, 800), (3, 'Стрижка + Борода', 90, 2000)")
    conn.commit()
    conn.close()
    logger.info("База данных инициализирована (WAL, индексы)")

def time_str_to_min(time_str: str) -> int:
    h, m = map(int, time_str.split(':'))
    return h * 60 + m

def min_to_time_str(minutes: int) -> str:
    return f"{minutes//60:02d}:{minutes%60:02d}"

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
    """Возвращает список свободных окон в формате 'HH:MM' с учётом пересечений."""
    barber = get_barber(barber_id)
    if not barber:
        return []
    start_day_min = time_str_to_min(barber[2])
    end_day_min = time_str_to_min(barber[3])
    step = 30
    slots = []
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    now = now_moscow()
    current = start_day_min
    while current + service_duration <= end_day_min:
        # Для сегодняшнего дня пропускаем прошедшие слоты
        if date_str == now.strftime("%Y-%m-%d"):
            now_min = now.hour * 60 + now.minute
            if current <= now_min:
                current += step
                continue
        # Проверка пересечений с активными записями
        cur.execute("""
            SELECT 1 FROM orders
            WHERE date=? AND barber_id=? AND status='active'
            AND start_min < ? AND end_min > ?
        """, (date_str, barber_id, current + service_duration, current))
        if cur.fetchone():
            current += step
            continue
        # Проверка блокировок
        cur.execute("SELECT 1 FROM blocked_slots WHERE date=? AND barber_id=? AND start_min=?",
                    (date_str, barber_id, current))
        if cur.fetchone():
            current += step
            continue
        slots.append(min_to_time_str(current))
        current += step
    conn.close()
    return slots

def find_first_free_slot(barber_id, service_id):
    """Ближайший свободный слот для услуги у мастера, начиная с сегодня."""
    service = get_service(service_id)
    if not service:
        return None, None
    now = now_moscow()
    for i in range(14):
        check_date = (now + timedelta(days=i)).strftime("%Y-%m-%d")
        slots = get_free_slots(check_date, barber_id, service[2])
        if slots:
            return check_date, slots[0]
    return None, None

def book_slot(date_str, time_str, user_id, barber_id, service_id, name, phone):
    """Бронирование с защитой от гонки через транзакцию."""
    service = get_service(service_id)
    if not service:
        return False
    duration = service[2]
    start_min = time_str_to_min(time_str)
    end_min = start_min + duration
    conn = sqlite3.connect(DB_NAME)
    try:
        # Транзакция с немедленной блокировкой
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.cursor()
        # Проверка лимита
        if MAX_SLOTS_PER_DAY > 0:
            cur.execute("SELECT COUNT(*) FROM orders WHERE date=? AND barber_id=? AND status='active'", (date_str, barber_id))
            if cur.fetchone()[0] >= MAX_SLOTS_PER_DAY:
                conn.rollback()
                return False
        # Проверка пересечений
        cur.execute("""
            SELECT 1 FROM orders
            WHERE date=? AND barber_id=? AND status='active'
            AND start_min < ? AND end_min > ?
        """, (date_str, barber_id, end_min, start_min))
        if cur.fetchone():
            conn.rollback()
            return False
        # Вставка
        cur.execute("""
            INSERT INTO orders (user_id, barber_id, service_id, date, start_min, end_min, client_name, phone)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, barber_id, service_id, date_str, start_min, end_min, name, phone))
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
    today = now_moscow().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT o.id, s.name, o.date, o.start_min, b.name, o.client_name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.user_id=? AND o.date >= ? AND o.status='active'
        ORDER BY o.date, o.start_min
    ''', (user_id, today))
    orders = []
    for row in cur.fetchall():
        orders.append((row[0], row[1], row[2], min_to_time_str(row[3]), row[4], row[5], row[6]))
    conn.close()
    return orders

def get_all_future_orders():
    today = now_moscow().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute('''
        SELECT o.id, o.user_id, s.name, o.date, o.start_min, b.name, o.client_name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.date >= ? AND o.status='active'
        ORDER BY o.date, o.start_min
    ''', (today,))
    orders = []
    for row in cur.fetchall():
        orders.append((row[0], row[1], row[2], row[3], min_to_time_str(row[4]), row[5], row[6], row[7]))
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
        SELECT o.id, o.user_id, s.name, o.date, o.start_min, b.name, o.client_name, o.phone, o.status, s.id, s.duration_min
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.id=?
    ''', (order_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        return (row[0], row[1], row[2], row[3], min_to_time_str(row[4]), row[5], row[6], row[7], row[8], row[9], row[10])
    return None

# Остальные функции (is_user_banned, get_orders_for_today, ...) аналогично перерабатываются с учётом start_min.
# Приведу только изменившиеся.
def get_orders_for_today():
    today = now_moscow().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT o.id, o.client_name, s.name, o.start_min, b.name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.date=? AND o.status='active'
        ORDER BY o.start_min
    """, (today,))
    rows = cur.fetchall()
    result = [(r[0], r[1], r[2], min_to_time_str(r[3]), r[4], r[5]) for r in rows]
    conn.close()
    return result

def get_orders_for_tomorrow():
    tomorrow = (now_moscow() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT o.id, o.client_name, s.name, o.start_min, b.name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.date=? AND o.status='active'
        ORDER BY o.start_min
    """, (tomorrow,))
    rows = cur.fetchall()
    result = [(r[0], r[1], r[2], min_to_time_str(r[3]), r[4], r[5]) for r in rows]
    conn.close()
    return result

def get_orders_for_reminder_24h():
    tomorrow = (now_moscow() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, user_id, date, start_min, phone
        FROM orders
        WHERE date=? AND status='active' AND reminder_sent24=0 AND user_id!=0
    """, (tomorrow,))
    rows = cur.fetchall()
    result = [(r[0], r[1], r[2], min_to_time_str(r[3]), r[4]) for r in rows]
    conn.close()
    return result

def get_orders_for_reminder_2h():
    """Все активные записи на сегодня, до которых осталось 1-2 часа."""
    now = now_moscow()
    today = now.strftime("%Y-%m-%d")
    now_min = now.hour * 60 + now.minute
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    # Берём записи, где start_min между now_min+60 и now_min+120 (напоминаем за ~1-2 часа)
    cur.execute("""
        SELECT id, user_id, date, start_min, phone
        FROM orders
        WHERE date=? AND status='active' AND reminder_sent2=0 AND user_id!=0
        AND start_min > ? AND start_min <= ?
    """, (today, now_min + 60, now_min + 120))
    rows = cur.fetchall()
    result = [(r[0], r[1], r[2], min_to_time_str(r[3]), r[4]) for r in rows]
    conn.close()
    return result

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
    today = now_moscow().strftime("%Y-%m-%d")
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='active' AND date >= ?", (user_id, today))
    count = cur.fetchone()[0]
    conn.close()
    return count

def block_day_for_barber(date_str, barber_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    barber = get_barber(barber_id)
    if not barber:
        conn.close()
        return
    start_min = time_str_to_min(barber[2])
    end_min = time_str_to_min(barber[3])
    step = 30
    for m in range(start_min, end_min, step):
        cur.execute("INSERT OR IGNORE INTO blocked_slots (date, start_min, barber_id) VALUES (?, ?, ?)",
                    (date_str, m, barber_id))
    conn.commit()
    conn.close()

def unblock_day_for_barber(date_str, barber_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM blocked_slots WHERE date=? AND barber_id=?", (date_str, barber_id))
    conn.commit()
    conn.close()

def get_cancelled_orders():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT o.id, o.user_id, s.name, o.date, o.start_min, o.client_name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        WHERE o.status='cancelled'
        ORDER BY o.date DESC LIMIT 20
    """)
    rows = cur.fetchall()
    result = [(r[0], r[1], r[2], r[3], min_to_time_str(r[4]), r[5], r[6]) for r in rows]
    conn.close()
    return result

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