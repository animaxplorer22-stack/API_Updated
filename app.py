#!/usr/bin/env python3
"""
Duino-Coin REST API - Rewritten
Fixes: pagination, rate limits, no passwords in URLs, connection pooling

Run with: python app.py
"""

import sys
import time
import json
import sqlite3
import threading
from functools import wraps
from contextlib import contextmanager

try:
    from flask import Flask, request, jsonify, g
    from flask_limiter import Limiter
    from flask_limiter.util import get_remote_address
    from bcrypt import checkpw
except ImportError as e:
    print(f"Missing dependency: {e}")
    print("Run: pip install -r requirements.txt")
    sys.exit(1)

from config import *

# ==================== INIT APP ====================
app = Flask(__name__)
app.config['SECRET_KEY'] = SECRET_KEY

limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[DEFAULT_RATE_LIMIT],
    storage_uri="memory://"
)

# ==================== DATABASE CONNECTION POOL ====================
class ConnectionPool:
    def __init__(self, db_path, max_connections=MAX_DB_CONNECTIONS):
        self.db_path = db_path
        self.max_connections = max_connections
        self._connections = []
        self._lock = threading.Lock()
    
    @contextmanager
    def get(self):
        conn = None
        with self._lock:
            if self._connections:
                conn = self._connections.pop()
            else:
                conn = sqlite3.connect(self.db_path, timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
        try:
            yield conn
        finally:
            with self._lock:
                if len(self._connections) < self.max_connections:
                    self._connections.append(conn)
                else:
                    conn.close()

db_pool = ConnectionPool(DATABASE_PATH)
tx_pool = ConnectionPool(TRANSACTIONS_PATH)
miners_pool = ConnectionPool(MINERS_PATH)

# ==================== CACHE ====================
_cache = {}
_cache_times = {}

def cached(ttl=CACHE_TTL_SECONDS):
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            key = f"{func.__name__}:{str(args)}:{str(kwargs)}"
            now = time.time()
            if key in _cache and (now - _cache_times.get(key, 0)) < ttl:
                return _cache[key]
            result = func(*args, **kwargs)
            _cache[key] = result
            _cache_times[key] = now
            return result
        return wrapper
    return decorator

def clear_cache():
    global _cache, _cache_times
    _cache = {}
    _cache_times = {}

# ==================== RESPONSE HELPERS ====================
def _success(data, code=200):
    return jsonify({"success": True, "result": data}), code

def _error(msg, code=400):
    return jsonify({"success": False, "message": msg}), code

def paginate(items, page, limit, total):
    page = max(1, page)
    limit = min(100, max(1, limit))
    return {
        "data": items,
        "page": page,
        "limit": limit,
        "total": total,
        "pages": (total + limit - 1) // limit if total else 1
    }

# ==================== ROW TO DICT CONVERTERS ====================
def row_to_transaction(row):
    if not row:
        return None
    return {
        'datetime': str(row['timestamp']),
        'sender': str(row['username']),
        'recipient': str(row['recipient']),
        'amount': float(row['amount']),
        'hash': str(row['hash']),
        'memo': str(row['memo']) if row['memo'] else '',
        'id': int(row['id'])
    }

def row_to_miner(row):
    return {
        "threadid": str(row[0]),
        "username": str(row[1]),
        "hashrate": float(row[2]),
        "sharetime": float(row[3]),
        "accepted": int(row[4]),
        "rejected": int(row[5]),
        "diff": int(row[6]),
        "software": str(row[7]),
        "identifier": str(row[8]),
        "algorithm": str(row[9]),
        "pool": str(row[10])
    }

def row_to_user(row):
    if not row:
        return None
    return {
        "username": str(row['username']),
        "balance": float(row['balance']),
        "created": str(row['created']),
        "verified": row['rig_verified'].lower() == 'yes' if row['rig_verified'] else False
    }

# ==================== TRANSACTIONS ====================
def get_transactions_paginated(offset, limit):
    with tx_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM Transactions ORDER BY id DESC LIMIT ? OFFSET ?", (limit, offset))
        return [row_to_transaction(row) for row in cur.fetchall()]

def get_user_transactions_paginated(username, offset, limit):
    with tx_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("""
            SELECT * FROM Transactions 
            WHERE username = ? OR recipient = ? 
            ORDER BY id DESC LIMIT ? OFFSET ?
        """, (username, username, limit, offset))
        return [row_to_transaction(row) for row in cur.fetchall()]

def get_transaction_by_hash(tx_hash):
    with tx_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM Transactions WHERE hash = ?", (tx_hash,))
        return row_to_transaction(cur.fetchone())

def get_transaction_by_id(tx_id):
    with tx_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM Transactions WHERE id = ?", (tx_id,))
        return row_to_transaction(cur.fetchone())

def count_transactions(username=None):
    with tx_pool.get() as conn:
        cur = conn.cursor()
        if username:
            cur.execute("SELECT COUNT(*) FROM Transactions WHERE username = ? OR recipient = ?", (username, username))
        else:
            cur.execute("SELECT COUNT(*) FROM Transactions")
        return cur.fetchone()[0]

# ==================== MINERS ====================
def get_miners_paginated(offset, limit):
    with miners_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM Miners LIMIT ? OFFSET ?", (limit, offset))
        return [row_to_miner(row) for row in cur.fetchall()]

def get_user_miners(username):
    with miners_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT * FROM Miners WHERE username = ?", (username,))
        return [row_to_miner(row) for row in cur.fetchall()]

def count_miners():
    with miners_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM Miners")
        return cur.fetchone()[0]

# ==================== USERS ====================
def get_user_balance(username):
    with db_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username, balance, created, rig_verified FROM Users WHERE username = ?", (username,))
        return row_to_user(cur.fetchone())

def get_all_balances_paginated(offset, limit):
    with db_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT username, balance FROM Users ORDER BY balance DESC LIMIT ? OFFSET ?", (limit, offset))
        return [{"username": row['username'], "balance": float(row['balance'])} for row in cur.fetchall()]

def count_users():
    with db_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM Users")
        return cur.fetchone()[0]

def check_password(username, password):
    with db_pool.get() as conn:
        cur = conn.cursor()
        cur.execute("SELECT password FROM Users WHERE username = ?", (username,))
        row = cur.fetchone()
        if not row:
            return False
        try:
            return checkpw(password.encode('utf-8'), row['password'].encode('utf-8'))
        except:
            return row['password'] == password

# ==================== STATISTICS ====================
@cached(ttl=CACHE_TTL_SECONDS)
def get_stats():
    users = count_users()
    miners = count_miners()
    txs = count_transactions()
    return {
        "users": users,
        "active_miners": miners,
        "total_transactions": txs,
        "timestamp": int(time.time())
    }

# ==================== ENDPOINTS ====================

@app.route("/")
def home():
    return _success({
        "name": "DUCO REST API",
        "version": "2.0.0",
        "endpoints": [
            "GET /users/<username>",
            "GET /miners",
            "GET /miners/<username>",
            "GET /transactions",
            "GET /transactions/hash/<hash>",
            "GET /transactions/id/<id>",
            "GET /balances",
            "GET /balances/<username>",
            "GET /statistics",
            "POST /auth/<username>",
            "GET /ping"
        ]
    })

@app.route("/users/<username>")
@limiter.limit(DEFAULT_RATE_LIMIT)
@cached(ttl=CACHE_TTL_SECONDS)
def get_user(username):
    user = get_user_balance(username)
    if not user:
        return _error("User not found", 404)
    return _success(user)

@app.route("/miners")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_miners():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', PAGE_LIMIT_DEFAULT, type=int)
    offset = (page - 1) * limit
    total = count_miners()
    data = get_miners_paginated(offset, limit)
    return _success(paginate(data, page, limit, total))

@app.route("/miners/<username>")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_user_miners_endpoint(username):
    miners = get_user_miners(username)
    return _success({"username": username, "miners": miners})

@app.route("/transactions")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_transactions():
    username = request.args.get('username')
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', PAGE_LIMIT_DEFAULT, type=int)
    offset = (page - 1) * limit
    
    if username:
        total = count_transactions(username)
        data = get_user_transactions_paginated(username, offset, limit)
        return _success(paginate(data, page, limit, total))
    else:
        total = count_transactions()
        data = get_transactions_paginated(offset, limit)
        return _success(paginate(data, page, limit, total))

@app.route("/transactions/hash/<tx_hash>")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_tx_by_hash(tx_hash):
    tx = get_transaction_by_hash(tx_hash)
    if not tx:
        return _error("Transaction not found", 404)
    return _success(tx)

@app.route("/transactions/id/<int:tx_id>")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_tx_by_id(tx_id):
    tx = get_transaction_by_id(tx_id)
    if not tx:
        return _error("Transaction not found", 404)
    return _success(tx)

@app.route("/balances")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_balances():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', PAGE_LIMIT_DEFAULT, type=int)
    offset = (page - 1) * limit
    total = count_users()
    data = get_all_balances_paginated(offset, limit)
    return _success(paginate(data, page, limit, total))

@app.route("/balances/<username>")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_balance(username):
    user = get_user_balance(username)
    if not user:
        return _error("User not found", 404)
    return _success({"username": username, "balance": user["balance"]})

@app.route("/statistics")
@limiter.limit(DEFAULT_RATE_LIMIT)
def get_statistics():
    stats = get_stats()
    return _success(stats)

@app.route("/auth/<username>", methods=['POST'])
@limiter.limit(AUTH_RATE_LIMIT)
def authenticate(username):
    """
    Authentication with password in HEADERS, not URL
    Use: curl -X POST /auth/username -H "X-Password: yourpassword"
    """
    password = request.headers.get('X-Password')
    if not password:
        return _error("Missing X-Password header", 400)
    
    if check_password(username, password):
        return _success({"authenticated": True, "username": username})
    return _error("Invalid credentials", 401)

@app.route("/ping")
def ping():
    return _success("pong")

# ==================== ERROR HANDLERS ====================
@app.errorhandler(429)
def rate_limit_handler(e):
    return _error(f"Rate limit exceeded. Max {RATE_LIMIT_PER_MINUTE} requests per minute.", 429)

@app.errorhandler(404)
def not_found(e):
    return _error("Endpoint not found", 404)

@app.errorhandler(500)
def internal_error(e):
    return _error("Internal server error", 500)

# ==================== MAIN ====================
if __name__ == "__main__":
    print(f"Starting DUCO REST API on {HOST}:{PORT}")
    print(f"Rate limit: {RATE_LIMIT_PER_MINUTE} requests per minute")
    print(f"Docs: http://{HOST}:{PORT}/")
    app.run(host=HOST, port=PORT, debug=DEBUG, threaded=True)
