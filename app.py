import os
import secrets
import logging
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

# ---------------- CONFIG ----------------
BASE_URL = os.environ.get("BASE_URL", "https://shortlinks.art")
SHORT_CODE_LENGTH = 8
MAX_ID_RETRIES = 10
TTL_MAP = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------- FIREBASE ----------------
db: firestore.client = None
APP_INSTANCE = None

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

def get_links_collection():
    return init_firebase().collection("links")

# ---------------- HELPERS ----------------
def _generate_short_code(length=SHORT_CODE_LENGTH):
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_unique_short_code():
    for _ in range(MAX_ID_RETRIES):
        code = _generate_short_code()
        if not get_links_collection().document(code).get().exists:
            return code
    raise RuntimeError("Could not generate unique code.")

def calculate_expiration(ttl: str) -> Optional[datetime]:
    delta = TTL_MAP.get(ttl, TTL_MAP["24h"])
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta

def create_link(long_url: str, ttl: str, custom_code: Optional[str] = None) -> Dict[str, Any]:
    code = custom_code or generate_unique_short_code()
    if custom_code:
        if not custom_code.isalnum():
            raise ValueError("Custom code must be alphanumeric.")
        if get_links_collection().document(custom_code).get().exists:
            raise ValueError("Custom code already exists.")
    expires_at = calculate_expiration(ttl)
    data = {
        "long_url": long_url,
        "deletion_token": secrets.token_urlsafe(32),
        "created_at": datetime.now(timezone.utc)
    }
    if expires_at:
        data["expires_at"] = expires_at
    get_links_collection().document(code).set(data)
    data["short_code"] = code
    return data

def get_link(code: str) -> Optional[Dict[str, Any]]:
    doc = get_links_collection().document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

# ---------------- APP ----------------
app = FastAPI(title="Shortlinks.art URL Shortener")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=True,
)

# ---------------- ROUTES ----------------
@app.get("/health")
async def health():
    try:
        init_firebase()
        return {"status": "ok", "database": "initialized"}
    except Exception as e:
        return {"status": "error", "database": str(e)}

@app.get("/", response_class=HTMLResponse)
async def index():
    return """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Shortlinks.art - Fast & Secure URL Shortener</title>
<meta name="description" content="Shortlinks.art - shorten links instantly, fast, secure, and shareable.">
<meta name="keywords" content="url shortener, short links, fast links, shareable links">
<meta name="author" content="Shortlinks.art">
<link rel="canonical" href="https://shortlinks.art/">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

:root {
  --primary:#4f46e5; --secondary:#6366f1; --accent:#facc15;
  --bg-gradient: linear-gradient(135deg,#667eea,#764ba2);
  --card-bg:#fff; --text:#111827; --input-bg:#f9fafb; --btn-hover:#5a56e0;
}

*{box-sizing:border-box;}
body{margin:0;font-family:'Inter',sans-serif;background:var(--bg-gradient);display:flex;justify-content:center;align-items:center;min-height:100vh;color:var(--text);}
.container{background:var(--card-bg);padding:2rem;border-radius:16px;box-shadow:0 12px 36px rgba(0,0,0,0.12);width:90%;max-width:500px;text-align:center;}
h1{color:var(--primary);margin-bottom:1rem;font-size:2rem;}
p.subtitle{color:#6b7280;margin-bottom:2rem;}
input, select{width:100%;padding:0.8rem 1rem;margin:0.5rem 0;border-radius:12px;border:1px solid #d1d5db;background:var(--input-bg);font-size:1rem;}
button{width:100%;padding:0.8rem;margin-top:1rem;font-size:1rem;border:none;border-radius:12px;background:var(--primary);color:#fff;cursor:pointer;transition:all 0.2s ease;}
button:hover{background:var(--btn-hover);}
.short-link{margin-top:1rem;padding:0.6rem 1rem;background:#f3f4f6;border-radius:12px;display:flex;justify-content:space-between;align-items:center;word-break:break-all;box-shadow:0 4px 12px rgba(0,0,0,0.08);}
.copy-btn{background:var(--accent);border:none;padding:0.5rem 0.8rem;border-radius:8px;cursor:pointer;color:#111827;transition:all 0.2s ease;}
.copy-btn:hover{opacity:0.85;}
@media(max-width:480px){h1{font-size:1.5rem;}}
</style>
</head>
<body>
<div class="container">
<h1>Shortlinks.art</h1>
<p class="subtitle">Fast, secure & shareable URL shortener</p>
<input type="url" id="longUrl" placeholder="Enter your URL here" required>
<select id="ttl">
<option value="1h">1 Hour</option>
<option value="24h" selected>24 Hours</option>
<option value="1w">1 Week</option>
<option value="never">Never</option>
</select>
<input type="text" id="customCode" placeholder="Custom code (optional)">
<button id="shortenBtn">Shorten URL</button>
<div id="result" style="display:none;">
<div class="short-link">
<span id="shortUrl"></span>
<button class="copy-btn" id="copyBtn">Copy</button>
</div>
</div>
</div>
<script>
const shortenBtn=document.getElementById("shortenBtn");
const resultDiv=document.getElementById("result");
const shortUrlSpan=document.getElementById("shortUrl");
const copyBtn=document.getElementById("copyBtn");

shortenBtn.addEventListener("click",async()=>{
    const longUrl=document.getElementById("longUrl").value.trim();
    const ttl=document.getElementById("ttl").value;
    const customCode=document.getElementById("customCode").value.trim()||undefined;
    if(!longUrl){alert("Please enter a URL.");return;}
    try{
        const res=await fetch("/api/v1/links",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({long_url:longUrl,ttl:ttl,custom_code:customCode})});
        const data=await res.json();
        if(res.ok){shortUrlSpan.textContent=data.short_url;resultDiv.style.display="flex";}
        else{alert(data.detail||"Error creating short link");}
    }catch(err){console.error(err);alert("Failed to connect to server.");}
});

copyBtn.addEventListener("click",()=>{
    navigator.clipboard.writeText(shortUrlSpan.textContent).then(()=>alert("Copied!")).catch(()=>alert("Failed to copy."));
});
</script>
</body>
</html>
"""

