import asyncio
import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, date, timezone
from enum import Enum

import uvicorn
from fastapi import FastAPI, HTTPException, Request, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, HttpUrl, field_validator, Field
from pydantic_settings import BaseSettings
from starlette.staticfiles import StaticFiles

import database

# --- Setup Logging ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


# --- Configuration Management ---
class Settings(BaseSettings):
    """Manages application configuration using environment variables."""
    # Use Render's persistent disk path. Default to local file for development.
    db_file: str = os.path.join(os.environ.get('RENDER_DISK_PATH', '.'), 'db.json')
    # In production, set this to your frontend's domain: "https://your-frontend.com"
    # The default ["*"] is insecure and for development only.
    cors_origins: list[str] = ["*"]
    cleanup_interval_seconds: int = 3600  # Run cleanup task every hour


settings = Settings()

# --- Custom I18n Implementation (replaces fastapi-i18n) ---

TRANSLATIONS = {}
DEFAULT_LANGUAGE = "en"


def load_translations():
    """
    Parses .po files from the locales directory and loads them into memory.
    This is a simple parser that handles the basic msgid/msgstr format.
    """
    locales_dir = "locales"
    if not os.path.isdir(locales_dir):
        return

    for lang in os.listdir(locales_dir):
        po_file = os.path.join(locales_dir, lang, "LC_MESSAGES", "messages.po")
        if os.path.exists(po_file):
            with open(po_file, "r", encoding="utf-8") as f:
                content = f.read()

            translations = {}
            # Regex to find msgid "" and msgstr "" pairs
            pattern = re.compile(r'msgid "((?:\\.|[^"])*)"\s+msgstr "((?:\\.|[^"])*)"', re.DOTALL)

            for match in pattern.finditer(content):
                msgid = match.group(1).replace('\\"', '"').replace('\\n', '\n')
                msgstr = match.group(2).replace('\\"', '"').replace('\\n', '\n')
                if msgid:  # Ensure msgid is not empty
                    translations[msgid] = msgstr

            TRANSLATIONS[lang] = translations
            print(f"Loaded {len(translations)} translations for language: {lang}")


def gettext(text: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """
    Translates a given text to the specified language.
    Falls back to the original text if no translation is found.
    """
    return TRANSLATIONS.get(lang, {}).get(text, text)


def lazy_gettext(request: Request, text: str) -> str:
    """A 'lazy' version of gettext that uses the language from the request scope."""
    lang = request.scope.get("language", DEFAULT_LANGUAGE)
    return gettext(text, lang)


# --- Bijective Base-6 Logic ---
def to_bijective_base6(n: int) -> str:
    if n <= 0:
        raise ValueError("Input must be a positive integer")
    chars = "123456"
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, 6)
        result.append(chars[remainder])
    return "".join(reversed(result))


def from_bijective_base6(s: str) -> int:
    if not s or not s.isalnum():
        raise ValueError("Invalid short code format")
    n = 0
    for char in s:
        n = n * 6 + "123456".index(char) + 1
    return n


# --- TTL Options ---
class TTL(str, Enum):
    ONE_HOUR = "1h"
    ONE_DAY = "1d"
    ONE_WEEK = "1w"
    NEVER = "never"


TTL_MAP = {
    TTL.ONE_HOUR: timedelta(hours=1),
    TTL.ONE_DAY: timedelta(days=1),
    TTL.ONE_WEEK: timedelta(weeks=1),
}


# --- Pydantic Models ---
class LinkBase(BaseModel):
    long_url: HttpUrl = Field(..., example="https://github.com/fastapi/fastapi",
                              description="The original, long URL to be shortened.")
    ttl: TTL = Field(TTL.ONE_DAY, description="Time-to-live for the link. Determines when it will expire.")

    @field_validator('long_url', mode='before')
    @classmethod
    def prepend_scheme_if_missing(cls, v: str):
        """
        Prepends 'https://' to the URL if no scheme (http:// or https://) is present.
        """
        if not isinstance(v, str):
            return v  # It's already a Pydantic object, do nothing
        if '.' not in v:
            raise ValueError("Invalid URL: must contain a domain name.")
        if not v.startswith(('http://', 'https://')):
            return 'https://' + v
        return v


