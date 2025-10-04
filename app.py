from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse, HTMLResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pydantic import BaseModel, HttpUrl, field_validator
from datetime import datetime, timedelta, date
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn
import json
import asyncio
import os
import random
from enum import Enum

# --- Configuration ---
LINK_TTL_SECONDS = 86400  # Links will expire after 24 hours (24 * 60 * 60)
# Use Render's persistent disk path. Default to local file for development.
DB_FILE = os.path.join(os.environ.get('RENDER_DISK_PATH', '.'), 'db.json')

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
    with open(DB_FILE, "w") as f:
        json.dump(state, f, indent=4)

def load_state():
    """Loads the state from a JSON file on startup."""
    global url_database, id_counter, freed_ids
    try:
        with open(DB_FILE, "r") as f:
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

# --- API Models ---
class URLItem(BaseModel):
    long_url: HttpUrl
    challenge_answer: int
    num1: int
    num2: int
    ttl: TTL = TTL.ONE_DAY # Default to 1 day

    @field_validator('long_url')
    @classmethod
    def check_domain(cls, v: HttpUrl):
        """
        Ensures the URL is not pointing to a local or private address.
        """
        if v.host in ('localhost', '127.0.0.1'):
            raise ValueError('Shortening localhost URLs is not permitted.')
        if not v.host or '.' not in v.host:
            raise ValueError('The provided URL must have a valid domain name.')
        return v


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
        await asyncio.sleep(3600)  # Run every hour

# --- Lifespan Events for Startup and Shutdown ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Load the state from disk when the application starts
    load_state()
    cleanup_task = asyncio.create_task(run_cleanup_task())
    yield
    # Save the state to disk when the application shuts down
    save_state()
    cleanup_task.cancel()

# --- FastAPI Application ---
app = FastAPI(
    title="Bijective-Shorty API",
    description="A simple URL shortener using bijective base-6 encoding with TTL and ID reuse.",
    lifespan=lifespan
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# CORS Middleware to allow the frontend to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", response_class=HTMLResponse, summary="Serve Frontend UI")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health", summary="Health Check")
async def health_check():
    return Response(status_code=200)


@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    content = f"""User-agent: *
Allow: /
Disallow: /shorten
Disallow: /challenge

Sitemap: https://shortlinks.art/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@app.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    today = date.today().isoformat()
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://shortlinks.art/</loc>
    <lastmod>{today}</lastmod>
  </url>
</urlset>"""
    return Response(content=xml_content, media_type="application/xml")


@app.get("/challenge", summary="Get a new bot verification challenge")
async def get_challenge():
    num1 = random.randint(1, 10)
    num2 = random.randint(1, 10)
    return {"num1": num1, "num2": num2, "question": f"What is {num1} + {num2}?"}


@app.post("/shorten", summary="Create a new short link")
async def create_short_link(url_item: URLItem, request: Request):
    """
    Creates a new short link. It will first try to reuse an expired ID.
    If no IDs are available for reuse, it will create a new one.
    """
    # Stateless bot verification
    if url_item.challenge_answer != (url_item.num1 + url_item.num2):
        raise HTTPException(status_code=400, detail="Bot verification failed. Incorrect answer.")

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
        if url_item.ttl == TTL.NEVER:
            expires_at = None
        else:
            expires_at = datetime.utcnow() + TTL_MAP[url_item.ttl]

        url_database[new_id] = {
            "long_url": url_item.long_url,
            "expires_at": expires_at
        }

        short_code = to_bijective_base6(new_id)
        short_url = f"{request.base_url}{short_code}"

        # Save the new state to disk
        save_state()
        return {"short_url": short_url, "long_url": url_item.long_url}


@app.get("/{short_code}", summary="Redirect to the original URL")
async def redirect_to_long_url(short_code: str):
    """
    Redirects to the original URL if the short link exists and has not expired.
    If the link is expired, it is cleaned up and its ID is made available for reuse.
    """
    try:
        url_id = from_bijective_base6(short_code)

        record = url_database.get(url_id)
        if not record:
            raise HTTPException(status_code=404, detail="Short link not found")

        # Check if the link has an expiration date and if it has passed
        if record["expires_at"] and datetime.utcnow() > record["expires_at"]:
            # Clean up the expired link (passive check)
            async with db_lock:
                if url_id in url_database: # Check again in case the background task just removed it
                    del url_database[url_id]
                    freed_ids.append(url_id)
                    save_state()
            raise HTTPException(status_code=404, detail="Short link has expired")

        return RedirectResponse(url=record["long_url"])

    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid short code format")


# This block is useful for local development but not strictly needed for Render deployment
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run("app:app", host="0.0.0.0", port=port, reload=True)