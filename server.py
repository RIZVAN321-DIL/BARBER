import os
import sqlite3
import logging
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory
from flask_cors import CORS
from config import TIMEZONE

logger = logging.getLogger(__name__)
app = Flask(__name__, static_folder='.', static_url_path='')
CORS(app)

# ---------- Статические страницы ----------
@app.route('/webapp')
def serve_webapp():
    return send_from_directory('.', 'webapp.html')

@app.route('/admin')
def serve_admin():
    return send_from_directory('.', 'admin.html')

# ---------- Вспомогательные функции для API ----------
def now_moscow():
    return datetime.now(TIMEZONE)

def get_all_future_orders():
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute('''
        SELECT o.id, o.user_id, s.name, o.date, o.time, b.name, o.client_name, o.phone
        FROM orders o
        JOIN services s ON o.service_id = s.id
        JOIN barbers b ON o.barber_id = b.id
        WHERE o.date >= date('now','localtime') AND o.status='active'
        ORDER BY o.date, o.time
    ''')
    rows = cur.fetchall()
    conn.close()
    return rows

def get_orders_count_for_date(date_str):
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM orders WHERE date=? AND status='active'", (date_str,))
    cnt = cur.fetchone()[0]
    conn.close()
    return cnt

# ---------- API ----------
@app.route('/api/orders')
def api_orders():
    orders = get_all_future_orders()
    result = [{"id": o[0], "user_id": o[1], "service": o[2], "date": o[3],
               "time": o[4], "barber": o[5], "client_name": o[6], "phone": o[7]} for o in orders]
    return jsonify({"orders": result})

@app.route('/api/cancel/<int:order_id>', methods=['POST'])
def api_cancel(order_id):
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status='cancelled' WHERE id=?", (order_id,))
    conn.commit()
    conn.close()
    logger.info(f"Запись #{order_id} отменена через API")
    return jsonify({"status": "ok", "message": f"Запись #{order_id} отменена"})

@app.route('/api/move/<int:order_id>', methods=['POST'])
def api_move(order_id):
    """Перенести запись на ближайший свободный слот у любого мастера"""
    start_date = now_moscow().date() + timedelta(days=1)
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    for i in range(30):
        check_date = start_date + timedelta(days=i)
        date_str = check_date.strftime("%Y-%m-%d")
        # Ищем любого мастера
        cur.execute("SELECT id, work_start, work_end FROM barbers")
        for barber_id, work_start, work_end in cur.fetchall():
            sh, sm = map(int, work_start.split(':'))
            eh, em = map(int, work_end.split(':'))
            mins = sh * 60 + sm
            end_mins = eh * 60 + em
            while mins < end_mins:
                time_str = f"{mins//60:02d}:{mins%60:02d}"
                cur.execute("SELECT 1 FROM orders WHERE date=? AND time=? AND barber_id=? AND status='active'",
                            (date_str, time_str, barber_id))
                if not cur.fetchone():
                    cur.execute("SELECT 1 FROM blocked_slots WHERE date=? AND time=? AND barber_id=?",
                                (date_str, time_str, barber_id))
                    if not cur.fetchone():
                        # Переносим
                        cur.execute("UPDATE orders SET date=?, time=?, barber_id=? WHERE id=?",
                                    (date_str, time_str, barber_id, order_id))
                        conn.commit()
                        conn.close()
                        return jsonify({"status": "ok", "message": f"Запись #{order_id} перенесена на {date_str} {time_str}"})
                mins += 60
    conn.close()
    return jsonify({"status": "error", "message": "Нет свободных слотов в ближайшие 30 дней"}), 404

@app.route('/api/stats')
def api_stats():
    today_str = now_moscow().strftime("%Y-%m-%d")
    tomorrow_str = (now_moscow() + timedelta(days=1)).strftime("%Y-%m-%d")
    today_cnt = get_orders_count_for_date(today_str)
    tomorrow_cnt = get_orders_count_for_date(tomorrow_str)
    future_cnt = len(get_all_future_orders())
    return jsonify({"today": today_cnt, "tomorrow": tomorrow_cnt, "future": future_cnt})

@app.route('/api/services')
def api_services():
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute("SELECT id, name, duration_min, price FROM services")
    rows = cur.fetchall()
    conn.close()
    return jsonify({"services": [{"id": r[0], "name": r[1], "duration": r[2], "price": r[3]} for r in rows]})

@app.route('/api/barbers')
def api_barbers():
    conn = sqlite3.connect("barber.db")
    cur = conn.cursor()
    cur.execute("SELECT id, name FROM barbers")
    rows = cur.fetchall()
    conn.close()
    return jsonify({"barbers": [{"id": r[0], "name": r[1]} for r in rows]})

def run_flask():
    logger.info("Запуск Flask-сервера на порту 5000")
    app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)