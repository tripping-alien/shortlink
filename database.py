import os
import logging
import random
import string
import asyncio
import json 
import tempfile 
from typing import Optional, Dict, Any, List, Union
from datetime import datetime, timezone, timedelta 

# Import passlib for secure token hashing
from passlib.context import CryptContext

# Import the necessary constants from the user's config file
from config import SHORT_CODE_LENGTH, MAX_ID_RETRIES, TTL_MAP 

# --- Environment Setup and Security ---

logger = logging.getLogger(__name__)

# 1. Setup Security Context for Hashing Deletion Tokens
# We use bcrypt, a strong, one-way hashing algorithm.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Constants & Globals ---

CLIENT_APP_ID_FALLBACK = 'shortlink-app-default'
LOCAL_DB_FILE = "shortlinks.json" # Path to your local JSON database file
# A far-future date for "never expires" links to allow efficient querying
FAR_FUTURE_EXPIRY = datetime(3000, 1, 1, tzinfo=timezone.utc) 

# --- Custom Exception (Required for delete_link_with_token_check) ---
class ResourceNotFoundException(Exception):
    """Custom exception for resource not found errors."""
    pass 

# --- Hashing Helper Functions ---

def _verify_token(plain_token: str, hashed_token: str) -> bool:
    """Verifies a plain token against a hashed one."""
    try:
        return pwd_context.verify(plain_token, hashed_token)
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return False

def _hash_token(plain_token: str) -> str:
    """Hashes a plain token using bcrypt."""
    return pwd_context.hash(plain_token)

# --- Local File Database Helpers (Synchronous) ---

