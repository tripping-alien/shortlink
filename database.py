import os
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

try:
    import firebase_admin
    from firebase_admin import credentials, firestore
except ImportError:
    print("WARNING: 'firebase-admin' is required to run this code on a server.")
    firebase_admin = None
    credentials = None
    firestore = None

# --- Global Firestore DB reference ---
db: Optional[firestore.client] = None

# --- Firestore Configuration ---
FIREBASE_PROJECT_ID = 'web2-9a703'
CLIENT_APP_ID_FALLBACK = '1:912785521871:web:424284b2b6b4dbd4214bba'
APP_ID = os.environ.get('APP_ID', CLIENT_APP_ID_FALLBACK)
COLLECTION_PATH = f"artifacts/{APP_ID}/public/data/links"

# --- Initialize Firestore using local JSON ---
def init_db():
    """Initializes the Firebase Admin SDK and Firestore client using a local JSON."""
    global db
    if db is not None:
        print("Firestore already initialized.")
        return

    if firebase_admin is None:
        print("Firebase Admin SDK not installed. Cannot initialize DB.")
        return

    try:
        try:
            firebase_admin.get_app()
        except ValueError:
            # Path to your local JSON
            cred_path = os.environ.get('FIREBASE_CREDENTIALS_PATH', 'serviceAccountKey.json')
            cred = credentials.Certificate(cred_path)
            firebase_admin.initialize_app(cred, {'projectId': FIREBASE_PROJECT_ID})

        db = firestore.client()
        print("Firestore initialized successfully.")
    except Exception as e:
        print(f"ERROR: Failed to initialize Firestore. {e}")
        db = None


# --- CRUD Methods (Signatures unchanged) ---

def create_link(long_url: str, expires_at: Optional[datetime], deletion_token: str) -> str:
    if db is None:
        raise ConnectionError("Database not initialized.")

    data: Dict[str, Any] = {
        'long_url': long_url,
        'expires_at': expires_at.astimezone(timezone.utc) if expires_at else None,
        'deletion_token': deletion_token,
        'created_at': datetime.now(timezone.utc)
    }

    doc_ref, _ = db.collection(COLLECTION_PATH).add(data)
    return doc_ref.id


def get_link_by_id(link_id: str) -> Optional[Dict[str, Any]]:
    if db is None:
        raise ConnectionError("Database not initialized.")

    doc_ref = db.collection(COLLECTION_PATH).document(link_id)
    doc_snapshot = doc_ref.get()

    if not doc_snapshot.exists:
        return None

    data = doc_snapshot.to_dict()
    if data.get('expires_at') and data['expires_at'].astimezone(timezone.utc) < datetime.now(timezone.utc):
        return None  # Expired

    return {'id': link_id, **data}


def get_all_active_links(now: datetime) -> List[Dict[str, Any]]:
    if db is None:
        raise ConnectionError("Database not initialized.")

    now_utc = now.astimezone(timezone.utc)
    links_ref = db.collection(COLLECTION_PATH)
    active_links: List[Dict[str, Any]] = []

    # Links with no expiry
    try:
        q1 = links_ref.where('expires_at', '==', None).stream()
        for doc in q1:
            active_links.append({'id': doc.id, **doc.to_dict()})
    except Exception as e:
        print(f"Warning (expires_at==None): {e}")

    # Links with future expiry
    try:
        q2 = links_ref.where('expires_at', '>', now_utc).stream()
        for doc in q2:
            active_links.append({'id': doc.id, **doc.to_dict()})
    except Exception as e:
        print(f"Warning (expires_at>now): {e}")

    return active_links


def cleanup_expired_links(now: datetime) -> int:
    if db is None:
        raise ConnectionError("Database not initialized.")

    now_utc = now.astimezone(timezone.utc)
    links_ref = db.collection(COLLECTION_PATH)
    query = links_ref.where('expires_at', '<', now_utc)

    batch = db.batch()
    deleted_docs = []

    for doc in query.stream():
        batch.delete(doc.reference)
        deleted_docs.append(doc.id)

    if deleted_docs:
        batch.commit()

    return len(deleted_docs)


def delete_link_by_id_and_token(link_id: str, token: str) -> int:
    if db is None:
        raise ConnectionError("Database not initialized.")

    doc_ref = db.collection(COLLECTION_PATH).document(link_id)
    doc_snapshot = doc_ref.get(['deletion_token'])

    if doc_snapshot.exists and doc_snapshot.to_dict().get('deletion_token') == token:
        doc_ref.delete()
        return 1

    return 0


# --- Local Testing Example ---
if __name__ == '__main__':
    from datetime import timedelta
    import os

    init_db()

    if db:
        print("\n--- Firestore API Test ---")
        future_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        test_token = os.urandom(8).hex()

        new_id = create_link("https://www.firestore-test.com/new", future_time, test_token)
        print(f"Created Link: ID={new_id}, Token={test_token}")

        link_data = get_link_by_id(new_id)
        print(f"Retrieved Data: {link_data['long_url'] if link_data else 'Expired/None'}")

        active_links = get_all_active_links(datetime.now(timezone.utc))
        print(f"Active Links: {len(active_links)} found.")

        delete_result = delete_link_by_id_and_token(new_id, test_token)
        print(f"Deletion Result (1=Success): {delete_result}")

        verify = get_link_by_id(new_id)
        print(f"Verification: {'Deleted' if verify is None else 'Failed to delete'}")
