import os
import logging
import random
import string
import asyncio
import json 
import tempfile 
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone, timedelta 

from firebase_admin import credentials, initialize_app, firestore, get_app
from firebase_admin import exceptions 
# 🟢 FIX: Corrected import path for FieldFilter
from google.cloud.firestore_v1 import FieldFilter 
from firebase_admin.firestore import AsyncClient, Transaction 

# Import passlib for secure token hashing
from passlib.context import CryptContext

# Import the necessary constants from the user's config file
from config import SHORT_CODE_LENGTH, MAX_ID_RETRIES, TTL_MAP 

# --- Environment Setup and Security ---

logger = logging.getLogger(__name__)

# 1. Setup Security Context for Hashing Deletion Tokens
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Constants & Globals ---

CLIENT_APP_ID_FALLBACK = 'shortlink-app-default'
# A far-future date for "never expires" links to allow efficient querying
FAR_FUTURE_EXPIRY = datetime(3000, 1, 1, tzinfo=timezone.utc) 

# The 'db' client is now the synchronous client (Type Hint remains for context)
db: firestore.client = None 
APP_ID: str = ""
APP_INSTANCE = None # Global to hold the initialized App instance

# --- Custom Exception (Required for delete_link_with_token_check) ---
class ResourceNotFoundException(Exception):
    """Custom exception for resource not found errors."""
    pass 

# --- Hashing Helper Functions ---

def _verify_token(plain_token: str, hashed_token: str) -> bool:
    """Verifies a plain token against a hashed one."""
    try:
        # pwd_context.verify is synchronous, but fast enough to not wrap in to_thread
        return pwd_context.verify(plain_token, hashed_token)
    except Exception as e:
        logger.warning(f"Token verification failed: {e}")
        return False

def _hash_token(plain_token: str) -> str:
    """Hashes a plain token using bcrypt."""
    # pwd_context.hash is synchronous, but fast enough to not wrap in to_thread
    return pwd_context.hash(plain_token)

# --- Database Connection (Async) ---

def get_db_connection():
    """Initializes and returns the Firestore client (runs once)."""
    global db, APP_ID, APP_INSTANCE

    if db is None:
        # 1. Get configuration safely
        app_id_env = os.environ.get('APP_ID')
        APP_ID = app_id_env if app_id_env else CLIENT_APP_ID_FALLBACK
        
        firebase_config_str = os.environ.get('FIREBASE_CONFIG')

        temp_file_path = None
        try:
            cred = None
            
            # 2. Determine Credential Source (ONLY checking FIREBASE_CONFIG, as requested)
            if firebase_config_str:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
                    tmp_file.write(firebase_config_str)
                    temp_file_path = tmp_file.name 
                cred = credentials.Certificate(temp_file_path)
                logger.info("Using FIREBASE_CONFIG JSON string via temporary file.")
            
            # 3. Handle missing configuration
            if cred is None:
                logger.error("FIREBASE_CONFIG is not set or is empty. Cannot connect to Firebase.")
                raise ValueError("Firebase configuration is missing. Please set the FIREBASE_CONFIG environment variable.")

            # 4. Initialize Firebase App
            try:
                APP_INSTANCE = get_app(APP_ID)
                logger.info(f"Reusing existing Firebase App instance: {APP_ID}")
            except ValueError:
                APP_INSTANCE = initialize_app(cred, name=APP_ID)
                logger.info(f"Initialized new Firebase App instance: {APP_ID}")
            
            # 5. Get Firestore Client (SYNCHRONOUS)
            db = firestore.client(app=APP_INSTANCE) 
            logger.info("Firebase Firestore client initialized successfully.")
            
        except Exception as e:
            if isinstance(e, json.JSONDecodeError):
                logger.error(f"Error initializing Firebase or Firestore: The content of FIREBASE_CONFIG is not valid JSON. Detail: {e}")
            else:
                logger.error(f"Error initializing Firebase or Firestore: {e}")
            raise RuntimeError("Database connection failure.") from e
        finally:
            # 6. Clean up the temp file
            if temp_file_path and os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                    logger.debug(f"Cleaned up temporary credential file at {temp_file_path}")
                except Exception as cleanup_e:
                    logger.warning(f"Failed to clean up temporary credential file: {cleanup_e}")

    return db