class HateoasLink(BaseModel):
    """A HATEOAS-compliant link object."""
    rel: str = Field(..., description="The relationship of the link to the resource (e.g., 'self').")
    href: HttpUrl = Field(..., description="The URL of the related resource.")
    method: str = Field(..., description="The HTTP method to use for the action (e.g., 'GET', 'DELETE').")


class LinkResponse(BaseModel):
    """The response model for a successfully created or retrieved link."""
    short_url: HttpUrl = Field(..., example="https://shortlinks.art/11", description="The generated short URL.")
    long_url: HttpUrl = Field(..., example="https://github.com/fastapi/fastapi", description="The original long URL.")
    expires_at: datetime | None = Field(..., example="2023-10-27T10:00:00Z",
                                        description="The UTC timestamp when the link will expire. `null` if it never expires.")
    links: list[HateoasLink] = Field(..., description="HATEOAS links for related actions.")


class ErrorResponse(BaseModel):
    """A standardized error response model."""
    detail: str


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
        content={"detail": "An unexpected internal error occurred."},
    )


# API Router for versioning and organization
api_router = APIRouter(
    prefix="/api/v1",
    tags=["Links"],  # Group endpoints in the docs
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


templates.env.globals['gettext'] = gettext
templates.env.globals['_'] = _


def get_translator(lang: str = DEFAULT_LANGUAGE):
    """Dependency to get a translator function for the current request's language."""

    def translator(text: str, **kwargs) -> str:
        translated = gettext(text, lang)
        return translated.format(**kwargs) if kwargs else translated

    return translator


@app.get("/", include_in_schema=False)
async def redirect_to_default_lang(request: Request):
    """Redirects the root path to the default language."""
    lang = DEFAULT_LANGUAGE

    # 1. Prioritize the language cookie set by the user.
    user_lang_cookie = request.cookies.get("lang")
    if user_lang_cookie and user_lang_cookie in TRANSLATIONS:
        lang = user_lang_cookie
    else:
        # 2. Fallback to browser's Accept-Language header for a good first-time experience.
        accept_language = request.headers.get("accept-language")
        if accept_language:
            browser_lang = accept_language.split(",")[0].split("-")[0].lower()
            if browser_lang in TRANSLATIONS:
                lang = browser_lang

    return RedirectResponse(url=f"/ui/{lang}")


@app.get(
    "/ui/{lang_code:str}",
    response_class=HTMLResponse,
    summary="Serve Frontend UI",
    tags=["UI"])
async def read_root(request: Request, lang_code: str):
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    # Pass the translator function to the template context
    translator = get_translator(lang_code)
    return templates.TemplateResponse("index.html", {"request": request, "_": translator, "lang_code": lang_code})


@app.get(
    "/ui/{lang_code:str}/about",
    response_class=HTMLResponse,
    summary="Serve About Page",
    tags=["UI"]
)
async def read_about(request: Request, lang_code: str):
    """Serves the about page for a given language."""
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    translator = get_translator(lang_code)
    return templates.TemplateResponse("about.html", {"request": request, "_": translator, "lang_code": lang_code})


@app.get("/health", response_class=HTMLResponse, summary="Health Check", tags=["Monitoring"])
async def health_check(request: Request):
    """
    Performs a deep health check on the application and its dependencies,
    and renders an HTML status page.
    """
    health_status = {
        "status": "ok",
        "services": {}
    }
    status_code = 200

    # 1. Check Translation System
    if TRANSLATIONS and len(TRANSLATIONS) > 0:
        health_status["services"]["translations"] = "ok"
    else:
        health_status["services"]["translations"] = "error"
        health_status["status"] = "error"
        status_code = 503

    # 2. Check Database Connection
    try:
        with database.get_db_connection() as conn:
            conn.execute("SELECT 1")
        health_status["services"]["database_connection"] = "ok"
    except Exception:
        health_status["services"]["database_connection"] = "error"
        health_status["status"] = "error"
        status_code = 503

    context = {
        "request": request,
        "overall_status": health_status["status"],
        "services": health_status["services"],
        "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    }
    return templates.TemplateResponse("health.html", context, status_code=status_code)

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    content = f"""User-agent: *
Allow: /$
Allow: /static/
Disallow: /api
Disallow: /challenge

# Yandex-specific directives
Clean-param: ref /

# Yandex-specific directive for the main mirror
Host: https://shortlinks.art/

Sitemap: https://shortlinks.art/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    today = date.today().isoformat()
    now = datetime.now(tz=timezone.utc)
    urlset = []
    base_url = "https://shortlinks.art"

    # Generate hreflang links for a given path (e.g., "/ui/{lang}/")
    def generate_hreflang_links(path_template: str) -> str:
        links = []
        for code in TRANSLATIONS.keys():
            links.append(f'    <xhtml:link rel="alternate" hreflang="{code}" href="{base_url}{path_template.format(lang=code)}"/>')
        # Add x-default for the default language
        links.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{base_url}{path_template.format(lang=DEFAULT_LANGUAGE)}"/>')
        return "\n".join(links)

    # 1. Add an entry for each supported language homepage
    # We only need to create one entry for each "page" and list the language alternatives within it.
    
    # Homepage
    urlset.append(f"""  <url>
    <loc>{base_url}/ui/en/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
{generate_hreflang_links("/ui/{lang}/")}
  </url>""")

    # About Page
    urlset.append(f"""  <url>
    <loc>{base_url}/ui/en/about/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>yearly</changefreq>
    <priority>0.8</priority>
{generate_hreflang_links("/ui/{lang}/about/")}
  </url>""")

    # 2. Add an entry for each active short link
    def get_active_links():
        with database.get_db_connection() as conn:
            return conn.execute("SELECT id FROM links WHERE expires_at IS NULL OR expires_at > ?", (now,)).fetchall()

    active_links = await asyncio.to_thread(get_active_links)

    for link in active_links:
        short_code = to_bijective_base6(link['id'])
        urlset.append(f"""  <url>
    <loc>{base_url}/{short_code}</loc>
    <changefreq>never</changefreq>
    <priority>0.5</priority>
  </url>""")

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
{"".join(urlset)}
</urlset>
"""
    return Response(content=xml_content, media_type="application/xml")


@api_router.get("/translations/{lang_code}", include_in_schema=False)
async def get_translations(lang_code: str):
    """
    Provides a set of translated strings to the frontend JavaScript.
    """
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    translator = get_translator(lang_code)
    return {
        "expire_in_duration": translator("Your link is private and will automatically expire in {duration}."),
        "expire_never": translator("Your link is private and will never expire."),
        "copied": translator("Copied!"),
        "copy": translator("Copy"),
        "ttl_1_hour": translator("1 Hour"),
        "ttl_24_hours": translator("24 Hours"),
        "ttl_1_week": translator("1 Week"),
        "ttl_never": translator("Never"),
    }


@api_router.post(
    "/links",
    response_model=LinkResponse,
    status_code=201,
    summary="Create a new short link",
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request: Invalid input or failed bot check."},
        422: {"model": ErrorResponse, "description": "Validation Error: The request body is malformed."},
    }
)
async def create_short_link(link_data: LinkBase, request: Request):
    """
    Creates a new short link from a long URL.

    - **ID Reuse**: It will first try to reuse an expired ID to keep codes short.
    - **TTL**: Links can be set to expire after a specific duration.
    """
    
    def db_insert():
        # Calculate the expiration datetime
        if link_data.ttl == TTL.NEVER:
            expires_at = None
        else:
            expires_at = datetime.now(tz=timezone.utc) + TTL_MAP[link_data.ttl]
            
        with database.get_db_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO links (long_url, expires_at) VALUES (?, ?)",
                (str(link_data.long_url), expires_at)
            )
            new_id = cursor.lastrowid
            conn.commit()
            return new_id, expires_at

    try:
        new_id, expires_at = await asyncio.to_thread(db_insert)
        short_code = to_bijective_base6(new_id)
        short_url = f"{request.base_url}{short_code}"
        resource_location = short_url

        # Prepare the response object that matches the LinkResponse model
        response_content = {
            "short_url": str(short_url),
            "long_url": str(link_data.long_url),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "links": [
                {
                    "rel": "self",
                    "href": f"{request.base_url}api/v1/links/{short_code}",
                    "method": "GET"
                },
                {
                    "rel": "delete",
                    "href": f"{request.base_url}api/v1/links/{short_code}",
                    "method": "DELETE"
                }
            ]
        }

        # Return 201 Created with a Location header and the response body
        return JSONResponse(
            status_code=201,
            content=response_content,
            headers={"Location": resource_location}
        )
    except Exception as e:
        logger.error(f"Database insert failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create link in the database.")


