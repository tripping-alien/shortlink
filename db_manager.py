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
# Import AsyncClient and Transaction for async operations
from firebase_admin.firestore import AsyncClient, Transaction 

# Import passlib for secure token hashing
from passlib.context import CryptContext

# --- FIX: Import globally exposed constants directly ---
from config import SHORT_CODE_LENGTH, MAX_ID_RETRIES, TTL_MAP 

# --- Environment Setup and Security ---

logger = logging.getLogger(__name__)

# 1. Setup Security Context for Hashing Deletion Tokens
# We use bcrypt, a strong, one-way hashing algorithm.
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- Constants & Globals ---

CLIENT_APP_ID_FALLBACK = 'shortlink-app-default'
# A far-future date for "never expires" links to allow efficient querying
FAR_FUTURE_EXPIRY = datetime(3000, 1, 1, tzinfo=timezone.utc) 

# Set the alias locally here:
MAX_ID_GENERATION_RETRIES = MAX_ID_RETRIES

# The 'db' client is now an AsyncClient
db: AsyncClient = None
APP_ID: str = ""
APP_INSTANCE = None # Global to hold the initialized App instance

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

# --- Database Connection (Async) ---

# --- In db_manager.py (The corrected function) ---

def get_db_connection():
    """Initializes and returns the Firestore ASYNC client (runs once)."""
    global db, APP_ID, APP_INSTANCE

    if db is None:
        # 1. Get configuration safely
        app_id_env = os.environ.get('APP_ID')
        APP_ID = app_id_env if app_id_env else CLIENT_APP_ID_FALLBACK
        
        firebase_config_str = os.environ.get('FIREBASE_CONFIG')

        temp_file_path = None
        try:
            cred = None
            
            # 2. Determine Credential Source
            if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                cred = credentials.ApplicationDefault()
                logger.info("Using GOOGLE_APPLICATION_CREDENTIALS path.")
            elif firebase_config_str:
                with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
                    tmp_file.write(firebase_config_str)
                    temp_file_path = tmp_file.name 
                cred = credentials.Certificate(temp_file_path)
                logger.info(f"Using FIREBASE_CONFIG JSON string via temporary file: {temp_file_path}")
            
            # 3. Handle missing configuration
            if cred is None:
                logger.error("FIREBASE_CONFIG or GOOGLE_APPLICATION_CREDENTIALS is not set. Cannot connect to Firebase.")
                raise ValueError("Firebase configuration is missing.")

            # 4. Initialize Firebase App
            try:
                APP_INSTANCE = get_app(APP_ID)
                logger.info(f"Reusing existing Firebase App instance: {APP_ID}")
            except ValueError:
                APP_INSTANCE = initialize_app(cred, name=APP_ID)
                logger.info(f"Initialized new Firebase App instance: {APP_ID}")
            
            # 5. Get Firestore Client (ASYNCHRONOUS)
            db = firestore.async_client(app=APP_INSTANCE)
            logger.info("Firebase Firestore ASYNC client initialized successfully.")
            
        except Exception as e:
            logger.error(f"Error initializing Firebase or Firestore: {e}")
            raise RuntimeError("Database connection failure.") from e
        finally: # <--- This block MUST be aligned with the 'try' and 'except' blocks
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


def get_collection_ref(collection_name: str) -> firestore.AsyncCollectionReference:
    """Returns the AsyncCollectionReference for a public collection."""
    if not APP_ID:
        raise ValueError("APP_ID is not set. Cannot construct collection path.")
    
    path = f"artifacts/{APP_ID}/public/data/{collection_name}" 
    return get_db_connection().collection(path)


# --- Utility Functions ---

def _calculate_expiration(ttl_key: str) -> Optional[datetime]:
    """Calculate expiration datetime from TTL key."""
    delta: Optional[timedelta] = TTL_MAP.get(ttl_key)
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta

def _generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    """Generates a random short code using only lowercase letters and digits."""
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

async def _is_short_code_unique(short_code: str) -> bool:
    """Checks the database asynchronously to see if a short code already exists."""
    get_db_connection()
    doc_ref = get_collection_ref("links").document(short_code)
    doc = await doc_ref.get() 
    return not doc.exists

