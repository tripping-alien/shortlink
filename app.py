from fastapi import FastAPI, HTTPException, Request, APIRouter
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel, HttpUrl, field_validator, Field
from datetime import datetime, timedelta, date, timezone
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import database  # Import the new database module
import uvicorn
import asyncio
import os
import random
from enum import Enum
import re

from mymath import to_bijective_base6, from_bijective_base6
from translations import gettext, load_translations
from config import settings, TRANSLATIONS, DEFAULT_LANGUAGE


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


class Challenge(BaseModel):
    num1: int = Field(..., example=5, description="The first number in the bot-check challenge.")
    num2: int = Field(..., example=8, description="The second number in the bot-check challenge.")
    challenge_answer: int = Field(..., example=13, description="The user's answer to the `num1 + num2` challenge.")


class LinkCreate(LinkBase):
    """The request body for creating a new short link."""
    challenge: Challenge = Field(..., description="A simple challenge-response object to prevent spam.")

    @field_validator('long_url', mode='before')
    @classmethod
    def prepend_scheme_if_missing(cls, v: str):
        """
        Prepends 'https://' to the URL if no scheme (http:// or https://) is present.
        """
        if not re.match(r'^[a-zA-Z]+://', v):
            return 'https://' + v
        return v

    # Keep the validator on the combined model
    @field_validator('long_url')
    @classmethod
    def check_domain(cls, v: HttpUrl):
        """
        Ensures the URL is not pointing to a local or private address.
        """
        # Pydantic's HttpUrl already does a great job, but we can add custom logic.
        if v.host in ('localhost', '127.0.0.1'):
            raise ValueError('Shortening localhost URLs is not permitted.')
        if not v.host or '.' not in v.host:
            raise ValueError('The provided URL must have a valid domain name.')
        return v


class LinkResponse(BaseModel):
    """The response model for a successfully created or retrieved link."""
    short_url: HttpUrl = Field(..., example="https://shortlinks.art/11", description="The generated short URL.")
    long_url: HttpUrl = Field(..., example="https://github.com/fastapi/fastapi", description="The original long URL.")
    expires_at: datetime | None = Field(..., example="2023-10-27T10:00:00Z",
                                        description="The UTC timestamp when the link will expire. `null` if it never expires.")


class ErrorResponse(BaseModel):
    """A standardized error response model."""
    detail: str


# --- Background Cleanup Task ---
async def cleanup_expired_links():
    """Periodically scans the database and removes expired links."""
    now = datetime.now(timezone.utc)
    with database.get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM links WHERE expires_at IS NOT NULL AND expires_at < ?", (now,))
        conn.commit()
        deleted_count = cursor.rowcount
    if deleted_count > 0:
        print(f"Cleaned up {deleted_count} expired links.")


async def run_cleanup_task():
    """Runs the cleanup task in a loop."""
    while True:
        await cleanup_expired_links()
        await asyncio.sleep(settings.cleanup_interval_seconds)


# --- Lifespan Events for Startup and Shutdown ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # The lifespan now only manages long-running background tasks.
    print("Lifespan: Starting background cleanup task...")
    cleanup_task = asyncio.create_task(run_cleanup_task())
    yield
    # Clean up the background task when the application shuts down
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
        "url": "https://github.com/tripping-alien/shortlink",
        "email": "your-email@example.com",
    },
)