def _read_db_file() -> Dict[str, Any]:
    """Reads the entire local database file and returns its content."""
    if not os.path.exists(LOCAL_DB_FILE):
        return {}
    try:
        with open(LOCAL_DB_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        logger.error(f"Error decoding JSON from {LOCAL_DB_FILE}. File might be corrupt. Returning empty database.")
        return {}
    except Exception as e:
        logger.error(f"Error reading database file {LOCAL_DB_FILE}: {e}")
        return {}

def _write_db_file(data: Dict[str, Any]):
    """Writes the given data dictionary to the local database file."""
    try:
        with open(LOCAL_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=4)
    except Exception as e:
        logger.error(f"Error writing to database file {LOCAL_DB_FILE}: {e}")
        raise RuntimeError("Failed to write to local database file.") from e

# --- Database Initialization ---

def init_db():
    """
    Explicitly initializes the local database file.
    Ensures the shortlinks.json file exists.
    """
    if not os.path.exists(LOCAL_DB_FILE):
        _write_db_file({}) # Create an empty JSON file
        logger.info(f"Initialized new local database file: {LOCAL_DB_FILE}")
    else:
        logger.info(f"Local database file already exists: {LOCAL_DB_FILE}")

# No longer needed for local file system
# def get_db_connection():
#     """This function is no longer relevant for a local JSON file."""
#     pass

# No longer needed for local file system
# def get_collection_ref(collection_name: str):
#     """This function is no longer relevant for a local JSON file."""
#     raise NotImplementedError("get_collection_ref is not implemented for local file database.")


# --- Internal Short Code Generation Logic (Async) ---

def _generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    """Generates a random short code using only lowercase letters and digits."""
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

async def _is_short_code_unique(short_code: str) -> bool:
    """Checks the local database asynchronously to see if a short code already exists."""
    db_data = await asyncio.to_thread(_read_db_file)
    return short_code not in db_data

async def generate_unique_short_code() -> str:
    """
    Generates a unique short code by checking the database and retrying on collision.
    """
    # NOTE: MAX_ID_GENERATION_RETRIES must be MAX_ID_RETRIES from config
    for attempt in range(MAX_ID_RETRIES):
        new_id = _generate_short_code()
        
        if await _is_short_code_unique(new_id): # <-- Await
            return new_id
        
        logger.debug(f"Collision detected for ID: {new_id}. Retrying... (Attempt {attempt + 1})")

    raise RuntimeError(
        f"Failed to generate a unique short ID after {MAX_ID_RETRIES} attempts."
    )

# --- Public Database Operations (Async, Secure) ---

async def create_link(
    long_url: str, 
    expires_at: Optional[datetime], 
    deletion_token: str, 
    short_code: Optional[str] = None
) -> str:
    """
    Creates a new link document in Firestore. Uses transactions/atomic
    operations to prevent race conditions and hashes the deletion token.
    
    Returns: The unique/chosen short code.
    Raises: ValueError if the provided short_code is already in use.
    """
    # --- 1. Prepare Data ---
    hashed_token = _hash_token(deletion_token)
    
    data = {
        "long_url": long_url,
        "deletion_token": hashed_token, # <-- Store the HASH, not the token
        "created_at": datetime.now(tz=timezone.utc).isoformat(), # Store as ISO string
        # Use a far-future date for "never expires" to simplify queries
        "expires_at": (expires_at if expires_at else FAR_FUTURE_EXPIRY).isoformat() # Store as ISO string
    }
    
    db_data = await asyncio.to_thread(_read_db_file)

    if short_code:
        # --- 2a. Custom Code Path ---
        if not short_code.isalnum(): 
            raise ValueError("Invalid short code format: custom code must be alphanumeric.")
        
        final_code = short_code
        if final_code in db_data:
            raise ValueError(f"Custom short code '{final_code}' is already in use.")
    
    else:
        # --- 2b. Random Generation Path ---
        final_code = await generate_unique_short_code()
        # Double-check in case generate_unique_short_code had a very rare race condition
        if final_code in db_data:
            logger.error(f"Critical collision on 'create' for {final_code}. This should not happen with generate_unique_short_code.")
            raise RuntimeError(f"Failed to create link for {final_code} due to a rare collision.")
    
    db_data[final_code] = data
    await asyncio.to_thread(_write_db_file, db_data)
    return final_code


async def get_link_by_id(short_code: str) -> Optional[Dict[str, Any]]:
    """Retrieves a link record by its short code (Document ID) asynchronously."""
    db_data = await asyncio.to_thread(_read_db_file)
    link_data = db_data.get(short_code)
    
    if link_data:
        data = link_data
        data['id'] = short_code # Add ID for consistency with Firestore doc.id
        return data
    return None

async def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    """Retrieves all non-expired links for sitemap generation (Async)."""
    try:
        # This efficient query relies on "never expires" links
        # having a far-future 'expires_at' date.
        db_data = await asyncio.to_thread(_read_db_file)
        
        links = []
        for doc_id, data in db_data.items():
            expires_at_str = data.get('expires_at')
            if expires_at_str:
                expires_at = datetime.fromisoformat(expires_at_str)
                if expires_at > now:
                    links.append({'id': doc_id, **data})
        return links
    except Exception as e:
        logger.error(f"Failed to fetch active links for sitemap: {e}")
        return []

@firestore.transactional
async def delete_link_with_token_check(
    # Removed transaction argument as it's not applicable to local files
    short_code: str, 
    token: str
) -> bool:
    """
    Retrieves a link, checks the deletion token, and deletes it from the local file.
    
    Returns: True on success, False on failure (bad token/not found).
    """
    db_data = await asyncio.to_thread(_read_db_file)

    if not doc_snapshot.exists:
        logger.warning(f"Deletion attempt failed: Link '{short_code}' not found.")
        # Raise ResourceNotFoundException instead of returning False for clear API error handling
        raise ResourceNotFoundException(f"Link '{short_code}' not found.")

    data = doc_snapshot.to_dict()
    hashed_token = data.get("deletion_token")

    # Securely verify the provided token against the stored hash
    if not hashed_token or not _verify_token(token, hashed_token):
        logger.warning(f"Deletion attempt failed: Invalid token for '{short_code}'.")
        # Raise ValueError for clear API error handling
        raise ValueError("Invalid deletion token.")
        
    del db_data[short_code]
    await asyncio.to_thread(_write_db_file, db_data)
    logger.info(f"Successfully deleted link '{short_code}'.")
    return True

async def cleanup_expired_links(now: datetime):
    """
    Deletes all short link entries from the local file that have passed their expiration time.
    """
    logger.info("Starting cleanup of expired links...")
    db_data = await asyncio.to_thread(_read_db_file)
    
    updated_db_data = {}
    deleted_count = 0

    for short_code, data in db_data.items():
        expires_at_str = data.get('expires_at')
        if expires_at_str:
            expires_at = datetime.fromisoformat(expires_at_str)
            if expires_at <= now:
                deleted_count += 1
            else:
                updated_db_data[short_code] = data
        else: # Should not happen if create_link always sets expires_at
            updated_db_data[short_code] = data

    if deleted_count > 0:
        await asyncio.to_thread(_write_db_file, updated_db_data)
        logger.info(f"Cleanup finished. Deleted {deleted_count} total expired links.")
    else:
        logger.info("Cleanup finished. No expired links found.")
    return deleted_count
