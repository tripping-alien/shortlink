from fastapi import FastAPI, HTTPException, Request, APIRouter
from fastapi.responses import RedirectResponse, HTMLResponse, Response, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic_settings import BaseSettings
from contextlib import asynccontextmanager
from pydantic import BaseModel, HttpUrl, field_validator, Field
from datetime import datetime, timedelta, date
from fastapi.staticfiles import StaticFiles 
from fastapi.templating import Jinja2Templates
import uvicorn
import json
import asyncio
import os
import random
from enum import Enum
import re

# --- Configuration Management ---
class Settings(BaseSettings):
    """Manages application configuration using environment variables."""
    # Use Render's persistent disk path. Default to local file for development.
    db_file: str = os.path.join(os.environ.get('RENDER_DISK_PATH', '.'), 'db.json')
    # In production, set this to your frontend's domain: "https://your-frontend.com"
    # The default ["*"] is insecure and for development only.
    cors_origins: list[str] = ["*"]
    cleanup_interval_seconds: int = 3600 # Run cleanup task every hour

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

# --- In-Memory "Database" ---
# In a real application, you would replace this with a proper database
# like SQLite, PostgreSQL, or a NoSQL database like Redis.
url_database = {}
id_counter = 0
freed_ids = []  # A pool of expired/reusable IDs
db_lock = asyncio.Lock() # To prevent race conditions during state modification

# --- Persistence Logic ---
def save_state():
    """Saves the current state to a JSON file."""
    # Convert datetime objects to strings for JSON serialization
    serializable_db = {
        url_id: {
            "long_url": str(data["long_url"]),  # Convert HttpUrl to string before saving
            "expires_at": data["expires_at"].isoformat() if data["expires_at"] else None
        }
        for url_id, data in url_database.items()
    }
    state = {
        "url_database": serializable_db,
        "id_counter": id_counter,
        "freed_ids": freed_ids
    }
    # This function is now synchronous, so we don't need async file I/O
    with open(settings.db_file, "w") as f:
        json.dump(state, f, indent=4)

def load_state():
    """Loads the state from a JSON file on startup."""
    global url_database, id_counter, freed_ids
    try:
        with open(settings.db_file, "r") as f:
            state = json.load(f)
            # Convert string timestamps back to datetime objects
            url_database = {
                int(url_id): {
                    "long_url": data["long_url"],
                    "expires_at": datetime.fromisoformat(data["expires_at"]) if data["expires_at"] else None
                }
                for url_id, data in state.get("url_database", {}).items()
            }
            id_counter = state.get("id_counter", 0)
            freed_ids = state.get("freed_ids", [])
    except (FileNotFoundError, json.JSONDecodeError):
        # If the file doesn't exist or is empty, start with a fresh state
        pass


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
    long_url: HttpUrl = Field(..., example="https://github.com/fastapi/fastapi", description="The original, long URL to be shortened.")
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
    expires_at: datetime | None = Field(..., example="2023-10-27T10:00:00Z", description="The UTC timestamp when the link will expire. `null` if it never expires.")

class ErrorResponse(BaseModel):
    """A standardized error response model."""
    detail: str


# --- Background Cleanup Task ---
async def cleanup_expired_links():
    """Periodically scans the database and removes expired links."""
    global url_database, freed_ids
    now = datetime.utcnow()
    expired_ids = []

    # It's safe to iterate without a lock because we are not modifying during iteration
    for url_id, record in url_database.items():
        # Skip links that never expire
        if record["expires_at"] is None:
            continue
        is_expired = now > record["expires_at"]
        is_invalid_date = record["expires_at"] < now - timedelta(weeks=52) # Heuristic for invalid past dates
        if is_expired or is_invalid_date:
            expired_ids.append(url_id)

    if expired_ids:
        async with db_lock:
            for url_id in expired_ids:
                # Check if the record still exists before deleting
                if url_id in url_database:
                    del url_database[url_id]
                    freed_ids.append(url_id)
            save_state()
        print(f"Cleaned up {len(expired_ids)} expired or invalid links.")

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
    print("Loading application state...")
    load_state()
    print("Starting background cleanup task...")
    cleanup_task = asyncio.create_task(run_cleanup_task())
    yield
    # Save the state to disk when the application shuts down
    print("Saving application state...")
    save_state()
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
        "url": "https://github.com/your-repo", # Replace with your project's repo
        "email": "your-email@example.com",
    },
)

