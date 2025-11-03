import secrets
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, List
# Import Path for reliable path handling
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Local imports - UPDATED to use the new config structure
from config import get_settings, TTL_MAP, TTL 
from schemas import LinkCreate, ShortLinkResponse
import database

# --- FastAPI Setup ---
app = FastAPI(title="Shortlinks Service", version="1.0.0")
logger = logging.getLogger(__name__)

# Initialize settings and determine the BASE_URL
settings = get_settings() 
# Ensure BASE_URL is a string without trailing slash for consistent URL generation
BASE_URL = str(settings.base_url).rstrip('/') 

# Global state to track database initialization status
DB_INITIALIZED = False

# Mock Translator function for template rendering (replace with actual translation library if needed)
def _(text: str) -> str:
    # This is a placeholder for the Jinja translation function
    return text

# Setup templates and static files
# MODIFIED: Use the directory of the current file (app.py) as the template directory.
# This ensures that Jinja2 always finds 'index.html' if it's placed next to app.py.
BASE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE_DIR))
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.on_event("startup")
async def startup_event():
    """Initialize database connection on application startup."""
    global DB_INITIALIZED
    try:
        # Note: If database.init_db() is failing due to missing env vars, 
        # this is the source of the hidden 500 error.
        database.init_db()
        DB_INITIALIZED = True
        logger.info("Database initialized successfully.")
    except Exception as e:
        logger.error(f"Failed to initialize database: {e}. Check FIREBASE_CONFIG and required environment variables.")
        # DB_INITIALIZED remains False, but the app continues running.


# --- Helper Functions ---

def calculate_expiration(ttl_string: str) -> Optional[datetime]:
    """Calculates the expiration time based on a time-to-live string using TTL_MAP."""
    if ttl_string == TTL.NEVER:
        return None
    
    now = datetime.now(timezone.utc)
    
    try:
        # Look up the timedelta in the new TTL_MAP from config
        duration = TTL_MAP.get(TTL(ttl_string))
        if duration:
            return now + duration
    except ValueError:
        # If ttl_string is not a valid TTL enum value, log and fall through
        logger.warning(f"Received invalid TTL value: {ttl_string}")
        
    # Default fallback to 1 day if calculation fails (using the constant from TTL_MAP)
    return now + TTL_MAP[TTL.ONE_DAY] 

# --- Routes ---

@app.get("/health")
async def health_check():
    """Simple health check endpoint that also checks DB status."""
    # Modified to include DB status for better monitoring
    if not DB_INITIALIZED:
        logger.error("Health check passed, but database initialization failed.")
        return {"status": "warning", "database": "uninitialized"}
        
    return {"status": "ok", "database": "initialized"}

@app.get("/")
async def root_redirect():
    """Redirects the root URL to the default English UI page."""
    # Using a 307 Temporary Redirect to send the user to the default language UI
    return RedirectResponse(url="/ui/en/", status_code=307)


@app.get("/ui/{lang_code}/", response_class=HTMLResponse)
async def serve_index(request: Request, lang_code: str):
    """Serves the main shortener UI (index.html)."""
    context = {
        "request": request, 
        "base_url": BASE_URL, 
        "lang_code": lang_code, 
        "_": _ # Mock translation function
    }
    # Templates.TemplateResponse uses the directory defined above (BASE_DIR)
    return templates.TemplateResponse("index.html", context)

@app.post("/api/v1/links", response_model=ShortLinkResponse, status_code=201)
async def create_short_link(link_data: LinkCreate):
    """Creates a new short link, using a custom code if provided."""
    
    # NEW: Check DB status before attempting operation
    if not DB_INITIALIZED:
        raise HTTPException(status_code=503, detail="Service Unavailable: Database not initialized.")

    # 1. Calculate Expiration and Deletion Token
    expiration_time = calculate_expiration(link_data.ttl)
    deletion_token = secrets.token_urlsafe(32)

    try:
        # 2. Call the MODIFIED create_link function
        short_code = database.create_link(
            long_url=link_data.long_url, 
            expires_at=expiration_time, 
            deletion_token=deletion_token,
            # PASS THE CUSTOM CODE HERE
            short_code=link_data.custom_code
        )
        
        # 3. Construct and return the response
        full_short_url = f"{BASE_URL}/{short_code}"
        
        return ShortLinkResponse(
            long_url=link_data.long_url,
            short_url=full_short_url,
            deletion_token=deletion_token,
        )

    except ValueError as e:
        # Handle custom code collision or invalid format (as returned by database.py)
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        # Handle ID generation failure
        raise HTTPException(status_code=500, detail="Failed to generate a unique ID. Link space may be exhausted.")

@app.get("/{short_code}")
async def redirect_to_long_url(short_code: str):
    """Redirects the user from the short code to the long URL."""
    # NEW: Check DB status before attempting operation
    if not DB_INITIALIZED:
        raise HTTPException(status_code=503, detail="Service Unavailable: Database not initialized.")

    link_data = database.get_link_by_id(short_code)
    
    if not link_data:
        raise HTTPException(status_code=404, detail="Short link not found.")
        
    # Check for expiration (already checked in database.py, but good to double-check)
    expires_at = link_data.get('expires_at')
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Short link has expired.")

    # Redirect to the stored long URL
    return RedirectResponse(url=link_data['long_url'], status_code=307)


@app.get("/api/v1/translations/{lang_code}")
async def get_translations(lang_code: str):
    """Mock endpoint to serve client translations for script.js."""
    # In a real app, you would load the JSON file for the given language.
    # For this example, we return a working set of English defaults.
    return JSONResponse({
        "copy": "Copy",
        "copied": "Copied!",
        "ttl_1_hour": "1 Hour",
        "ttl_24_hours": "24 Hours",
        "ttl_1_week": "1 Week",
        "expire_never": "Your link will not expire.",
        "expire_in_duration": "Your link is private and will automatically expire in {duration}.",
        "default_error": "An unexpected error occurred.",
        "network_error": "Failed to connect to the server. Check your network or try again later.",
        "invalid_custom_code": "Custom suffix must only contain lowercase letters (a-z) and numbers (0-9)."
    })
