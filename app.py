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
from hashids import Hashids
from slowapi.errors import RateLimitExceeded
from starlette.staticfiles import StaticFiles

import database
from encoding import decode_id, get_hashids
from i18n import load_translations, get_translator, DEFAULT_LANGUAGE
from router import api_router, ui_router
from config import Settings, get_settings
from limiter import limiter

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Background Cleanup Task ---
async def cleanup_expired_links(settings: Settings):
    """Periodically scans the database and removes expired links."""
    now = datetime.now(tz=timezone.utc)
    deleted_count = await asyncio.to_thread(database.cleanup_expired_links, now)
    if deleted_count > 0:
        logger.info(f"Cleaned up {deleted_count} expired links.")


async def run_cleanup_task(settings: Settings):
    """Runs the cleanup task in a loop."""
    while True:
        await cleanup_expired_links(settings)
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
    # Pass settings to the task to avoid re-fetching in the loop
    cleanup_task = asyncio.create_task(run_cleanup_task(get_settings()))
    yield
    cleanup_task.cancel()


# --- FastAPI Application Setup ---
app = FastAPI(
    title="Private, Secure, and Free Shortlinks API",
    description="A privacy-focused, secure, and simple URL shortener. This API provides endpoints for creating and managing short links.",
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

# --- Custom Exception Handlers for Robustness ---

@app.exception_handler(ValueError)
async def value_error_exception_handler(request: Request, exc: ValueError):
    """
    Handles ValueErrors that occur during request processing, typically from
    invalid short codes. Returns a 404 response.
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


@app.exception_handler(RateLimitExceeded)
async def rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded):
    """
    Handles RateLimitExceeded errors, returning a 429 Too Many Requests response.
    """
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE))
    return JSONResponse(
        status_code=429,
        content={"detail": translator("Rate limit exceeded. Please try again later.")}
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


# --- Core Application Routes (Catch-All) ---

async def get_valid_link_or_404(short_code: str, hashids: Hashids = Depends(get_hashids)):
    """
    A reusable dependency to decode a short code and fetch the corresponding
    link from the database, handling all validation and not-found cases.
    """
    translator = get_translator()
    url_id = decode_id(short_code, hashids)
    if url_id is None:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    record = await asyncio.to_thread(database.get_link_by_id, url_id)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    expires_at = record['expires_at']
    if expires_at and datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    return record


@app.get("/get/{short_code}", summary="Preview Short Link", tags=["Redirect"], include_in_schema=False)
async def preview_short_link(request: Request, record: dict = Depends(get_valid_link_or_404)):
    """
    Shows a preview page with the destination URL, allowing the user to
    confirm before redirecting.
    """
    return templates.TemplateResponse("preview.html", {
        "request": request,
        "long_url": record["long_url"]
    })


@app.get("/{short_code}", summary="Redirect to the original URL", tags=["Redirect"], include_in_schema=False)
async def redirect_to_long_url(record: dict = Depends(get_valid_link_or_404)):
    """
    Redirects to the original URL if the short link exists and has not expired.
    This is the primary function of the service.
    """
    return RedirectResponse(url=record["long_url"])


# This block is useful for local development but not strictly needed for Render deployment
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
