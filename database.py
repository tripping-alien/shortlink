import os
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

# NOTE: For this code to run on a Python server, you must install the Firebase Admin SDK:
# pip install firebase-admin
# Ensure you set up service account credentials or Application Default Credentials for production.

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    # Handle missing library in the local environment gracefully
    print("WARNING: The 'firebase-admin' library is required to run this code on a server.")
    firebase_admin = None
    credentials = None
    firestore = None

# --- Global Initialization ---
db: Optional[firestore.client] = None

# EXPLICITLY DEFINED IDs from your Firebase configuration snippet:
FIREBASE_PROJECT_ID = 'web2-9a703'
# This is the client-side 'appId'. We use it as the default fallback for the path construction.
CLIENT_APP_ID_FALLBACK = '1:912785521871:web:424284b2b6b4dbd4214bba'

# This APP_ID determines the root path for Canvas Firestore security rules (artifacts/{APP_ID}/...)
# It uses the environment variable first, then falls back to the explicit client appId.
APP_ID = os.environ.get('APP_ID', CLIENT_APP_ID_FALLBACK)
# Define the collection path based on Canvas environment rules for public data
COLLECTION_PATH = f"artifacts/{APP_ID}/public/data/links"


def init_db():
    """Initializes the Firebase Admin SDK and Firestore connection."""
    global db
    if db is not None:
        print("Firestore already initialized.")
        return

    print("Initializing Firebase Admin SDK...")
    try:
        if not firebase_admin.apps:
            # Options dictionary to explicitly set the project ID
            options = {'projectId': FIREBASE_PROJECT_ID}
            
            # Use Application Default Credentials (ADC) or a provided credentials file
            if os.environ.get('FIREBASE_CREDENTIALS_PATH'):
                cred = credentials.Certificate(os.environ['FIREBASE_CREDENTIALS_PATH'])
                # Initialize using explicit credentials and the project ID option
                firebase_admin.initialize_app(cred, options=options)
            else:
                # Use ADC, providing project ID explicitly
                firebase_admin.initialize_app(options=options)
        
        db = firestore.client()
        print("Firestore initialized successfully.")

    except Exception as e:
        print(f"ERROR: Failed to initialize Firebase Admin SDK. Ensure credentials are set. {e}")
        db = None


# --- Database API Functions (Signatures Maintained, ID type updated to str) ---

def create_link(long_url: str, expires_at: Optional[datetime], deletion_token: str) -> str:
    """
    Inserts a new link into Firestore and returns its document ID (the short link ID).
    NOTE: The return type is str (Firestore Document ID) instead of int.
    """
    if db is None: raise ConnectionError("Database not initialized.")

    data: Dict[str, Any] = {
        'long_url': long_url,
        # Ensure datetime object is UTC-aware or None
        'expires_at': expires_at.astimezone(timezone.utc) if expires_at else None,
        'deletion_token': deletion_token,
        'created_at': datetime.now(timezone.utc)
    }
    
    # add() creates a document and returns a DocumentReference and UpdateTime tuple
    _, doc_ref = db.collection(COLLECTION_PATH).add(data)
    
    return doc_ref.id


def get_link_by_id(link_id: str) -> Optional[Dict[str, Any]]:
    """
    Retrieves a single link's data by its Firestore document ID (short link ID).
    NOTE: link_id must be a string.
    """
    if db is None: raise ConnectionError("Database not initialized.")

    doc_ref = db.collection(COLLECTION_PATH).document(link_id)
    doc_snapshot = doc_ref.get()

    if doc_snapshot.exists:
        data = doc_snapshot.to_dict()
        
        # Check for expiration
        if data.get('expires_at'):
            # Convert Firestore Timestamp to UTC datetime for comparison
            expiry_dt = data['expires_at'].astimezone(timezone.utc)
            if expiry_dt < datetime.now(timezone.utc):
                return None  # Link is expired
        
        # Return link data, including the ID
        return {'id': link_id, **data}
    
    return None