# API Router for versioning and organization
api_router = APIRouter(
    prefix="/api",
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


# --- Static Route Definitions ---

@app.get("/", include_in_schema=False)
async def redirect_to_default_lang(request: Request):
    """Redirects the root path to the default language."""
    accept_language = request.headers.get("accept-language")
    lang = DEFAULT_LANGUAGE
    if accept_language:
        browser_lang = accept_language.split(",")[0].split("-")[0].lower()
        if browser_lang in TRANSLATIONS:
            lang = browser_lang
    return RedirectResponse(url=f"/{lang}")


@app.get("/health", summary="Health Check", tags=["Monitoring"])
async def health_check():
    """A simple health check endpoint that returns a 200 OK status."""
    return Response(status_code=200)


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
    now = datetime.now(timezone.utc)
    urlset = []

    if not TRANSLATIONS:
        load_translations()

    for lang_code in TRANSLATIONS.keys():
        urlset.append(f"""  <url>
    <loc>https://shortlinks.art/{lang_code}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
  </url>""")
        urlset.append(f"""  <url>
    <loc>https://shortlinks.art/{lang_code}/about/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>yearly</changefreq>
    <priority>0.8</priority>
  </url>""")

    with database.get_db_connection() as conn:
        active_links = conn.execute("SELECT id FROM links WHERE expires_at IS NULL OR expires_at > ?",
                                    (now,)).fetchall()

    for link in active_links:
        short_code = to_bijective_base6(link['id'])
        urlset.append(f"""  <url>
    <loc>https://shortlinks.art/{short_code}</loc>
    <changefreq>never</changefreq>
    <priority>0.5</priority>
  </url>""")

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{"".join(urlset)}
</urlset>
"""
    return Response(content=xml_content, media_type="application/xml")


# --- API Route Definitions ---

@app.get("/challenge", summary="Get a new bot verification challenge", tags=["Utilities"])
async def get_challenge(request: Request):
    """Provides a simple arithmetic challenge to be solved by the client."""
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE))
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    return {"num1": num1, "num2": num2, "question": translator("What is {num1} + {num2}?", num1=num1, num2=num2)}


@api_router.get("/translations/{lang_code}", include_in_schema=False)
async def get_translations(lang_code: str):
    """Provides a set of translated strings to the frontend JavaScript."""
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
async def create_short_link(link_data: LinkCreate, request: Request):
    """Creates a new short link from a long URL."""
    lang = request.headers.get("Referer", f"/{DEFAULT_LANGUAGE}").split('/')[-2]
    translator = get_translator(lang if lang in TRANSLATIONS else DEFAULT_LANGUAGE)
    if link_data.challenge.challenge_answer != (link_data.challenge.num1 + link_data.challenge.num2):
        raise HTTPException(status_code=400, detail=translator("Bot verification failed. Incorrect answer."))

    new_id = None
    try:
        def db_insert():
            with database.get_db_connection() as conn:
                expires_at = None
                if link_data.ttl != TTL.NEVER:
                    expires_at = datetime.now(timezone.utc) + TTL_MAP[link_data.ttl]
                cursor = conn.execute(
                    "INSERT INTO links (long_url, expires_at) VALUES (?, ?)",
                    (str(link_data.long_url), expires_at)
                )
                new_id = cursor.lastrowid
                conn.commit()
                return new_id, expires_at

        new_id, expires_at = await asyncio.to_thread(db_insert)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {e}")

    if not new_id:
        raise HTTPException(status_code=500, detail="Failed to create link ID in database.")

    short_code = to_bijective_base6(new_id)
    short_url = f"{request.base_url}{short_code}"
    resource_location = short_url

    response_content = {
        "short_url": str(short_url),
        "long_url": str(link_data.long_url),
        "expires_at": expires_at.isoformat() if expires_at else None
    }
    return JSONResponse(status_code=201, content=response_content, headers={"Location": resource_location})


@api_router.get(
    "/links/{short_code}",
    response_model=LinkResponse,
    summary="Get details for a short link",
    responses={404: {"model": ErrorResponse, "description": "Not Found: The link does not exist or has expired."}}
)
async def get_link_details(short_code: str, request: Request):
    """Retrieves the details of a short link."""
    now = datetime.now(timezone.utc)
    translator = get_translator()
    try:
        url_id = from_bijective_base6(short_code)
    except ValueError:
        raise HTTPException(status_code=404, detail=translator("Invalid short code format"))

    def db_select():
        with database.get_db_connection() as conn:
            return conn.execute("SELECT long_url, expires_at FROM links WHERE id = ?", (url_id,)).fetchone()

    record = await asyncio.to_thread(db_select)

    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    expires_at = record['expires_at']
    if expires_at and now > expires_at:
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    return {
        "short_url": f"https://shortlinks.art/{short_code}",
        "long_url": record['long_url'],
        "expires_at": expires_at
    }


app.include_router(api_router)


# --- Final Initialization and Dynamic Route Registration ---

@app.on_event("startup")
def on_startup():
    """
    This function runs once when the application starts up, before serving requests.
    It's the canonical place for initialization logic that affects routing.
    """
    database.init_db()
    load_translations()

    # Create a regex to match only the supported language codes.
    language_codes_regex = "|".join(TRANSLATIONS.keys())
    if not language_codes_regex:
        language_codes_regex = DEFAULT_LANGUAGE

    # Define route handlers locally or import them
    async def read_root(request: Request, lang_code: str):
        if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
            raise HTTPException(status_code=404, detail="Language not supported")
        translator = get_translator(lang_code)
        return templates.TemplateResponse("index.html", {"request": request, "_": translator, "lang_code": lang_code})

    async def read_about(request: Request, lang_code: str):
        if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
            raise HTTPException(status_code=404, detail="Language not supported")
        translator = get_translator(lang_code)
        return templates.TemplateResponse("about.html", {"request": request, "_": translator, "lang_code": lang_code})

    async def redirect_to_long_url(short_code: str, request: Request):
        """Redirects to the original URL if the short link exists and has not expired."""
        now = datetime.now(timezone.utc)
        translator = get_translator()
        try:
            url_id = from_bijective_base6(short_code)

            def db_select():
                with database.get_db_connection() as conn:
                    return conn.execute("SELECT long_url, expires_at FROM links WHERE id = ?", (url_id,)).fetchone()

            record = await asyncio.to_thread(db_select)
            if not record:
                raise HTTPException(status_code=404, detail=translator("Short link not found"))
            expires_at = record['expires_at']
            if expires_at and now > expires_at:
                raise HTTPException(status_code=404, detail=translator("Short link has expired"))
            return RedirectResponse(url=record['long_url'])
        except ValueError:
            raise HTTPException(status_code=404, detail=translator("Invalid short code format"))

    # Programmatically add routes in the correct order of specificity
    app.add_api_route(f"/{'{lang_code}'}:str:regex({language_codes_regex})", read_root, methods=["GET"],
                      response_class=HTMLResponse, tags=["UI"])
    app.add_api_route(f"/{'{lang_code}'}:str:regex({language_codes_regex})/about", read_about, methods=["GET"],
                      response_class=HTMLResponse, tags=["UI"])

    # Add the catch-all redirect route LAST
    app.add_api_route("/{short_code}", redirect_to_long_url, methods=["GET"], summary="Redirect to the original URL",
                      tags=["Redirect"])


# This block is useful for local development but not strictly needed for Render deployment
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)