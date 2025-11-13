import sqlite3
import logging
import random
import string
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta

from passlib.context import CryptContext

from config import SHORT_CODE_LENGTH, MAX_ID_RETRIES, TTL_MAP

# --- Environment Setup and Security ---

logger = logging.getLogger(__name__)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Constants & Globals ---

DB_FILE = "shortlinks.db"
FAR_FUTURE_EXPIRY = datetime(3000, 1, 1, tzinfo=timezone.utc)

class ResourceNotFoundException(Exception):
    """Custom exception for resource not found errors."""
    pass

# --- Hashing Helper Functions ---

def _verify_token(plain_token: str, hashed_token: str) -> bool:
    try:
        return pwd_context.verify(plain_token, hashed_token)
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return False

def _hash_token(plain_token: str) -> str:
    return pwd_context.hash(plain_token)

# --- Database Connection ---

def get_db_connection():
    """Returns a connection to the SQLite database."""
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    """Initializes the database and creates the 'links' table if it doesn't exist."""
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS links (
                id TEXT PRIMARY KEY,
                long_url TEXT NOT NULL,
                deletion_token TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL,
                expires_at TIMESTAMP NOT NULL,
                clicks INTEGER DEFAULT 0,
                owner_id TEXT,
                utm_tags TEXT,
                summary_status TEXT DEFAULT 'pending',
                summary_text TEXT,
                meta_title TEXT,
                meta_description TEXT,
                meta_image TEXT
            )
        """)
        conn.commit()
    logger.info("Database initialized successfully.")

def get_collection_ref(collection_name: str):
    # This function is a placeholder to maintain compatibility with the old structure.
    # In SQLite, we interact with tables directly.
    if collection_name == "links":
        return "links"
    raise ValueError(f"Unknown collection: {collection_name}")


# --- Internal Short Code Generation Logic ---

def _generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

async def _is_short_code_unique(short_code: str) -> bool:
    """Checks the database to see if a short code already exists."""
    loop = asyncio.get_running_loop()
    def db_check():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1 FROM links WHERE id = ?", (short_code,))
            return cursor.fetchone() is None
    return await loop.run_in_executor(None, db_check)

async def generate_unique_short_code() -> str:
    for _ in range(MAX_ID_RETRIES):
        new_id = _generate_short_code()
        if await _is_short_code_unique(new_id):
            return new_id
    raise RuntimeError(f"Failed to generate a unique short ID after {MAX_ID_RETRIES} attempts.")

# --- Public Database Operations ---

async def create_link(
    long_url: str,
    ttl: str,
    deletion_token: str,
    custom_code: Optional[str] = None,
    owner_id: Optional[str] = None,
    utm_tags: Optional[str] = None
) -> str:
    hashed_token = _hash_token(deletion_token)
    delta = TTL_MAP.get(ttl)
    expires_at = (datetime.now(timezone.utc) + delta) if delta else FAR_FUTURE_EXPIRY

    final_code = custom_code or await generate_unique_short_code()

    if custom_code and not await _is_short_code_unique(custom_code):
        raise ValueError(f"Custom short code '{custom_code}' is already in use.")

    loop = asyncio.get_running_loop()
    def db_insert():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO links (id, long_url, deletion_token, created_at, expires_at, owner_id, utm_tags)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (final_code, long_url, hashed_token, datetime.now(timezone.utc), expires_at, owner_id, utm_tags)
            )
            conn.commit()
    await loop.run_in_executor(None, db_insert)
    return final_code

async def get_link_by_id(short_code: str) -> Optional[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    def db_fetch():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM links WHERE id = ?", (short_code,))
            row = cursor.fetchone()
            if row:
                # Check for expiration
                expires_at = row['expires_at']
                if isinstance(expires_at, str):
                    expires_at = datetime.fromisoformat(expires_at)
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=timezone.utc)

                if expires_at > datetime.now(timezone.utc):
                    return dict(row)
            return None
    return await loop.run_in_executor(None, db_fetch)

async def delete_link_by_id_and_token(short_code: str, token: str):
    loop = asyncio.get_running_loop()
    def db_delete():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT deletion_token FROM links WHERE id = ?", (short_code,))
            row = cursor.fetchone()
            if not row:
                raise ResourceNotFoundException(f"Link '{short_code}' not found.")

            hashed_token = row['deletion_token']
            if not _verify_token(token, hashed_token):
                raise ValueError("Invalid deletion token.")

            cursor.execute("DELETE FROM links WHERE id = ?", (short_code,))
            conn.commit()
    await loop.run_in_executor(None, db_delete)
    return True

async def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    loop = asyncio.get_running_loop()
    def db_fetch_all():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM links WHERE expires_at > ?", (now,))
            return [dict(row) for row in cursor.fetchall()]
    return await loop.run_in_executor(None, db_fetch_all)

async def cleanup_expired_links(now: datetime):
    loop = asyncio.get_running_loop()
    def db_cleanup():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM links WHERE expires_at <= ?", (now,))
            conn.commit()
            return cursor.rowcount
    deleted_count = await loop.run_in_executor(None, db_cleanup)
    logger.info(f"Cleanup finished. Deleted {deleted_count} total expired links.")
    return deleted_count

async def update_link_metadata(
    short_code: str,
    meta_title: Optional[str] = None,
    meta_description: Optional[str] = None,
    meta_image: Optional[str] = None
):
    """Updates the metadata fields for a given short code."""
    loop = asyncio.get_running_loop()
    def db_update():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE links
                SET meta_title = ?, meta_description = ?, meta_image = ?
                WHERE id = ?
                """,
                (meta_title, meta_description, meta_image, short_code)
            )
            conn.commit()
    await loop.run_in_executor(None, db_update)

async def update_link_summary(
    short_code: str,
    status: str,
    summary_text: Optional[str] = None,
    meta_title: Optional[str] = None,
    meta_description: Optional[str] = None,
    meta_image: Optional[str] = None
):
    """Updates the summary and metadata fields for a given short code."""
    loop = asyncio.get_running_loop()
    def db_update():
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE links
                SET summary_status = ?, summary_text = ?, meta_title = ?, meta_description = ?, meta_image = ?
                WHERE id = ?
                """,
                (status, summary_text, meta_title, meta_description, meta_image, short_code)
            )
            conn.commit()
    await loop.run_in_executor(None, db_update)
    logger.info(f"Updated summary/metadata for {short_code} with status '{status}'")
