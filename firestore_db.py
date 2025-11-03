import os
import json
import base64
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
import traceback

# --- Firebase Admin SDK Imports ---
try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    # Set to None for runtime check
    firebase_admin = None
    credentials = None
    firestore = None
    print("WARNING: 'firebase-admin' is required to run this code.")

# --- Global Firestore DB reference ---
db: Optional[firestore.client] = None

# --- Firestore Configuration ---
FIREBASE_PROJECT_ID = 'web2-9a703'
CLIENT_APP_ID_FALLBACK = '1:912785521871:web:424284b2b6b4dbd4214bba'
# Use ENV variable or fallback for dynamic pathing
APP_ID = os.environ.get('APP_ID', CLIENT_APP_ID_FALLBACK)
COLLECTION_PATH = f"artifacts/{APP_ID}/public/data/links"


# --- Initialize Firestore using ENV or Local JSON ---
def init_db():
    """
    Initializes Firebase Admin SDK and Firestore client.
    Prioritizes FIREBASE_CREDENTIALS_JSON environment variable.
    """
    global db
    if db is not None:
        return

    if firebase_admin is None:
        print("Firebase Admin SDK not available. Cannot initialize DB.")
        return

    try:
        # Check if an app is already initialized
        try:
            firebase_admin.get_app()
        except ValueError:
            # --- 1. Attempt to load credentials from ENV variable (Secure Production Method) ---
            if os.environ.get('FIREBASE_CREDENTIALS_JSON'):
                try:
                    # Decode the base64-encoded JSON string
                    json_str = base64.b64decode(os.environ['FIREBASE_CREDENTIALS_JSON']).decode('utf-8')
                    cred_dict = json.loads(json_str)
                    cred = credentials.Certificate(cred_dict)
                    print("Attempting initialization with ENV variable...")
                except Exception:
                    print("WARNING: Failed to decode/parse FIREBASE_CREDENTIALS_JSON ENV variable.")
                    print(traceback.format_exc())
                    raise # Re-raise to try fallback

            # --- 2. Attempt to load credentials from local file (Local Dev Fallback) ---
            else:
                cred_path = './serviceAccountKey.json'
                if not os.path.exists(cred_path):
                    raise FileNotFoundError(f"Service account JSON not found at {cred_path} and ENV variable is missing.")
                cred = credentials.Certificate(cred_path)
                print(f"Attempting initialization with local file: {cred_path}")
            
            # Finalize initialization
            firebase_admin.initialize_app(cred, {'projectId': FIREBASE_PROJECT_ID})

        db = firestore.client()
        print("Firestore initialized successfully.")
    except Exception as e:
        print("ERROR: Failed to initialize Firestore.")
        print(traceback.format_exc())
        db = None
        raise # Raise to halt application startup if DB is critical


# --- CRUD Methods (using existing logic) ---

def create_link(long_url: str, expires_at: Optional[datetime], deletion_token: str) -> str:
    if db is None:
        raise ConnectionError("Database not initialized.")
    try:
        data: Dict[str, Any] = {
            'long_url': long_url,
            'expires_at': expires_at.astimezone(timezone.utc) if expires_at else None,
            'deletion_token': deletion_token,
            'created_at': datetime.now(timezone.utc)
        }
        # Simplified for clarity, assuming db is guaranteed non-None here
        doc_ref, _ = db.collection(COLLECTION_PATH).add(data)  
        return doc_ref.id
    except Exception as e:
        print("Error in create_link:")
        print(traceback.format_exc())
        raise


def get_link_by_id(link_id: str) -> Optional[Dict[str, Any]]:
    if db is None:
        raise ConnectionError("Database not initialized.")
    try:
        doc_ref = db.collection(COLLECTION_PATH).document(link_id)
        doc_snapshot = doc_ref.get()

        if not doc_snapshot.exists:
            return None

        data = doc_snapshot.to_dict()
        if data.get('expires_at') and data['expires_at'].astimezone(timezone.utc) < datetime.now(timezone.utc):
            return None  # Expired

        return {'id': link_id, **data}
    except Exception as e:
        print(f"Error in get_link_by_id({link_id}):")
        print(traceback.format_exc())
        raise


def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    if db is None:
        raise ConnectionError("Database not initialized.")
    active_links: List[Dict[str, Any]] = []
    now_utc = now.astimezone(timezone.utc)
    links_ref = db.collection(COLLECTION_PATH)

    try:
        # Links with no expiry
        # IMPORTANT: Firestore requires a composite index for chained queries or sorting.
        # Ensure you have indexes for 'expires_at' if you get errors.
        q1 = links_ref.where('expires_at', '==', None).stream()
        for doc in q1:
            active_links.append({'id': doc.id, **doc.to_dict()})
    except Exception as e:
        print("Warning (expires_at==None query failed):")
        print(traceback.format_exc())

    try:
        # Links with future expiry
        q2 = links_ref.where('expires_at', '>', now_utc).stream()
        for doc in q2:
            active_links.append({'id': doc.id, **doc.to_dict()})
    except Exception as e:
        print("Warning (expires_at>now query failed, may require index):")
        print(traceback.format_exc())

    return active_links


def cleanup_expired_links(now: datetime) -> int:
    if db is None:
        raise ConnectionError("Database not initialized.")
    now_utc = now.astimezone(timezone.utc)
    links_ref = db.collection(COLLECTION_PATH)
    deleted_count = 0

    try:
        query = links_ref.where('expires_at', '<', now_utc)
        batch = db.batch()
        for doc in query.stream():
            batch.delete(doc.reference)
            deleted_count += 1
        
        if deleted_count > 0:
            batch.commit()
    except Exception as e:
        print("Error in cleanup_expired_links:")
        print(traceback.format_exc())

    return deleted_count


def delete_link_by_id_and_token(link_id: str, token: str) -> int:
    if db is None:
        raise ConnectionError("Database not initialized.")
    try:
        doc_ref = db.collection(COLLECTION_PATH).document(link_id)
        # Only fetch the required field to save read cost
        doc_snapshot = doc_ref.get(['deletion_token']) 

        if doc_snapshot.exists and doc_snapshot.to_dict().get('deletion_token') == token:
            doc_ref.delete()
            return 1
        return 0
    except Exception as e:
        print(f"Error in delete_link_by_id_and_token({link_id}):")
        print(traceback.format_exc())
        raise

# --- Initialize DB on module import ---
# This ensures 'db' is ready when 'app.py' imports this module.
# The init_db() function uses the global 'db' and will only run once.
if firebase_admin:
    init_db()


# --- Local Testing ---
if __name__ == '__main__':
    from datetime import timedelta
    
    # If the database failed to initialize above, try again for local testing clarity
    if db is None:
        print("\nAttempting re-initialization for local test...")
        try:
            init_db()
        except:
            print("\nFATAL: Database could not be initialized for local test.")

    if db:
        print("\n--- Firestore API Test ---")
        # Existing test logic...
