import os
import secrets
import html
import string
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

# --- NEW IMPORTS ---
import httpx              # For async HTTP requests
from bs4 import BeautifulSoup # For HTML parsing
from urllib.parse import urljoin, urlparse # For fixing relative URLs
# --- END NEW IMPORTS ---

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

# ---------------- CONFIG ----------------
BASE_URL = os.environ.get("BASE_URL", "https://shortlinks.art")
SHORT_CODE_LENGTH = 6
MAX_ID_RETRIES = 10

TTL_MAP = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

# ---------------- FIREBASE ----------------
db: firestore.Client = None
APP_INSTANCE = None

import threading
import time

def start_cleanup_thread():
    thread = threading.Thread(target=cleanup_worker, daemon=True)
    thread.start()
    print("[CLEANUP] Background cleanup worker started.")

def cleanup_worker():
    while True:
        try:
            deleted = cleanup_expired_links()
            print(f"[CLEANUP] Deleted {deleted} expired links.")
        except Exception as e:
            print(f"[CLEANUP ERROR] {e}")
        time.sleep(1800)  # 30 minutes

def cleanup_expired_links():
    db = init_firebase()
    collection = db.collection("links")
    now = datetime.now(timezone.utc)

    expired_docs = (
        collection
        .where("expires_at", "<", now)
        .limit(100)
        .stream()
    )

    batch = db.batch()
    count = 0

    for doc in expired_docs:
        batch.delete(doc.reference)
        count += 1

    if count > 0:
        batch.commit()

    return count

def init_firebase():
    global db, APP_INSTANCE
    if db:
        return db
    firebase_config_str = os.environ.get("FIREBASE_CONFIG")
    cred = None
    if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
        cred = credentials.ApplicationDefault()
    elif firebase_config_str:
        import tempfile
        temp_file = tempfile.NamedTemporaryFile(mode='w', delete=False)
        temp_file.write(firebase_config_str)
        temp_file.close()
        cred = credentials.Certificate(temp_file.name)
        os.remove(temp_file.name)
    if cred is None:
        raise RuntimeError("Firebase config missing.")
    try:
        APP_INSTANCE = get_app()
    except ValueError:
        APP_INSTANCE = firebase_admin.initialize_app(cred)
    db = firestore.client(app=APP_INSTANCE)
    return db

# ---------------- HELPERS ----------------
def _generate_short_code(length=SHORT_CODE_LENGTH) -> str:
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_unique_short_code() -> str:
    collection = init_firebase().collection("links")
    for _ in range(MAX_ID_RETRIES):
        code = _generate_short_code()
        doc = collection.document(code).get()
        if not doc.exists:
            return code
    raise RuntimeError("Could not generate unique short code.")

def calculate_expiration(ttl: str) -> Optional[datetime]:
    delta = TTL_MAP.get(ttl, TTL_MAP["24h"])
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta

def create_link_in_db(long_url: str, ttl: str = "24h", custom_code: Optional[str] = None) -> Dict[str, Any]:
    collection = init_firebase().collection("links")
    if custom_code:
        if not custom_code.isalnum() or len(custom_code) > 20:
            raise ValueError("Custom code must be alphanumeric and <=20 chars")
        doc = collection.document(custom_code).get()
        if doc.exists:
            raise ValueError("Custom code already exists")
        code = custom_code
    else:
        code = generate_unique_short_code()

    expires_at = calculate_expiration(ttl)
    deletion_token = secrets.token_urlsafe(32)
    data = {
        "long_url": long_url,
        "deletion_token": deletion_token,
        "created_at": datetime.now(timezone.utc)
    }
    if expires_at:
        data["expires_at"] = expires_at

    collection.document(code).set(data)
    return {**data, "short_code": code, "short_url": f"{BASE_URL}/preview/{code}"}

def get_link(code: str) -> Optional[Dict[str, Any]]:
    collection = init_firebase().collection("links")
    doc = collection.document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

