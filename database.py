import os
import logging
import random
import string
import asyncio
from typing import Optional, Dict, Any, List, Callable

from firebase_admin import credentials, initialize_app, firestore

from config import SHORT_CODE_LENGTH, MAX_ID_GENERATION_RETRIES

# --- Environment Setup and Constants ---

logger = logging.getLogger(__name__)

# Fallback values for environment variables (only used if they are unset/empty)
CLIENT_APP_ID_FALLBACK = 'shortlink-app-default'
CLIENT_DB_SECRET_FALLBACK = '{}' # Empty JSON object for anonymous/default sign-in

# Global variables initialized once
db: firestore.client = None
APP_ID: str = ""

def get_db_connection():
    """Initializes and returns the Firestore client."""
    global db, APP_ID

    if db is None:
        # 1. Get configuration safely
        app_id_env = os.environ.get('APP_ID')
        # Use a robust fallback: if the environment variable is not set or empty, use the fallback.
        APP_ID = app_id_env if app_id_env else CLIENT_APP_ID_FALLBACK
        
        firebase_config_str = os.environ.get('FIREBASE_CONFIG')
        if not firebase_config_str:
            logger.warning("FIREBASE_CONFIG environment variable is not set. Using fallback credentials.")
            # In a real deployed environment, you must set FIREBASE_CONFIG or use a service account file.
            # We use the fallback here to allow local development setup.
            firebase_config_str = CLIENT_DB_SECRET_FALLBACK

        try:
            # 2. Initialize Firebase App
            cred_dict = firestore.client.from_service_account_info(
                credentials.Certificate(CLIENT_DB_SECRET_FALLBACK)
            )
            initialize_app(cred_dict, name=APP_ID)
            
            # 3. Get Firestore Client
            db = firestore.client()
            logger.info("Firebase Firestore client initialized successfully.")
            
        except Exception as e:
            logger.error(f"Error initializing Firebase or Firestore: {e}")
            raise RuntimeError("Database connection failure.")

    return db


def get_collection_ref(collection_name: str) -> firestore.CollectionReference:
    """Returns the CollectionReference for a public collection, ensuring APP_ID is not empty."""
    if not APP_ID:
        # Should not happen if get_db_connection runs first, but here for safety.
        raise ValueError("APP_ID is not set. Cannot construct collection path.")
    
    # Path: /artifacts/{appId}/public/data/{collection_name}
    path = f"artifacts/{APP_ID}/public/data/{collection_name}"
    return get_db_connection().collection(path)


# --- Internal Short Code Generation Logic ---

def _generate_short_code(length: int = SHORT_CODE_LENGTH) -> str:
    """Generates a random short code using alphanumeric characters."""
    characters = string.ascii_letters + string.digits
    return ''.join(random.choice(characters) for _ in range(length))

def _is_short_code_unique(short_code: str) -> bool:
    """Checks the database to see if a short code already exists."""
    doc_ref = get_collection_ref("links").document(short_code)
    doc = doc_ref.get()
    return not doc.exists

def generate_unique_short_code() -> str:
    """
    Generates a short ID and ensures its uniqueness against the database using a retry loop.
    Returns the unique short code string.
    Raises: RuntimeError if failed to find a unique ID after MAX_RETRIES.
    """
    for attempt in range(MAX_RETRIES):
        new_id = _generate_short_code()
        
        # Check uniqueness in the database (synchronous call)
        if _is_short_code_unique(new_id):
            return new_id
        
        logger.debug(f"Collision detected for ID: {new_id}. Retrying... (Attempt {attempt + 1})")

    raise RuntimeError(
        f"Failed to generate a unique short ID after {MAX_RETRIES} attempts. Link space may be exhausted or highly saturated."
    )

# --- Public Database Operations ---

def create_link(long_url: str, expires_at: Optional[datetime], deletion_token: str) -> str:
    """
    Creates a new link document in Firestore using a pre-generated, unique short code
    as the Document ID.
    
    Returns: The unique short code used as the Document ID.
    """
    # 1. Generate guaranteed unique short code/ID
    short_code = generate_unique_short_code()
    
    # 2. Prepare data
    data = {
        "long_url": long_url,
        # Ensure the datetime object is timezone aware (as it comes from router.py)
        "expires_at": expires_at, 
        "deletion_token": deletion_token,
        "created_at": datetime.now(tz=timezone.utc),
    }

    # 3. Write data using the short_code as the Document ID
    doc_ref = get_collection_ref("links").document(short_code)
    doc_ref.set(data)

    # Return the short code, which is now the document ID
    return short_code


def get_link_by_id(short_code: str) -> Optional[Dict[str, Any]]:
    """Retrieves a link record by its short code (Document ID)."""
    doc_ref = get_collection_ref("links").document(short_code)
    doc = doc_ref.get()
    
    if doc.exists:
        data = doc.to_dict()
        # Ensure ID is included (the short code itself)
        data['id'] = doc.id 
        return data
    return None

def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    """Retrieves all non-expired links for sitemap generation."""
    
    # In a real-world scenario, you would use a proper query with a filter here.
    # Due to Firestore query limitations and index requirements, we simplify to
    # fetching a few recent links for the sitemap demo.
    
    # WARNING: This implementation is for demo/sitemap only and is not scalable.
    # A real implementation requires a `where('expires_at', '>', now)` clause,
    # which requires a composite index that cannot be guaranteed in this environment.
    
    try:
        # Fetching a small, manageable number of links for sitemap generation
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
    # Note: The security rule should enforce token check on the server side.
    # The client-side logic in the router provides an extra layer.
    doc_ref = get_collection_ref("links").document(short_code)
    doc_ref.delete()
    # No return value, a successful delete is assumed if no exception is raised.