def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    """
    Retrieves all links that have not expired.
    Uses two distinct Firestore queries due to query limitations (combining '==' None and '>' time).
    """
    if db is None: raise ConnectionError("Database not initialized.")
    now_utc = now.astimezone(timezone.utc)
    
    links_ref = db.collection(COLLECTION_PATH)
    active_links: List[Dict[str, Any]] = []

    # Q1: Links with no expiry (expires_at == None)
    try:
        q1 = links_ref.where('expires_at', '==', None).stream()
        for doc in q1:
            active_links.append({'id': doc.id, **doc.to_dict()})
    except Exception as e:
        print(f"Warning (Q1: None expiry): {e}")
        
    # Q2: Links with future expiry (expires_at > now)
    try:
        q2 = links_ref.where('expires_at', '>', now_utc).stream()
        for doc in q2:
            active_links.append({'id': doc.id, **doc.to_dict()})
    except Exception as e:
        print(f"Warning (Q2: Future expiry): {e}")
        # Reminder: This query often requires a composite index in Firestore.

    return active_links


def cleanup_expired_links(now: datetime) -> int:
    """Deletes all links that have expired and returns the count of deleted rows."""
    if db is None: raise ConnectionError("Database not initialized.")
    now_utc = now.astimezone(timezone.utc)
    
    links_ref = db.collection(COLLECTION_PATH)
    
    # Query for documents where expires_at is in the past
    query = links_ref.where('expires_at', '<', now_utc)
    
    batch = db.batch()
    docs_to_delete = []
    
    for doc in query.stream():
        batch.delete(doc.reference)
        docs_to_delete.append(doc.id)

    if docs_to_delete:
        batch.commit()
    
    return len(docs_to_delete)


def delete_link_by_id_and_token(link_id: str, token: str) -> int:
    """
    Deletes a link from the database only if the ID (string) and deletion_token match.
    Returns 1 for success, 0 for failure (not found or token mismatch).
    """
    if db is None: raise ConnectionError("Database not initialized.")

    doc_ref = db.collection(COLLECTION_PATH).document(link_id)
    # Fetch only the token field for efficiency
    doc_snapshot = doc_ref.get(['deletion_token']) 

    if doc_snapshot.exists:
        data = doc_snapshot.to_dict()
        
        # Check the token
        if data and data.get('deletion_token') == token:
            doc_ref.delete()
            return 1 # Successfully deleted
    
    return 0 # Not found or token mismatch

if __name__ == '__main__':
    # --- Local Testing Example ---
    from datetime import timedelta
    
    init_db()

    if db:
        print("\n--- Testing Firestore API ---")
        
        # 1. Setup Data
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        test_token = os.urandom(8).hex()
        
        try:
            print("1. Creating link...")
            new_id = create_link("https://www.firestore-test.com/new", future_time, test_token)
            print(f"   Created Link (ID: {new_id}, Token: {test_token})")

            # 2. Retrieve Data
            link_data = get_link_by_id(new_id)
            print(f"2. Retrieved Data: {link_data['long_url'] if link_data else 'Error'}")

            # 3. Check Active Links
            active_links = get_all_active_links(datetime.now(timezone.utc))
            print(f"3. Found {len(active_links)} active links.")

            # 4. Attempt Deletion with correct token
            print("4. Deleting link...")
            delete_result = delete_link_by_id_and_token(new_id, test_token)
            print(f"   Deletion result (1=Success): {delete_result}")
            
            # 5. Verify Deletion
            verify = get_link_by_id(new_id)
            print(f"5. Verification check: {'Deleted' if verify is None else 'Failed to delete'}")


        except ConnectionError as ce:
            print(f"\nOperation failed: {ce}")
        except Exception as e:
            print(f"\nAn unexpected error occurred during testing: {e}")