async def generate_unique_short_code() -> str:
    """
    Generates a unique short code by checking the database and retrying on collision.
    """
    for attempt in range(MAX_ID_GENERATION_RETRIES):
        new_id = _generate_short_code()
        
        if await _is_short_code_unique(new_id): 
            return new_id
        
        logger.debug(f"Collision detected for ID: {new_id}. Retrying... (Attempt {attempt + 1})")

    raise RuntimeError(
        f"Failed to generate a unique short ID after {MAX_ID_GENERATION_RETRIES} attempts."
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
    
    # --- 1. Prepare Data ---
    hashed_token = _hash_token(deletion_token)
    expires_at = _calculate_expiration(ttl_key)
    
    data = {
        "long_url": long_url,
        "deletion_token": hashed_token, 
        "created_at": datetime.now(tz=timezone.utc),
        "clicks": 0,
        "owner_id": owner_id,
        "utm_tags": utm_tags,
        # Use a far-future date for "never expires" to simplify queries
        "expires_at": expires_at if expires_at else FAR_FUTURE_EXPIRY
    }
    
    if custom_code:
        # --- 2a. Custom Code Path (Atomic Check-and-Set) ---
        final_code = custom_code
        doc_ref = get_collection_ref("links").document(final_code)
        
        # Use a transaction to check-and-set atomically
        @firestore.transactional
        async def _create_in_transaction(transaction: Transaction, ref, data_to_set):
            doc_snapshot = await ref.get(transaction=transaction)
            if doc_snapshot.exists:
                raise ValueError(f"Custom short code '{ref.id}' is already in use.")
            transaction.set(ref, data_to_set)
        
        try:
            await _create_in_transaction(db_client.transaction(), doc_ref, data)
        except ValueError as e:
            # Re-raise the "already in use" error as a ValidationException equivalent
            raise ValueError(f"Custom code already exists")
    
    else:
        # --- 2b. Random Generation Path (Atomic Create) ---
        final_code = await generate_unique_short_code()
        doc_ref = get_collection_ref("links").document(final_code)
        
        try:
            # Use .create() for an atomic "create if not exists" operation.
            await doc_ref.create(data)
        except exceptions.AlreadyExists as e:
            logger.error(f"Critical collision on 'create' for {final_code}: {e}")
            raise RuntimeError(
                f"Failed to create link for {final_code} due to a rare collision."
            )
    
    return final_code


async def get_link_by_id(short_code: str) -> Optional[Dict[str, Any]]:
    """Retrieves a link record by its short code (Document ID) asynchronously."""
    doc_ref = get_collection_ref("links").document(short_code)
    doc = await doc_ref.get() 
    
    if doc.exists:
        data = doc.to_dict()
        data['short_code'] = doc.id 
        return data
    return None

async def delete_link_by_id_and_token(
    short_code: str, 
    token: str
) -> bool:
    """
    Atomically retrieves a doc, checks the deletion token, and deletes it.
    
    Returns: True on successful deletion.
    Raises: ValueError for invalid token, ResourceNotFoundException if link is not found.
    """
    db_client = get_db_connection()
    doc_ref = get_collection_ref("links").document(short_code)

    @firestore.transactional
    async def _delete_in_transaction(transaction: Transaction, ref, token_to_verify):
        doc_snapshot = await ref.get(transaction=transaction)

        if not doc_snapshot.exists:
            raise exceptions.NotFound(f"Link '{ref.id}' not found.")

        data = doc_snapshot.to_dict()
        hashed_token = data.get("deletion_token")

        if not hashed_token or not _verify_token(token_to_verify, hashed_token):
            raise ValueError("Invalid deletion token.")
            
        transaction.delete(doc_ref)
        return True

    try:
        await _delete_in_transaction(db_client.transaction(), doc_ref, token)
        logger.info(f"Successfully deleted link '{short_code}'.")
        return True
    except exceptions.NotFound:
        raise ResourceNotFoundException(f"Link '{short_code}' not found.")
    except ValueError as e:
        raise ValueError(e)
    except Exception as e:
        logger.error(f"Transaction failed for delete_link: {e}")
        raise RuntimeError("Deletion transaction failed.")

async def cleanup_expired_links(now: datetime):
    """
    Deletes all short link documents that have passed their expiration time
    using efficient Batched Writes (Async).
    """
    logger.info("Starting cleanup of expired links...")
    links_ref = get_collection_ref("links")
    db_client = get_db_connection()
    
    # NOTE: This query requires a Firestore Index on 'expires_at'
    expired_query = links_ref.where('expires_at', '<=', now).stream()
    
    deleted_count = 0
    batch = db_client.batch()
    batch_count = 0
    
    async for doc in expired_query: # <-- Use async for
        batch.delete(doc.reference)
        batch_count += 1
        deleted_count += 1
        
        # Firestore batches are limited to 500 operations
        if batch_count >= 499:
            await batch.commit() # <-- Await
            logger.info(f"Committed batch of {batch_count} deletions.")
            # Start a new batch
            batch = db_client.batch()
            batch_count = 0

    # Commit any remaining docs in the last batch
    if batch_count > 0:
        await batch.commit() # <-- Await
        logger.info(f"Committed final batch of {batch_count} deletions.")

    logger.info(f"Cleanup finished. Deleted {deleted_count} total expired links.")
    return deleted_count
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


def get_collection_ref(collection_name: str) -> firestore.AsyncCollectionReference:
    """Returns the AsyncCollectionReference for a public collection."""
    if not APP_ID:
        raise ValueError("APP_ID is not set. Cannot construct collection path.")
    
    # NOTE: Assuming 'links' are stored in a public/data sub-collection.
    # Adjust this path if your Firestore hierarchy is different.
    # If your links are at the root: return get_db_connection().collection(collection_name)
    path = f"artifacts/{APP_ID}/public/data/{collection_name}" 
    return get_db_connection().collection(path)


# --- Utility Functions ---

def _calculate_expiration(ttl_key: str) -> Optional[datetime]:
    """Calculate expiration datetime from TTL key."""
    delta: Optional[timedelta] = TTL_MAP.get(ttl_key)
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta

def _generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    """Generates a random short code using only lowercase letters and digits."""
    characters = string.ascii_lowercase + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

async def _is_short_code_unique(short_code: str) -> bool:
    """Checks the database asynchronously to see if a short code already exists."""
    get_db_connection()
    doc_ref = get_collection_ref("links").document(short_code)
    doc = await doc_ref.get() 
    return not doc.exists

async def generate_unique_short_code() -> str:
    """
    Generates a unique short code by checking the database and retrying on collision.
    """
    for attempt in range(MAX_ID_GENERATION_RETRIES):
        new_id = _generate_short_code()
        
        if await _is_short_code_unique(new_id): 
            return new_id
        
        logger.debug(f"Collision detected for ID: {new_id}. Retrying... (Attempt {attempt + 1})")

    raise RuntimeError(
        f"Failed to generate a unique short ID after {MAX_ID_GENERATION_RETRIES} attempts."
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
    
    # --- 1. Prepare Data ---
    hashed_token = _hash_token(deletion_token)
    expires_at = _calculate_expiration(ttl_key)
    
    data = {
        "long_url": long_url,
        "deletion_token": hashed_token, 
        "created_at": datetime.now(tz=timezone.utc),
        "clicks": 0,
        "owner_id": owner_id,
        "utm_tags": utm_tags,
        # Use a far-future date for "never expires" to simplify queries
        "expires_at": expires_at if expires_at else FAR_FUTURE_EXPIRY
    }
    
    if custom_code:
        # --- 2a. Custom Code Path (Atomic Check-and-Set) ---
        final_code = custom_code
        doc_ref = get_collection_ref("links").document(final_code)
        
        # Use a transaction to check-and-set atomically
        @firestore.transactional
        async def _create_in_transaction(transaction: Transaction, ref, data_to_set):
            doc_snapshot = await ref.get(transaction=transaction)
            if doc_snapshot.exists:
                raise ValueError(f"Custom short code '{ref.id}' is already in use.")
            transaction.set(ref, data_to_set)
        
        try:
            await _create_in_transaction(db_client.transaction(), doc_ref, data)
        except ValueError as e:
            # Re-raise the "already in use" error as a ValidationException equivalent
            raise ValueError(f"Custom code already exists")
    
    else:
        # --- 2b. Random Generation Path (Atomic Create) ---
        final_code = await generate_unique_short_code()
        doc_ref = get_collection_ref("links").document(final_code)
        
        try:
            # Use .create() for an atomic "create if not exists" operation.
            await doc_ref.create(data)
        except exceptions.AlreadyExists as e:
            logger.error(f"Critical collision on 'create' for {final_code}: {e}")
            raise RuntimeError(
                f"Failed to create link for {final_code} due to a rare collision."
            )
    
    return final_code


async def get_link_by_id(short_code: str) -> Optional[Dict[str, Any]]:
    """Retrieves a link record by its short code (Document ID) asynchronously."""
    doc_ref = get_collection_ref("links").document(short_code)
    doc = await doc_ref.get() 
    
    if doc.exists:
        data = doc.to_dict()
        data['short_code'] = doc.id 
        return data
    return None

async def delete_link_by_id_and_token(
    short_code: str, 
    token: str
) -> bool:
    """
    Atomically retrieves a doc, checks the deletion token, and deletes it.
    
    Returns: True on successful deletion.
    Raises: ValueError for invalid token, ResourceNotFoundException if link is not found.
    """
    db_client = get_db_connection()
    doc_ref = get_collection_ref("links").document(short_code)

    @firestore.transactional
    async def _delete_in_transaction(transaction: Transaction, ref, token_to_verify):
        doc_snapshot = await ref.get(transaction=transaction)

        if not doc_snapshot.exists:
            raise exceptions.NotFound(f"Link '{ref.id}' not found.")

        data = doc_snapshot.to_dict()
        hashed_token = data.get("deletion_token")

        if not hashed_token or not _verify_token(token_to_verify, hashed_token):
            raise ValueError("Invalid deletion token.")
            
        transaction.delete(ref)
        return True

    try:
        await _delete_in_transaction(db_client.transaction(), doc_ref, token)
        logger.info(f"Successfully deleted link '{short_code}'.")
        return True
    except exceptions.NotFound:
        raise ResourceNotFoundException(f"Link '{short_code}' not found.")
    except ValueError as e:
        raise ValueError(e)
    except Exception as e:
        logger.error(f"Transaction failed for delete_link: {e}")
        raise RuntimeError("Deletion transaction failed.")
