import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime

# Define the database file path. Use RENDER_DISK_PATH for Render deployment.
DB_FILE = os.path.join(os.environ.get('RENDER_DISK_PATH', '.'), 'shortlinks.db')

def adapt_datetime(dt_obj):
    """Adapt datetime.datetime to an ISO 8601 string."""
    return dt_obj.isoformat() if dt_obj else None

def convert_timestamp(ts_bytes):
    """Convert an ISO 8601 string from bytes to a datetime.datetime object."""
    return datetime.fromisoformat(ts_bytes.decode('utf-8')) if ts_bytes else None

sqlite3.register_adapter(datetime, adapt_datetime)
sqlite3.register_converter("timestamp", convert_timestamp)

@contextmanager
def get_db_connection():
    """Provides a transactional database connection."""
    conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES)
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    """Initializes the database and creates the 'links' table if it doesn't exist."""
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS links (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                long_url TEXT NOT NULL,
                expires_at TIMESTAMP
            )
        """)
        conn.commit()
    print("Database initialized successfully.")