# --- NEW HELPER FUNCTION ---
async def fetch_metadata(url: str) -> dict:
    """
    Fetches metadata (title, description, image) from a given URL.
    """
    headers = {
        # Pretend to be a browser to avoid getting blocked
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    meta = {
        "title": None,
        "description": None,
        "image": None,
        "favicon": None
    }

    try:
        async with httpx.AsyncClient() as client:
            # Follow redirects, set a 5-second timeout
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=5.0)
            response.raise_for_status() # Raise exception for 4xx/5xx errors
            
            # Use the final URL after redirects as the base for relative URLs
            final_url = str(response.url)
            
            soup = BeautifulSoup(response.text, "lxml")

            # 1. Get Title
            if og_title := soup.find("meta", property="og:title"):
                meta["title"] = og_title.get("content")
            elif title := soup.find("title"):
                meta["title"] = title.string

            # 2. Get Description
            if og_desc := soup.find("meta", property="og:description"):
                meta["description"] = og_desc.get("content")
            elif desc := soup.find("meta", name="description"):
                meta["description"] = desc.get("content")

            # 3. Get Image
            if og_image := soup.find("meta", property="og:image"):
                # Make relative image URLs absolute
                meta["image"] = urljoin(final_url, og_image.get("content"))

            # 4. Get Favicon
            if favicon := soup.find("link", rel="icon") or soup.find("link", rel="shortcut icon"):
                # Make relative favicon URLs absolute
                meta["favicon"] = urljoin(final_url, favicon.get("href"))
            else:
                # Fallback: try to guess /favicon.ico
                parsed_url = urlparse(final_url)
                meta["favicon"] = f"{parsed_url.scheme}://{parsed_url.netloc}/favicon.ico"

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error fetching metadata for {url}: {e}")
        # If fetching fails, we just return empty meta; the page will still load
    except Exception as e:
        print(f"Error parsing HTML for {url}: {e}")

    return meta
# --- END NEW HELPER FUNCTION ---


# ---------------- APP ----------------
app = FastAPI(title="Shortlinks.art URL Shortener")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- ROUTES ----------------
# Google AdSense Publisher ID
ADSENSE_CLIENT_ID = "pub-6170587092427912"
ADSENSE_SCRIPT = f"""
    <script async src="https://pagead2.googlesyndication.com/pagead/js/adsbygoogle.js?client={ADSENSE_CLIENT_ID}"
     crossorigin="anonymous"></script>
"""

@app.get("/health")
async def health():
    try:
        init_firebase()
        return {"status": "ok", "database": "initialized"}
    except Exception as e:
        return {"status": "error", "database": str(e)}

@app.post("/api/v1/links")
async def api_create_link(payload: Dict[str, Any]):
    long_url = payload.get("long_url")
    ttl = payload.get("ttl", "24h")
    custom_code = payload.get("custom_code")
    
    if not long_url:
        raise HTTPException(status_code=400, detail="Missing long_url")

    # FIX 1: Normalize the URL before saving to the database
    # Add https:// if no scheme (http://, https://) is present
    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url

    try:
        link = create_link_in_db(long_url, ttl, custom_code)
        return {"short_url": link["short_url"]}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/", response_class=HTMLResponse)
