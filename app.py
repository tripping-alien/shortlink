from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime, timedelta
import uvicorn

# --- Configuration ---
LINK_TTL_SECONDS = 86400  # Links will expire after 24 hours (24 * 60 * 60)

# --- In-Memory "Database" ---
# In a real application, you would replace this with a proper database
# like SQLite, PostgreSQL, or a NoSQL database like Redis.
url_database = {}
id_counter = 0
freed_ids = []  # A pool of expired/reusable IDs


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


# --- API Models ---
class URLItem(BaseModel):
    long_url: str


# --- FastAPI Application ---
app = FastAPI(
    title="Bijective-Shorty API",
    description="A simple URL shortener using bijective base-6 encoding with TTL and ID reuse."
)

# CORS Middleware to allow the frontend to communicate with the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this to your frontend's domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", summary="API Root")
async def read_root():
    return {"message": "Welcome to Bijective-Shorty API. Use /shorten to create links or /{short_code} to redirect."}


@app.post("/shorten", summary="Create a new short link")
async def create_short_link(url_item: URLItem, request: Request):
    """
    Creates a new short link. It will first try to reuse an expired ID.
    If no IDs are available for reuse, it will create a new one.
    """
    global id_counter, url_database, freed_ids

    if freed_ids:
        # Reuse an old ID if available
        new_id = freed_ids.pop(0)
    else:
        # Otherwise, create a new one
        id_counter += 1
        new_id = id_counter

    url_database[new_id] = {
        "long_url": url_item.long_url,
        "created_at": datetime.utcnow()
    }

    short_code = to_bijective_base6(new_id)
    short_url = f"{request.base_url}{short_code}"
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

        # Check if the link has expired
        if datetime.utcnow() > record["created_at"] + timedelta(seconds=LINK_TTL_SECONDS):
            # Clean up the expired link
            del url_database[url_id]
            freed_ids.append(url_id)
            raise HTTPException(status_code=404, detail="Short link has expired")

        return RedirectResponse(url=record["long_url"])

    except ValueError:
        raise HTTPException(status_code=404, detail="Invalid short code format")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)