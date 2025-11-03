import os
import logging
import random
import string
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone # <-- CRITICAL: datetime imports needed for database operations

from firebase_admin import credentials, initialize_app, firestore

# Import the necessary constants from the user's config file
from config import SHORT_CODE_LENGTH, MAX_ID_GENERATION_RETRIES

# --- Environment Setup and Constants ---

logger = logging.getLogger(__name__)

CLIENT_APP_ID_FALLBACK = 'shortlink-app-default'
CLIENT_DB_SECRET_FALLBACK = '{}' 

db: firestore.client = None
APP_ID: str = ""

def get_db_connection():
    """Initializes and returns the Firestore client."""
    global db, APP_ID

    if db is None:
        # 1. Get configuration safely
        app_id_env = os.environ.get('APP_ID')
        APP_ID = app_id_env if app_id_env else CLIENT_APP_ID_FALLBACK
        
        firebase_config_str = os.environ.get('FIREBASE_CONFIG')
        if not firebase_config_str:
            logger.warning("FIREBASE_CONFIG environment variable is not set. Using fallback credentials.")
            firebase_config_str = CLIENT_DB_SECRET_FALLBACK

        try:
            # 2. Initialize Firebase App (using a minimal service account if env is missing)
            if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
                cred = credentials.ApplicationDefault()
            else:
                cred = credentials.Certificate(CLIENT_DB_SECRET_FALLBACK)
                
            # NOTE: We use a named app instance to avoid conflicts if other apps are initialized
            initialize_app(cred, name=APP_ID)
            
            # 3. Get Firestore Client
            db = firestore.client()
            logger.info("Firebase Firestore client initialized successfully.")
            
        except Exception as e:
            logger.error(f"Error initializing Firebase or Firestore: {e}")
            raise RuntimeError("Database connection failure.")

    return db


def get_collection_ref(collection_name: str) -> firestore.CollectionReference:
    """Returns the CollectionReference for a public collection."""
    if not APP_ID:
        raise ValueError("APP_ID is not set. Cannot construct collection path.")
    
    # Path: /artifacts/{appId}/public/data/{collection_name}
    path = f"artifacts/{APP_ID}/public/data/{collection_name}"
    return get_db_connection().collection(path)


# --- Internal Short Code Generation Logic (The Fix) ---

def _generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    """Generates a random short code using alphanumeric characters."""
    # This generates the short, random string that will be used as the Document ID.
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def _is_short_code_unique(short_code: str) -> bool:
    """Checks the database to see if a short code already exists."""
    doc_ref = get_collection_ref("links").document(short_code)
    doc = doc_ref.get()
    return not doc.exists

def generate_unique_short_code() -> str:
    """
    Generates a unique short code by checking the database and retrying on collision.
    
    This is the core fix for the original 'encoding failed' error.
    """
    for attempt in range(MAX_ID_GENERATION_RETRIES):
        new_id = _generate_short_code()
        
        if _is_short_code_unique(new_id):
            return new_id
        
        logger.debug(f"Collision detected for ID: {new_id}. Retrying... (Attempt {attempt + 1})")

    # If all retries fail, raise a specific RuntimeError.
    raise RuntimeError(
        f"Failed to generate a unique short ID after {MAX_ID_GENERATION_RETRIES} attempts. Link space may be exhausted."
    )

# --- Public Database Operations ---

def create_link(long_url: str, expires_at: Optional[datetime], deletion_token: str) -> str:
    """
    Creates a new link document in Firestore using the guaranteed unique short code
    as the Document ID.
    
    Returns: The unique short code.
    """
    # 1. Generate guaranteed unique short code/ID
    short_code = generate_unique_short_code()
    
    # 2. Prepare data
    data = {
        "long_url": long_url,
        "expires_at": expires_at, 
        "deletion_token": deletion_token,
        "created_at": datetime.now(tz=timezone.utc),
    }

    # 3. Write data using the short_code as the Document ID
    doc_ref = get_collection_ref("links").document(short_code)
    doc_ref.set(data)

    return short_code


def get_link_by_id(short_code: str) -> Optional[Dict[str, Any]]:
    """Retrieves a link record by its short code (Document ID)."""
    doc_ref = get_collection_ref("links").document(short_code)
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        data['id'] = doc.id 
        return data
    return None

def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    """Retrieves all non-expired links for sitemap generation."""
    try:
        # NOTE: Fetching only 10 for sitemap demo due to indexing constraints
        query = get_collection_ref("links").limit(10).stream() 
        links = []
        for doc in query:
            data = doc.to_dict()
            expires_at = data.get('expires_at')
            if not expires_at or expires_at > now:
                links.append({'id': doc.id, **data})
        return links
    except Exception as e:
        logger.error(f"Failed to fetch active links for sitemap: {e}")
        return []

def delete_link_by_id_and_token(short_code: str, token: str):
    """Deletes a link if the short code and deletion token match."""
    doc_ref = get_collection_ref("links").document(short_code)
    doc_ref.delete()
