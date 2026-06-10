#!/usr/bin/env python3
"""
Configuration file for DUCO REST API
Change these settings before running
"""

# ==================== DATABASE PATHS ====================
DATABASE_PATH = "config/database.db"
TRANSACTIONS_PATH = "config/transactions.db"
MINERS_PATH = "config/miners.db"

# ==================== SERVER SETTINGS ====================
HOST = "0.0.0.0"
PORT = 8000
DEBUG = False
SECRET_KEY = "change_this_in_production"

# ==================== RATE LIMITING ====================
RATE_LIMIT_PER_MINUTE = 60
PAGE_LIMIT_DEFAULT = 50

# ==================== CACHING ====================
CACHE_TTL_SECONDS = 15

# ==================== DATABASE ====================
MAX_DB_CONNECTIONS = 10
DB_TIMEOUT = 10

# ==================== SECURITY ====================
# Rate limit for auth endpoints (stricter)
AUTH_RATE_LIMIT = "10 per minute"
# Rate limit for regular endpoints
DEFAULT_RATE_LIMIT = f"{RATE_LIMIT_PER_MINUTE} per minute"