def init_db():
    """
    Explicitly initializes the database connection.
    Called by the application's lifespan event.
    """
    get_db_connection()


def get_collection_ref(collection_name: str) -> firestore.CollectionReference:
    """Returns the CollectionReference for a public collection."""
    if not APP_ID:
        raise ValueError("APP_ID is not set. Cannot construct collection path.")
    
    path = f"artifacts/{APP_ID}/public/data/{collection_name}"
    # NOTE: The client is synchronous, so the return type is synchronous.
    return get_db_connection().collection(path)


# --- Internal Short Code Generation Logic (Async) ---

def _generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    """Generates a random short code using only lowercase letters and digits."""
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

async def _is_short_code_unique(short_code: str) -> bool:
    """Checks the database asynchronously to see if a short code already exists."""
    get_db_connection()
    doc_ref = get_collection_ref("links").document(short_code)
    
    doc = await asyncio.to_thread(doc_ref.get)
    return not doc.exists

async def generate_unique_short_code() -> str:
    """
    Generates a unique short code by checking the database and retrying on collision.
    """
    for attempt in range(MAX_ID_RETRIES):
        new_id = _generate_short_code()
        
        if await _is_short_code_unique(new_id):
            return new_id
        
        logger.debug(f"Collision detected for ID: {new_id}. Retrying... (Attempt {attempt + 1})")

    raise RuntimeError(
        f"Failed to generate a unique short ID after {MAX_ID_RETRIES} attempts."
    )

# --- Public Database Operations (Async, Secure) ---

async def create_link(
    long_url: str, 
    ttl_key: str, 
    deletion_token: str, 
    custom_code: Optional[str] = None,
    owner_id: Optional[str] = None,
    utm_tags: Optional[str] = None
) -> str:
    """
    Creates a new link document in Firestore. Returns the unique/chosen short code.
    """
    db_client = get_db_connection()
    
    # 1. Prepare Data
    hashed_token = _hash_token(deletion_token)
    
    # Calculate expiration using TTL_MAP from config
    delta: Optional[timedelta] = TTL_MAP.get(ttl_key)
    expires_at = datetime.now(timezone.utc) + delta if delta else FAR_FUTURE_EXPIRY
    
    data = {
        "long_url": long_url,
        "deletion_token": hashed_token, 
        "created_at": datetime.now(tz=timezone.utc),
        "clicks": 0,
        "owner_id": owner_id,
        "utm_tags": utm_tags,
        "expires_at": expires_at
    }
    
    if custom_code:
        # 2a. Custom Code Path (Atomic Check-and-Set)
        if not custom_code.isalnum(): 
            raise ValueError("Invalid short code format: custom code must be alphanumeric.")
            
        final_code = custom_code
        doc_ref = get_collection_ref("links").document(final_code)
        
        @firestore.transactional
        async def _create_in_transaction(transaction: Transaction, ref, data_to_set):
            # FIX: Synchronous .get() must be wrapped in asyncio.to_thread
            doc_snapshot = await asyncio.to_thread(ref.get, transaction=transaction)
            if doc_snapshot.exists:
                raise ValueError(f"Custom short code '{ref.id}' is already in use.")
            # FIX: Synchronous .set() must be wrapped in asyncio.to_thread
            await asyncio.to_thread(transaction.set, ref, data_to_set)
        
        try:
            # FIX: Synchronous db_client.transaction().run must be wrapped in asyncio.to_thread
            await asyncio.to_thread(db_client.transaction().run, _create_in_transaction, doc_ref, data)
        except ValueError as e:
            raise ValueError(f"Custom code already exists")
    
    else:
        # 2b. Random Generation Path (Atomic Create)
        final_code = await generate_unique_short_code()
        doc_ref = get_collection_ref("links").document(final_code)
        
        try:
            # FIX: Synchronous .create() must be wrapped in asyncio.to_thread
            await asyncio.to_thread(doc_ref.create, data)
        except exceptions.AlreadyExists as e:
            logger.error(f"Critical collision on 'create' for {final_code}: {e}")
            raise RuntimeError(f"Failed to create link due to a rare collision.")
    
    return final_code


