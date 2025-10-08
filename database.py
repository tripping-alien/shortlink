import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone

# --- SQLite Type Adapters for Timezone-Aware Datetimes ---

def adapt_datetime_to_timestamp(dt_obj):
    """Converts a timezone-aware datetime object to a UTC timestamp (float)."""
    return dt_obj.astimezone(timezone.utc).timestamp()

def convert_timestamp_to_datetime(ts_bytes: bytes) -> datetime:
    """
    Converts a UTC timestamp stored as bytes in the DB back to a timezone-aware datetime object.
    The converter receives a byte string from sqlite3.
    """
    return datetime.fromtimestamp(float(ts_bytes), tz=timezone.utc)

sqlite3.register_adapter(datetime, adapt_datetime_to_timestamp)
sqlite3.register_converter("timestamp", convert_timestamp_to_datetime)

# Define the database file path. Use RENDER_DISK_PATH for Render deployment.
DB_FILE = os.path.join(os.environ.get('RENDER_DISK_PATH', '.'), 'shortlinks.db')

@contextmanager
def get_db_connection():
    """Provides a transactional database connection."""
    # Using detect_types to automatically handle timestamp conversion
    conn = sqlite3.connect(DB_FILE, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
    conn.row_factory = sqlite3.Row  # Allows accessing columns by name
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
                expires_at "timestamp",
                deletion_token TEXT NOT NULL UNIQUE
            )
        """)
        conn.commit()
    print("Database initialized successfully.")

def delete_link_by_id_and_token(link_id: int, token: str) -> int:
    """Deletes a link from the database only if the ID and deletion_token match."""
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM links WHERE id = ? AND deletion_token = ?", (link_id, token))
        conn.commit()
        return cursor.rowcount