@api_router.get(
    "/links/{short_code}",
    response_model=LinkResponse,
    summary="Get details for a short link",
    responses={404: {"model": ErrorResponse, "description": "Not Found: The link does not exist or has expired."}}
)
async def get_link_details(short_code: str, request: Request):
    """
    Retrieves the details of a short link, such as the original URL and its
    expiration time, without performing a redirect.
    """
    translator = get_translator()  # Defaults to 'en' for API responses
    # The ValueError from an invalid short_code is now handled by the exception handler
    url_id = from_bijective_base6(short_code)
    
    def db_select():
        with database.get_db_connection() as conn:
            return conn.execute("SELECT long_url, expires_at FROM links WHERE id = ?", (url_id,)).fetchone()
            
    record = await asyncio.to_thread(db_select)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Check for expiration but do not delete it here (let the background task handle it)
    expires_at = record["expires_at"]
    # Make the retrieved datetime object timezone-aware before comparison
    if expires_at:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and datetime.now(tz=timezone.utc) > expires_at:
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    return {
        "short_url": f"https://shortlinks.art/{short_code}",  # Use canonical URL
        "long_url": record["long_url"],
        "expires_at": record["expires_at"],
        "links": [
            {
                "rel": "self",
                "href": str(request.url),
                "method": "GET"
            },
            {
                "rel": "delete",
                "href": str(request.url),
                "method": "DELETE"
            }
        ]
    }


@api_router.delete(
    "/links/{short_code}",
    status_code=204,
    summary="Delete a short link",
    responses={404: {"model": ErrorResponse, "description": "Not Found: The link does not exist."}}
)
async def delete_short_link(short_code: str):
    """
    Permanently deletes a short link.
    """
    url_id = from_bijective_base6(short_code)

    def db_delete():
        return database.delete_link_by_id(url_id)

    rows_deleted = await asyncio.to_thread(db_delete)

    if rows_deleted == 0:
        translator = get_translator()
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Return a 204 No Content response, which is standard for successful deletions.
    return Response(status_code=204)


app.include_router(api_router)


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
    url_id = from_bijective_base6(short_code)
    
    def db_select():
        with database.get_db_connection() as conn:
            return conn.execute("SELECT long_url, expires_at FROM links WHERE id = ?", (url_id,)).fetchone()
            
    record = await asyncio.to_thread(db_select)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Check if the link has an expiration date and if it has passed
    expires_at = record['expires_at']
    # Make the retrieved datetime object timezone-aware before comparison
    if expires_at:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at and now > expires_at:
        # The background task will eventually remove it. For now, just deny access.
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    return RedirectResponse(url=record["long_url"])


# This block is useful for local development but not strictly needed for Render deployment
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)