async def get_link_by_id(short_code: str) -> Optional[Dict[str, Any]]:
    """Retrieves a link record by its short code (Document ID) asynchronously."""
    doc_ref = get_collection_ref("links").document(short_code)
    # FIX: Synchronous .get() must be wrapped in asyncio.to_thread
    doc = await asyncio.to_thread(doc_ref.get)
    
    if doc.exists:
        data = doc.to_dict()
        data['id'] = doc.id 
        return data
    return None

async def delete_link_by_id_and_token(
    short_code: str, 
    token: str
) -> bool:
    """
    Public function to delete a link, wrapping the transactional logic.

    Returns: True on successful deletion.
    Raises: ValueError for invalid token, ResourceNotFoundException if link is not found.
    """
    db_client = get_db_connection()
    
    # FIX: Synchronous db_client.transaction().run must be wrapped in asyncio.to_thread
    await asyncio.to_thread(
        db_client.transaction().run, 
        delete_link_with_token_check, 
        short_code, 
        token
    )
    return True

@firestore.transactional
async def delete_link_with_token_check(
    transaction: Transaction, 
    short_code: str, 
    token: str
) -> bool:
    """
    Atomically retrieves a doc, checks the deletion token, and deletes it.
    """
    doc_ref = get_collection_ref("links").document(short_code)
    
    # FIX: Synchronous .get() must be wrapped in asyncio.to_thread
    doc_snapshot = await asyncio.to_thread(doc_ref.get, transaction=transaction)

    if not doc_snapshot.exists:
        logger.warning(f"Deletion attempt failed: Link '{short_code}' not found.")
        raise ResourceNotFoundException(f"Link '{short_code}' not found.")

    data = doc_snapshot.to_dict()
    hashed_token = data.get("deletion_token")

    if not hashed_token or not _verify_token(token, hashed_token):
        logger.warning(f"Deletion attempt failed: Invalid token for '{short_code}'.")
        raise ValueError("Invalid deletion token.")
        
    # FIX: Synchronous transaction.delete() must be wrapped in asyncio.to_thread
    await asyncio.to_thread(transaction.delete, doc_ref)
    logger.info(f"Successfully deleted link '{short_code}'.")
    return True

async def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    """Retrieves all non-expired links for sitemap generation (Async)."""
    try:
        links_ref = get_collection_ref("links")
        
        # 🟢 FIX: Use FieldFilter and the 'filter' keyword argument
        expired_query = links_ref.where(filter=FieldFilter('expires_at', '>', now)).stream() 
        
        # FIX: Run synchronous iteration (list comprehension) in a thread
        docs = await asyncio.to_thread(list, expired_query)
        
        links = []
        for doc in docs:
            data = doc.to_dict()
            links.append({'id': doc.id, **data})
        return links
    except Exception as e:
        logger.error(f"Failed to fetch active links for sitemap: {e}")
        return []

async def cleanup_expired_links(now: datetime):
    """
    Deletes all short link documents that have passed their expiration time
    using efficient Batched Writes (Async).
    """
    logger.info("Starting cleanup of expired links...")
    links_ref = get_collection_ref("links")
    db_client = get_db_connection()
    
    # 🟢 FIX: Use FieldFilter and the 'filter' keyword argument
    expired_query = links_ref.where(filter=FieldFilter('expires_at', '<=', now)).stream()
    
    deleted_count = 0
    batch = db_client.batch()
    batch_count = 0
    
    # FIX: Run synchronous iteration in a thread and collect results
    docs_to_delete = await asyncio.to_thread(list, expired_query)
    
    for doc in docs_to_delete:
        batch.delete(doc.reference)
        batch_count += 1
        deleted_count += 1
        
        # Firestore batches are limited to 500 operations
        if batch_count >= 499:
            # FIX: Synchronous .commit() must be wrapped in asyncio.to_thread
            await asyncio.to_thread(batch.commit)
            logger.info(f"Committed batch of {batch_count} deletions.")
            # Start a new batch
            batch = db_client.batch()
            batch_count = 0

    # Commit any remaining docs in the last batch
    if batch_count > 0:
        # FIX: Synchronous .commit() must be wrapped in asyncio.to_thread
        await asyncio.to_thread(batch.commit)
        logger.info(f"Committed final batch of {batch_count} deletions.")

    logger.info(f"Cleanup finished. Deleted {deleted_count} total expired links.")
    return deleted_count