async def index():
    # ... (This route is unchanged, code omitted for brevity) ...
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">

    <title>Shortlinks.art - Fast & Simple URL Shortener</title>
    <meta name="description" content="A fast, free, and simple URL shortener with link previews and custom expiration times.">
    <meta name="keywords" content="url shortener, shortlinks, link shortener, custom url, short url, free url shortener, shortlinks.art, shorten link">
    <link rel="canonical" href="https://shortlinks.art/" />
    <meta name="robots" content="index, follow">
    
    <meta name="google-site-verification" content="YOUR_GOOGLE_CODE_HERE" />
    <meta name="msvalidate.01" content="YOUR_BING_CODE_HERE" />
    <meta name="yandex-verification" content="YOUR_YANDEX_CODE_HERE" />

    <meta property="og:type" content="website">
    <meta property="og:url" content="https://shortlinks.art/">
    <meta property="og:title" content="Shortlinks.art - Fast & Simple URL Shortener">
    <meta property="og:description" content="A fast, free, and simple URL shortener with link previews and custom expiration times.">
    <meta property="og:image" content="https://shortlinks.art/assets/social-preview.jpg"> 

    <meta property="twitter:card" content="summary_large_image">
    <meta property="twitter:url" content="https://shortlinks.art/">
    <meta property="twitter:title" content="Shortlinks.art - Fast & Simple URL Shortener">
    <meta property="twitter:description" content="A fast, free, and simple URL shortener with link previews and custom expiration times.">
    <meta property="twitter:image" content="https://shortlinks.art/assets/social-preview.jpg">

    {ADSENSE_SCRIPT} 

    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;700&display=swap" rel="stylesheet">

    <style>
        :root {{
            --primary-color: #4f46e5;
            --primary-hover: #6366f1;
            --text-primary: #111827;
            --text-secondary: #6b7280;
            --bg-light: #f3f4f6;
            --bg-white: #ffffff;
            --border-color: #d1d5db;
        }}

        body {{
            /* NEW: Using Inter font */
            font-family: 'Inter', Arial, sans-serif;
            margin: 0;
            background: var(--bg-light);
            color: var(--text-primary);
            display: flex;
            justify-content: center;
            align-items: center;
            min-height: 100vh;
            padding: 1rem;
            -webkit-font-smoothing: antialiased;
            -moz-osx-font-smoothing: grayscale;
        }}

        .container {{
            background: var(--bg-white);
            padding: 2rem 2.5rem; /* More horizontal padding */
            border-radius: 12px;
            box-shadow: 0 10px 25px -5px rgba(0,0,0,0.07), 0 4px 6px -2px rgba(0,0,0,0.05);
            width: 100%;
            max-width: 480px;
            text-align: center;
        }}

        /* NEW: Branded H1 */
        h1 {{
            font-size: 2.25rem;
            font-weight: 700;
            margin-bottom: 0.5rem;
        }}
        h1 span {{
            color: var(--primary-color);
        }}

        /* NEW: Tagline */
        .tagline {{
            color: var(--text-secondary);
            font-size: 1rem;
            margin-top: 0;
            margin-bottom: 2rem;
        }}

        input, select {{
            padding: 0.8rem;
            width: 100%;
            margin-bottom: 0.75rem; /* Consistent margin */
            border-radius: 8px;
            border: 1px solid var(--border-color);
            font-size: 1rem;
            font-family: 'Inter', Arial, sans-serif;
            box-sizing: border-box; /* Crucial for padding */
            /* NEW: Smooth focus transition */
            transition: border-color 0.3s ease, box-shadow 0.3s ease;
        }}

        /* NEW: Focus state for accessibility and polish */
        input:focus, select:focus {{
            border-color: var(--primary-color);
            box-shadow: 0 0 0 3px rgba(79, 70, 229, 0.1);
            outline: none;
        }}

        button {{
            background: var(--primary-color);
            color: white;
            border: none;
            padding: 0.8rem 1.5rem;
            font-size: 1rem;
            font-weight: 500; /* NEW */
            border-radius: 8px;
            cursor: pointer;
            width: 100%;
            margin-top: 0.5rem;
            /* NEW: Smooth hover transition */
            transition: background-color 0.3s ease;
        }}
        button:hover {{
            background: var(--primary-hover);
        }}
        button:disabled {{
            background: #9ca3af;
            cursor: not-allowed;
        }}

        /* NEW: Styling for the result box */
        #result {{
            /* Hidden by default for transition */
            opacity: 0;
            max-height: 0;
            overflow: hidden;
            transition: opacity 0.5s ease, max-height 0.5s ease, margin-top 0.5s ease;
        }}
        /* NEW: 'show' class to trigger animation */
        #result.show {{
            opacity: 1;
            max-height: 100px;
            margin-top: 1.5rem;
        }}

        .short-link {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.8rem 1rem;
            background: #f9fafb;
            border-radius: 8px;
            border: 1px solid #e5e7eb;
            word-break: break-all;
            text-align: left;
        }}
        #shortUrl {{
            font-weight: 500;
        }}

        /* NEW: Improved copy button */
        .copy-btn {{
            background: #e5e7eb;
            color: #374151;
            padding: 0.5rem 0.8rem;
            border-radius: 6px;
            cursor: pointer;
            margin-left: 1rem;
            width: auto; /* Override 100% width */
            margin-top: 0;
            font-size: 0.9rem;
            transition: background-color 0.3s ease;
        }}
        .copy-btn:hover {{
            background: #d1d5db;
        }}
        .copy-btn:disabled {{
            background: #e5e7eb;
            color: #6b7280;
        }}

        /* NEW: Inline error message */
        #error-msg {{
            color: #dc2626; /* Red */
            font-size: 0.9rem;
            margin-top: 1rem;
            display: none; /* Hidden by default */
        }}

        @media(max-width:500px){{
            .container {{ padding: 2rem 1.5rem; }}
            h1 {{ font-size: 1.8rem; }}
            .tagline {{ margin-bottom: 1.5rem; }}
        }}
    </style>
    </head>
    <body>
    <div class="container">
      <h1>Shortlinks<span>.art</span></h1>
      <p class="tagline">Fast, simple, and free.</p>
      
      <input type="url" id="longUrl" placeholder="Enter your URL here">
      <select id="ttl">
        <option value="1h">1 Hour</option>
        <option value="24h" selected>24 Hours</option>
        <option value="1w">1 Week</option>
        <option value="never">Never</option>
      </select>
      <input type="text" id="customCode" placeholder="Custom code (optional)">
      
      <div id="error-msg"></div>
      
      <button id="shortenBtn">Shorten</button>
      
      <div id="result">
        <div class="short-link">
          <span id="shortUrl"></span>
          <button class="copy-btn" id="copyBtn">Copy</button>
        </div>
      </div>
    </div>

    <script>
    const shortenBtn = document.getElementById("shortenBtn");
    const resultDiv = document.getElementById("result");
    const shortUrlSpan = document.getElementById("shortUrl");
    const copyBtn = document.getElementById("copyBtn");
    const errorDiv = document.getElementById("error-msg");

    shortenBtn.addEventListener("click", async () => {{
        const longUrl = document.getElementById("longUrl").value.trim();
        const ttl = document.getElementById("ttl").value;
        const customCode = document.getElementById("customCode").value.trim() || undefined;
        
        // NEW: Clear previous errors
        errorDiv.style.display = "none";
        errorDiv.textContent = "";

        if (!longUrl) {{
            // NEW: Show inline error
            errorDiv.textContent = "Please enter a URL.";
            errorDiv.style.display = "block";
            return;
        }}
        
        // NEW: Disable button on submit
        shortenBtn.disabled = true;
        shortenBtn.textContent = "Shortening...";

        try {{
            const res = await fetch("/api/v1/links", {{
                method:"POST",
                headers:{{"Content-Type":"application/json"}},
                body: JSON.stringify({{long_url:longUrl, ttl:ttl, custom_code:customCode}})
            }});
            const data = await res.json();
            
            if (res.ok) {{
                shortUrlSpan.textContent = data.short_url;
                resultDiv.classList.add("show"); // NEW: Trigger animation
            }} else {{
                // NEW: Show inline error
                errorDiv.textContent = data.detail || "Error creating short link";
                errorDiv.style.display = "block";
            }}
        }} catch(err) {{
            console.error(err);
            // NEW: Show inline error
            errorDiv.textContent = "Failed to connect to the server.";
            errorDiv.style.display = "block";
        }} finally {{
            // NEW: Re-enable button
            shortenBtn.disabled = false;
            shortenBtn.textContent = "Shorten";
        }}
    }});

    copyBtn.addEventListener("click", () => {{
        navigator.clipboard.writeText(shortUrlSpan.textContent)
            .then(() => {{
                // NEW: Better feedback than alert()
                const originalText = copyBtn.textContent;
                copyBtn.textContent = "Copied!";
                copyBtn.disabled = true;
                setTimeout(() => {{
                    copyBtn.textContent = originalText;
                    copyBtn.disabled = false;
                }}, 2000); // Reset after 2 seconds
            }})
            .catch(() => {{
                // NEW: Handle copy failure
                const originalText = copyBtn.textContent;
                copyBtn.textContent = "Failed!";
                copyBtn.disabled = true;
                 setTimeout(() => {{
                    copyBtn.textContent = originalText;
                    copyBtn.disabled = false;
                }}, 2000);
            }});
    }});
    </script>
    </body>
    </html>
    """

# --- UPDATED PREVIEW ROUTE ---
@app.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(short_code: str):
    link = get_link(short_code) # Assuming this is your DB call
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    
    long_url = link["long_url"]

    # FIX 2: Create an absolute URL for the 'href' attribute
    if not long_url.startswith(("http://", "https://")):
        safe_href_url = "https://" + long_url
    else:
        safe_href_url = long_url
    
    # --- NEW: Fetch Metadata ---
    meta = await fetch_metadata(safe_href_url)
    
    # --- NEW: Escape all metadata for security (XSS prevention) ---
    escaped_title = html.escape(meta.get("title") or "Title not found")
    escaped_description = html.escape(meta.get("description") or "No description available.")
    escaped_image_url = html.escape(meta.get("image") or "", quote=True)
    escaped_favicon_url = html.escape(meta.get("favicon") or "", quote=True)
    
    # Escape the URLs for display and href
    escaped_long_url_href = html.escape(safe_href_url, quote=True)
    escaped_long_url_display = html.escape(long_url)

    # --- NEW: Conditionally create HTML blocks ---
    favicon_html = ""
    if meta.get("favicon"):
        favicon_html = f'<img src="{escaped_favicon_url}" class="favicon" alt="">'
        
    image_html = ""
    if meta.get("image"):
        image_html = f'<img src="{escaped_image_url}" alt="Preview Image" class="preview-image">'
    
    description_html = ""
    if meta.get("description"):
        description_html = f'<p class="description">{escaped_description}</p>'
    
    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Preview - {short_code}</title>
        <meta name="robots" content="noindex">
        <meta name="description" content="Preview link before visiting">
        {ADSENSE_SCRIPT}
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif; margin:0; background:#f3f4f6; display:flex; justify-content:center; align-items:center; min-height:100vh; padding:1rem; box-sizing: border-box; }}
            .card {{ background:#fff; padding:2rem; border-radius:12px; box-shadow:0 8px 24px rgba(0,0,0,0.1); width:100%; max-width:500px; text-align:center; }}
            
            /* --- NEW STYLES --- */
            .meta-header {{ display:flex; align-items:center; justify-content:center; gap: 8px; }}
            .favicon {{ width:16px; height:16px; vertical-align:middle; }}
            .preview-image {{
                width: 100%;
                max-height: 250px;
                object-fit: cover;
                border-radius: 8px;
                margin-top: 1.5rem;
                border: 1px solid #eee;
            }}
            .meta-title {{
                margin-top: 0.5rem;
                margin-bottom: 0.5rem;
                font-size: 1.25rem;
                font-weight: 600;
                color: #111827;
            }}
            .description {{
                font-size: 0.9rem;
                color: #4b5563;
                line-height: 1.5;
                margin-bottom: 1.5rem;
            }}
            /* --- END NEW STYLES --- */

            h1 {{ margin-top:0; color:#4f46e5; }}
            p.info {{ margin-bottom: 0; color: #374151; }}
            p.url {{ word-break: break-all; font-weight:bold; color:#111827; margin-top: 8px; background: #f9fafb; padding: 10px; border-radius: 6px; border: 1px solid #e5e7eb;}}
            a.button {{ display:inline-block; margin-top:20px; padding:12px 24px; background:#4f46e5; color:white; text-decoration:none; border-radius:8px; font-weight:bold; }}
            a.button:hover {{ background:#6366f1; }}
            @media(max-width:500px){{ 
                .card {{ padding:1.5rem; }} 
                a.button {{ width:100%; box-sizing: border-box; }} 
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Link Preview</h1>
            
            {image_html}
            
            <div class="meta-header">
                {favicon_html}
                <h2 class="meta-title">{escaped_title}</h2>
            </div>
            
            {description_html}
            <hr style="border:none; border-top: 1px solid #e5e7eb; margin: 1.5rem 0;">

            <p class="info">You are being redirected to:</p>
            <p class="url">{escaped_long_url_display}</p>
            
            <a class="button" href="{escaped_long_url_href}" target="_blank" rel="noopener noreferrer">Proceed to Link</a>
        </div>
    </body>
    </html>
    """
# --- END UPDATED PREVIEW ROUTE ---


@app.get("/r/{short_code}")
async def redirect_link(short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")

    long_url = link["long_url"]

    # FIX 3: Ensure the redirect URL is absolute, handling old data
    if not long_url.startswith(("http://", "https://")):
        absolute_url = "https://" + long_url
    else:
        absolute_url = long_url

    return RedirectResponse(url=absolute_url)
    
start_cleanup_thread()