@app.post("/api/v1/links")
async def api_create_link(payload: Dict[str, Any]):
    long_url = payload.get("long_url")
    ttl = payload.get("ttl", "24h")
    custom_code = payload.get("custom_code")
    if not long_url:
        raise HTTPException(status_code=400, detail="Missing long_url")
    try:
        link = create_link(long_url, ttl, custom_code)
        short_url = f"{BASE_URL}/r/{link['short_code']}"
        preview_url = f"{BASE_URL}/preview/{link['short_code']}"
        return {"short_url": short_url, "preview_url": preview_url}
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    long_url = link["long_url"]

    return f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Preview - {short_code}</title>
<meta name="description" content="Preview for short link {short_code} on Shortlinks.art">
<meta name="robots" content="noindex">
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');

:root {{
  --primary:#4f46e5;
  --secondary:#6366f1;
  --accent:#facc15;
  --bg-gradient: linear-gradient(135deg,#667eea,#764ba2);
  --card-bg:#fff;
  --text:#111827;
  --btn-hover:#5a56e0;
}}

*{{box-sizing:border-box;}}
body{{margin:0;font-family:'Inter',sans-serif;background:var(--bg-gradient);display:flex;justify-content:center;align-items:center;min-height:100vh;color:var(--text);padding:1rem;}}
.container{{background:var(--card-bg);padding:2rem;border-radius:16px;box-shadow:0 12px 36px rgba(0,0,0,0.12);width:100%;max-width:480px;text-align:center;}}
h1{{color:var(--primary);margin-bottom:0.5rem;font-size:2rem;}}
p{{margin-bottom:1rem;word-break:break-word;}}
a.button{{display:inline-block;padding:0.8rem 1.5rem;background:var(--primary);color:#fff;text-decoration:none;font-weight:600;border-radius:12px;transition:all 0.2s ease;margin-top:1rem;}}
a.button:hover{{background:var(--btn-hover);}}
.short-link-box{{margin-top:1rem;padding:0.8rem 1rem;background:#f3f4f6;border-radius:12px;word-break:break-all;box-shadow:0 4px 12px rgba(0,0,0,0.08);}}
@media(max-width:480px){{h1{{font-size:1.5rem;}}}}
</style>
</head>
<body>
<div class="container">
<h1>Preview Link</h1>
<p class="short-link-box">{long_url}</p>
<a class="button" href="/r/{short_code}" target="_blank">Go to Link</a>
</div>
</body>
</html>
"""
    
from fastapi import FastAPI, HTTPException
from fastapi.responses import RedirectResponse
from datetime import datetime, timezone

# Assumes you already have get_link(code) implemented
@app.get("/r/{short_code}")
async def redirect_link(short_code: str):
    # Fetch the link document from Firebase
    link = get_link(short_code)
    
    if not link:
        # Link not found
        raise HTTPException(status_code=404, detail="Link not found")
    
    # Check expiration
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    
    # Redirect to the original URL
    long_url = link["long_url"]
    return RedirectResponse(url=long_url, status_code=302)
