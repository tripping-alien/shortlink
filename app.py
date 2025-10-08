import asyncio
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

import database
from encoding import decode_id
from i18n import load_translations, get_translator, DEFAULT_LANGUAGE
from router import api_router, ui_router
from config import Settings, get_settings

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Background Cleanup Task ---
async def cleanup_expired_links():
    """Periodically scans the database and removes expired links."""
    now = datetime.now(tz=timezone.utc)
    
    def db_cleanup():
        with database.get_db_connection() as conn:
            cursor = conn.execute("DELETE FROM links WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
            conn.commit()
            return cursor.rowcount
            
    deleted_count = await asyncio.to_thread(db_cleanup)
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} expired links.")


async def run_cleanup_task():
    """Runs the cleanup task in a loop."""
    while True:
        settings = get_settings()
        await cleanup_expired_links()
        await asyncio.sleep(settings.cleanup_interval_seconds)

# --- Lifespan Events for Startup and Shutdown ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the state from disk when the application starts
    print("Loading translations...")
    load_translations()
    print("Initializing database...")
    database.init_db()
    print("Starting background cleanup task...")
    cleanup_task = asyncio.create_task(run_cleanup_task())
    yield
    cleanup_task.cancel()


# --- FastAPI Application Setup ---
app = FastAPI(
    title="Bijective-Shorty API",
    description="A robust and efficient URL shortener using bijective base-6 encoding, TTL, and ID reuse. "
                "This API provides endpoints for creating, retrieving, and redirecting short links.",
    version="1.0.0",
    lifespan=lifespan,
    contact={
        "name": "API Support",
        "url": "https://github.com/your-repo",  # Replace with your project's repo
        "email": "your-email@example.com",
    },
)

settings = get_settings()

# --- Custom Exception Handlers for Robustness ---

@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError):
    """
    Handles ValueErrors that occur during request processing, typically from
    invalid short codes in `from_bijective_base6`. Returns a 404 response.
    """
    logger.warning(f"ValueError handled for request {request.url.path}: {exc}")
    # Use the translator from the request scope if available, otherwise default
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE))
    return JSONResponse(
        status_code=404,
        content={"detail": translator("Invalid short code format")},
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    """
    Catches any unhandled exceptions, logs the full error for debugging,
    and returns a generic 500 Internal Server Error to the user.
    This prevents leaking sensitive implementation details.
    """
    logger.error(f"Unhandled exception for request {request.url.path}", exc_info=True)
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE))
    return JSONResponse(
        status_code=500,
        content={"detail": translator("An unexpected internal error occurred.")},
    )


# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# CORS Middleware to allow the frontend to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _(text: str, **kwargs):
    """
    This is a placeholder for Jinja2. The actual translation happens
    via a context processor that we add to the TemplateResponse.
    """
    return text.format(**kwargs)


templates.env.globals['_'] = _


app.include_router(api_router)  # API routes are checked first
app.include_router(ui_router)   # UI routes are checked second


# This catch-all route MUST be defined last.
@app.get("/{short_code}", summary="Redirect to the original URL", tags=["Redirect"])
async def redirect_to_long_url(short_code: str, request: Request):
    """
    Redirects to the original URL if the short link exists and has not expired.
    If the link is expired, it is cleaned up and its ID is made available for reuse.
    This is the primary function of the service.
    """
    now = datetime.now(tz=timezone.utc)
    translator = get_translator()  # Defaults to 'en' for error messages on redirect
    # The ValueError from an invalid short_code is now handled by the exception handler
    url_id = decode_id(short_code)
    if url_id is None:
        # This handles cases where the short_code is malformed or invalid
        raise HTTPException(status_code=404, detail=translator("Short link not found"))
    
    record = await asyncio.to_thread(database.get_link_by_id, url_id)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Check if the link has an expiration date and if it has passed
    expires_at = record['expires_at']
    if expires_at and now > expires_at:
        # The background task will eventually remove it. For now, just deny access.
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    return RedirectResponse(url=record["long_url"])


# This block is useful for local development but not strictly needed for Render deployment
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