# API Router for versioning and organization
api_router = APIRouter(
    prefix="/api",
    tags=["Links"], # Group endpoints in the docs
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
    # Detect browser language for a better first-time user experience
    accept_language = request.headers.get("accept-language")
    lang = DEFAULT_LANGUAGE
    if accept_language:
        browser_lang = accept_language.split(",")[0].split("-")[0].lower()
        if browser_lang in TRANSLATIONS:
            lang = browser_lang
    return RedirectResponse(url=f"/{lang}")

@app.get(
    "/{lang_code:str}",
    response_class=HTMLResponse,
    summary="Serve Frontend UI",
    tags=["UI"])
async def read_root(request: Request, lang_code: str):
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    # Pass the translator function to the template context
    translator = get_translator(lang_code)
    return templates.TemplateResponse("index.html", {"request": request, "_": translator, "lang_code": lang_code})

@app.get("/health", summary="Health Check", tags=["Monitoring"])
async def health_check():
    """
    A simple health check endpoint that returns a 200 OK status.
    Useful for uptime monitoring services.
    """
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
    now = datetime.utcnow()
    urlset = []

    # 1. Add an entry for each supported language homepage
    for lang_code in TRANSLATIONS.keys():
        urlset.append(f"""  <url>
    <loc>https://shortlinks.art/{lang_code}/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
  </url>""")

    # 2. Add an entry for each active short link
    # Create a copy to prevent issues with concurrent modification
    db_copy = url_database.copy()
    for url_id, record in db_copy.items():
        # Skip expired links
        if record["expires_at"] and now > record["expires_at"]:
            continue
        
        short_code = to_bijective_base6(url_id)
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


@app.get("/challenge", summary="Get a new bot verification challenge", tags=["Utilities"])
async def get_challenge(request: Request):
    """
    Provides a simple arithmetic challenge to be solved by the client.
    This is a stateless mechanism to deter simple bots from spamming the link creation endpoint.
    """
    translator = get_translator(request.scope.get("language", DEFAULT_LANGUAGE)) # Fallback for direct API calls
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    return {"num1": num1, "num2": num2, "question": translator("What is {num1} + {num2}?", num1=num1, num2=num2)}


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
async def create_short_link(link_data: LinkCreate, request: Request):
    """
    Creates a new short link from a long URL.

    - **ID Reuse**: It will first try to reuse an expired ID to keep codes short.
    - **Bot Protection**: Requires a simple arithmetic challenge to be solved.
    - **TTL**: Links can be set to expire after a specific duration.
    """
    # Determine language from referrer or default
    lang = request.headers.get("Referer", f"/{DEFAULT_LANGUAGE}").split('/')[-2]
    translator = get_translator(lang if lang in TRANSLATIONS else DEFAULT_LANGUAGE)
    # Stateless bot verification
    if link_data.challenge.challenge_answer != (link_data.challenge.num1 + link_data.challenge.num2):
        raise HTTPException(status_code=400, detail=translator("Bot verification failed. Incorrect answer."))

    async with db_lock:
        global id_counter, url_database, freed_ids

        if freed_ids:
            # Reuse an old ID if available
            new_id = freed_ids.pop(0)
        else:
            # Otherwise, create a new one
            id_counter += 1
            new_id = id_counter
        
        # Calculate the expiration datetime
        if link_data.ttl == TTL.NEVER:
            expires_at = None
        else:
            expires_at = datetime.utcnow() + TTL_MAP[link_data.ttl]

        url_database[new_id] = {
            "long_url": str(link_data.long_url), # Store as string
            "expires_at": expires_at
        }

        short_code = to_bijective_base6(new_id)
        # Construct the URL for the redirect, not the API path
        short_url = f"{request.base_url}{short_code}"
        resource_location = short_url

        # Save the new state to disk
        save_state()

        # Prepare the response object that matches the LinkResponse model
        response_content = {
            "short_url": short_url,
            "long_url": link_data.long_url,
            "expires_at": expires_at
        }

        # Return 201 Created with a Location header and the response body
        return JSONResponse(
            status_code=201,
            content=response_content,
            headers={"Location": resource_location}
        )


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
    translator = get_translator() # Defaults to 'en' for API responses
    try:
        url_id = from_bijective_base6(short_code)
    except ValueError:
        raise HTTPException(status_code=404, detail=translator("Invalid short code format"))

    record = url_database.get(url_id)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Check for expiration but do not delete it here (let the background task handle it)
    if record["expires_at"] and datetime.utcnow() > record["expires_at"]:
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    return {
        "short_url": f"https://shortlinks.art/{short_code}", # Use canonical URL
        "long_url": record["long_url"],
        "expires_at": record["expires_at"]
    }


app.include_router(api_router)


@app.get("/{short_code}", summary="Redirect to the original URL", tags=["Redirect"])
async def redirect_to_long_url(short_code: str, request: Request):
    """
    Redirects to the original URL if the short link exists and has not expired.
    If the link is expired, it is cleaned up and its ID is made available for reuse.
    This is the primary function of the service.
    """
    translator = get_translator() # Defaults to 'en' for error messages on redirect
    try:
        url_id = from_bijective_base6(short_code)

        record = url_database.get(url_id)
        if not record:
            raise HTTPException(status_code=404, detail=translator("Short link not found"))

        # Check if the link has an expiration date and if it has passed
        if record["expires_at"] and datetime.utcnow() > record["expires_at"]:
            # Clean up the expired link (passive check)
            async with db_lock:
                if url_id in url_database: # Check again in case the background task just removed it
                    del url_database[url_id]
                    freed_ids.append(url_id)
                    save_state()
            raise HTTPException(status_code=404, detail=translator("Short link has expired"))

        return RedirectResponse(url=record["long_url"])

    except ValueError:
        raise HTTPException(status_code=404, detail=translator("Invalid short code format"))


# This block is useful for local development but not strictly needed for Render deployment
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)