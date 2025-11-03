import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from hashids import Hashids
from slowapi.errors import RateLimitExceeded
from starlette.staticfiles import StaticFiles

# --- Import Firestore wrapper ---
import firestore_db

# --- Other imports from your project ---
from encoding import decode_id, get_hashids
from i18n import load_translations, get_translator, DEFAULT_LANGUAGE
from router import api_router, ui_router
from config import Settings, get_settings
from limiter import limiter

# --- Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Background Cleanup Task ---
async def cleanup_expired_links_task(settings: Settings):
    while True:
        now = datetime.now(tz=timezone.utc)
        
        # Check if DB is initialized before attempting cleanup
        if firestore_db.db is not None:
            deleted_count = 0
            try:
                # Cleanup is a synchronous operation, run in a thread
                deleted_count = await asyncio.to_thread(firestore_db.cleanup_expired_links, now)
            except Exception as e:
                logger.error(f"Error during background cleanup: {e}", exc_info=True)
            
            if deleted_count > 0:
                logger.info(f"Cleaned up {deleted_count} expired links.")
        else:
            logger.warning("DB not initialized. Skipping cleanup.")

        await asyncio.sleep(settings.cleanup_interval_seconds)

# --- Lifespan Events ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("Loading translations...")
    load_translations()

    print("Initializing Firestore database...")
    # The init_db function is now called, and on failure, firestore_db.db will be None
    firestore_db.init_db()

    # Start cleanup task only if settings can be retrieved
    try:
        settings = get_settings()
        print("Starting background cleanup task...")
        cleanup_task = asyncio.create_task(cleanup_expired_links_task(settings))
    except Exception as e:
        logger.critical(f"Failed to load settings or start cleanup task: {e}")
        cleanup_task = None
    
    yield
    if cleanup_task:
        cleanup_task.cancel()

# --- FastAPI Application Setup ---
app = FastAPI(
    title="Private, Secure, and Free Shortlinks API",
    description="A privacy-focused, secure, and simple URL shortener.",
    version="1.0.0",
    lifespan=lifespan,
    contact={
        "name": "Andrey Lopukhov",
        "url": "https://github.com/tripping-alien/shortlink",
        "email": "andreyevenflow@gmail.com",
    },
)

app.state.limiter = limiter

settings = get_settings()

# --- Exception Handlers ---
@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError):
    logger.warning(f"ValueError handled for request {request.url.path}: {exc}")
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE))
    return JSONResponse(status_code=404, content={"detail": translator("Invalid short code format")})

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception for request {request.url.path}", exc_info=True)
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE))
    return JSONResponse(status_code=500, content={"detail": translator("An unexpected internal error occurred.")})

@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE))
    return JSONResponse(status_code=429, content={"detail": translator("Rate limit exceeded. Please try again later.")})

# --- Static Files and Templates ---
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def _(text: str, **kwargs):
    return text.format(**kwargs)
templates.env.globals['_'] = _

# --- CRITICAL Health Check Route ---
@app.get("/health")
async def health_check():
    """Checks the application's responsiveness and database connection status."""
    # Check if the app is responsive
    if firestore_db.db is None:
        # If the DB client is None, the app is running but the DB is unhealthy.
        return JSONResponse({"status": "error", "message": "Database not connected"}, status_code=503)
        
    # If we made it here, the event loop is responsive and the DB client is ready.
    return {"status": "ok"} 

# --- Include Routers ---
app.include_router(api_router)
app.include_router(ui_router)

# --- Core Dependencies (MOVED UP) ---
async def get_valid_link_or_404(short_code: str, hashids: Hashids = Depends(get_hashids)):
    translator = get_translator()
    url_id = decode_id(short_code, hashids)
    if url_id is None:
        raise HTTPException(status_code=404, detail=translator("Invalid short code format"))

    record = await asyncio.to_thread(firestore_db.get_link_by_id, url_id)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    expires_at = record['expires_at']
    if expires_at and datetime.now(timezone.utc) > expires_at:
        # Note: Your firestore_db.get_link_by_id already handles expiry internally
        pass # Leaving this check here for redundancy if needed

    return record

# --- Core Routes ---
@app.get("/")
async def read_root():
    return {"message": "Welcome to the service."}
    
@app.get("/get/{short_code}", summary="Preview Short Link", include_in_schema=False)
async def preview_short_link(request: Request, record: dict = Depends(get_valid_link_or_404)):
    return templates.TemplateResponse("preview.html", {
        "request": request,
        "long_url": record["long_url"]
    })
    
@app.get("/{short_code}", summary="Redirect to the original URL", include_in_schema=False)
async def redirect_to_long_url(record: dict = Depends(get_valid_link_or_404)):
    return RedirectResponse(url=record["long_url"])

# --- Optional Firestore API Routes ---
@app.post("/links")
async def api_create_link(request: Request):
    data = await request.json()
    long_url = data.get("long_url")
    expires_at_str = data.get("expires_at")
    deletion_token = data.get("deletion_token")
    expires_at = datetime.fromisoformat(expires_at_str) if expires_at_str else None
    new_id = await asyncio.to_thread(firestore_db.create_link, long_url, expires_at, deletion_token)
    return JSONResponse({"id": new_id}, status_code=201)

@app.get("/links/active")
async def api_get_active_links():
    links = await asyncio.to_thread(firestore_db.get_all_active_links, datetime.now(timezone.utc))
    return JSONResponse({"active_links": links})

@app.delete("/links/{link_id}")
async def api_delete_link(link_id: str, token: str):
    if not token:
        raise HTTPException(status_code=400, detail="Missing deletion token")
    result = await asyncio.to_thread(firestore_db.delete_link_by_id_and_token, link_id, token)
    if result == 0:
        raise HTTPException(status_code=404, detail="Not found or invalid token")
    return JSONResponse({"deleted": True})

# --- Run Local Server ---
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)

