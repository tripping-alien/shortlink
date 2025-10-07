import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone

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
                expires_at "timestamp"
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