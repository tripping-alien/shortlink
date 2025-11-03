import os
import logging
import random
import string
import asyncio
import json 
import tempfile # <-- IMPORTANT: Needed for creating a temporary file
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone 

from firebase_admin import credentials, initialize_app, firestore

# Import the necessary constants from the user's config file
from config import SHORT_CODE_LENGTH, MAX_ID_GENERATION_RETRIES

# --- Environment Setup and Constants ---

logger = logging.getLogger(__name__)

CLIENT_APP_ID_FALLBACK = 'shortlink-app-default'

db: firestore.client = None
APP_ID: str = ""

def get_db_connection():
    """Initializes and returns the Firestore client (runs once)."""
    global db, APP_ID

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
                # Option 1: Running in environment with standard Service Account file path set
                cred = credentials.ApplicationDefault()
                logger.info("Using GOOGLE_APPLICATION_CREDENTIALS path.")
            elif firebase_config_str:
                # Option 2: Config provided as JSON string (from FIREBASE_CONFIG env var)
                # FIX for older firebase-admin versions (like 7.1.0): 
                # Write the JSON string to a temporary file path, then load the certificate from the file.
                
                # Use tempfile.NamedTemporaryFile for a secure way to handle the file
                with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
                    tmp_file.write(firebase_config_str)
                    temp_file_path = tmp_file.name # Store the path for cleanup
                
                # Now load credentials using the file path, which is supported by all versions
                cred = credentials.Certificate(temp_file_path)
                logger.info(f"Using FIREBASE_CONFIG JSON string via temporary file: {temp_file_path}")
            
            # 3. Handle missing configuration
            if cred is None:
                logger.error("FIREBASE_CONFIG or GOOGLE_APPLICATION_CREDENTIALS is not set. Cannot connect to Firebase.")
                raise ValueError("Firebase configuration is missing.")

            # 4. Initialize Firebase App (using a named app instance)
            initialize_app(cred, name=APP_ID)
            
            # 5. Get Firestore Client
            db = firestore.client()
            logger.info("Firebase Firestore client initialized successfully.")
            
        except Exception as e:
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
    This function is called by the application's lifespan event (e.g., in app.py).
    """
    get_db_connection()


def get_collection_ref(collection_name: str) -> firestore.CollectionReference:
    """Returns the CollectionReference for a public collection."""
    if not APP_ID:
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
    # Ensure connection is established before querying
    get_db_connection()
    doc_ref = get_collection_ref("links").document(short_code)
    doc = doc_ref.get()
    return not doc.exists

def generate_unique_short_code() -> str:
    """
    Generates a unique short code by checking the database and retrying on collision.
    """
    for attempt in range(MAX_ID_GENERATION_RETRIES):
        new_id = _generate_short_code()
        
        if _is_short_code_unique(new_id):
            return new_id
        
        logger.debug(f"Collision detected for ID: {new_id}. Retrying... (Attempt {attempt + 1})")

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
    short_code = generate_unique_short_code()
    
    data = {
        "long_url": long_url,
        "expires_at": expires_at, 
        "deletion_token": deletion_token,
        "created_at": datetime.now(tz=timezone.utc),
    }

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
