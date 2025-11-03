import os
import secrets
import logging
import random
import string
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

# ------------------ CONFIG ------------------
BASE_URL = os.environ.get("BASE_URL", "https://shortlinks.art")
SHORT_CODE_LENGTH = 6
MAX_ID_RETRIES = 10
TTL_MAP = {
    "1h": timedelta(hours=1),
    "24h": timedelta(days=1),
    "1w": timedelta(weeks=1),
    "never": None
}

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# ------------------ FIREBASE ------------------
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

# ------------------ HELPERS ------------------
def _generate_short_code(length=SHORT_CODE_LENGTH):
    chars = string.ascii_lowercase + string.digits
    return ''.join(random.choice(chars) for _ in range(length))

def generate_unique_short_code():
    for _ in range(MAX_ID_RETRIES):
        code = _generate_short_code()
        doc = get_links_collection().document(code).get()
        if not doc.exists:
            return code
    raise RuntimeError("Could not generate unique code.")

def calculate_expiration(ttl: str) -> Optional[datetime]:
    delta = TTL_MAP.get(ttl, TTL_MAP["24h"])
    if delta is None:
        return None
    return datetime.now(timezone.utc) + delta

def create_link_in_db(long_url: str, ttl: str, custom_code: Optional[str] = None):
    code = (custom_code or generate_unique_short_code()).lower()
    if custom_code:
        if not custom_code.isalnum():
            raise ValueError("Custom code must be alphanumeric.")
        doc = get_links_collection().document(code).get()
        if doc.exists:
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
    return {**data, "short_code": code}

def get_link(code: str) -> Optional[Dict[str, Any]]:
    code = code.lower()
    doc = get_links_collection().document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

# ------------------ APP ------------------
app = FastAPI(title="Shortlinks.art URL Shortener")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ------------------ ROUTES ------------------
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
<title>Shortlinks.art - URL Shortener</title>
<style>
:root {--primary:#4f46e5;--secondary:#6366f1;--accent:#facc15;--bg:#f3f4f6;--text:#111827;}
body{font-family:Arial,sans-serif;background:var(--bg);color:var(--text);display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;}
.container{background:#fff;padding:2rem;border-radius:12px;box-shadow:0 8px 24px rgba(0,0,0,0.1);width:100%;max-width:480px;text-align:center;}
input,select{padding:0.8rem;width:100%;margin:0.5rem 0;border-radius:8px;border:1px solid #d1d5db;font-size:1rem;}
button{background:var(--primary);color:white;border:none;padding:0.8rem 1.5rem;font-size:1rem;border-radius:8px;cursor:pointer;margin-top:0.5rem;}
button:hover{background:var(--secondary);}
.short-link{margin-top:1rem;display:flex;justify-content:space-between;align-items:center;padding:0.6rem;background:#f9fafb;border-radius:8px;}
.copy-btn{background:var(--accent);border:none;padding:0.5rem 0.8rem;border-radius:6px;cursor:pointer;color:#111827;}
</style>
</head>
<body>
<div class="container">
<h1>Shortlinks.art</h1>
<input type="url" id="longUrl" placeholder="Enter your URL here">
<select id="ttl">
<option value="1h">1 Hour</option>
<option value="24h" selected>24 Hours</option>
<option value="1w">1 Week</option>
<option value="never">Never</option>
</select>
<input type="text" id="customCode" placeholder="Custom code (optional)">
<button id="shortenBtn">Shorten</button>
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
if(res.ok){shortUrlSpan.textContent=data.short_url;resultDiv.style.display="block";}
else{alert(data.detail||"Error creating short link");}
}catch(err){console.error(err);alert("Failed to connect to the server.");}
});
copyBtn.addEventListener("click",()=>{
navigator.clipboard.writeText(shortUrlSpan.textContent).then(()=>alert("Copied!")).catch(()=>alert("Failed to copy."));
});
</script>
</body>
</html>
"""
@app.get("/r/{short_code}")
async def redirect_link(short_code: str):
    link = get_link(short_code)  # Use the correct function
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail="Link expired")
    
    # Redirect the user to the original URL
    return RedirectResponse(url=link["long_url"])
@app.post("/api/v1/links")
async def api_create_link(payload: Dict[str, Any]):
    long_url = payload.get("long_url")
    ttl = payload.get("ttl","24h")
    custom_code = payload.get("custom_code")
    if not long_url:
        raise HTTPException(status_code=400, detail="Missing long_url")
    try:
        link = create_link_in_db(long_url, ttl, custom_code)
        preview_url = f"/preview/{link['short_code']}"
        return {"short_url": preview_url}
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
        <title>Preview - {short_code}</title>
        <meta name="robots" content="noindex">
        <style>
            body {{
                margin: 0;
                font-family: Arial, sans-serif;
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                background: linear-gradient(135deg, #6366f1, #4f46e5);
                color: #111827;
            }}
            .card {{
                background: white;
                padding: 2rem;
                border-radius: 16px;
                box-shadow: 0 15px 40px rgba(0,0,0,0.15);
                text-align: center;
                max-width: 480px;
                width: 90%;
                animation: fadeIn 0.5s ease-out;
            }}
            h1 {{
                color: #4f46e5;
                margin-bottom: 1rem;
            }}
            p {{
                word-break: break-word;
                font-size: 1.1rem;
            }}
            a.button {{
                display: inline-block;
                margin-top: 1.5rem;
                padding: 0.8rem 1.5rem;
                font-size: 1rem;
                font-weight: bold;
                color: white;
                background-color: #6366f1;
                border-radius: 8px;
                text-decoration: none;
                transition: background 0.3s ease;
            }}
            a.button:hover {{
                background-color: #4f46e5;
            }}
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(-20px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Preview Link</h1>
            <p><strong>Short Code:</strong> {short_code}</p>
            <p><strong>Original URL:</strong></p>
            <p>{long_url}</p>
            <a class="button" href="{BASE_URL}/r/{short_code}" target="_blank">Go to Link</a>
        </div>
    </body>
    </html>
    """
@app.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(short_code: str):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail="Link not found")

    expires_at = link.get("expires_at")
    expired_text = ""
    if expires_at:
        now = datetime.now(timezone.utc)
        if expires_at < now:
            raise HTTPException(status_code=410, detail="Link expired")
        expired_text = f"<p>Expires at: {expires_at.strftime('%Y-%m-%d %H:%M UTC')}</p>"

    long_url = link["long_url"]
    domain = long_url.split("//")[-1].split("/")[0]
    favicon_url = f"https://www.google.com/s2/favicons?domain={domain}"

    return f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Preview - {short_code}</title>
        <meta name="robots" content="noindex">
        <style>
            body {{
                font-family: Arial, sans-serif;
                margin: 0;
                min-height: 100vh;
                display: flex;
                justify-content: center;
                align-items: center;
                background: linear-gradient(135deg, #6366f1, #4f46e5);
            }}
            .card {{
                background: white;
                padding: 2rem;
                border-radius: 16px;
                box-shadow: 0 15px 40px rgba(0,0,0,0.15);
                text-align: center;
                max-width: 480px;
                width: 90%;
                animation: fadeIn 0.5s ease-out;
            }}
            @keyframes fadeIn {{
                from {{ opacity: 0; transform: translateY(-20px); }}
                to {{ opacity: 1; transform: translateY(0); }}
            }}
            h1 {{
                color: #4f46e5;
                margin-bottom: 1rem;
            }}
            .link-info {{
                display: flex;
                align-items: center;
                justify-content: center;
                gap: 0.5rem;
                margin: 1rem 0;
                font-size: 1.1rem;
                word-break: break-all;
            }}
            .link-info img {{
                width: 28px;
                height: 28px;
                border-radius: 4px;
            }}
            .button {{
                display: inline-block;
                padding: 0.8rem 1.8rem;
                background: #facc15;
                color: #111827;
                text-decoration: none;
                border-radius: 10px;
                font-weight: bold;
                margin-top: 1rem;
                transition: all 0.2s;
            }}
            .button:hover {{
                background: #eab308;
            }}
            .expires {{
                color: #6b7280;
                font-size: 0.9rem;
                margin-top: 0.5rem;
            }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>Preview Link</h1>
            <div class="link-info">
                <img src="{favicon_url}" alt="favicon">
                <span>{long_url}</span>
            </div>
            {f'<div class="expires">{expired_text}</div>' if expired_text else ''}
            <a class="button" href="{BASE_URL}/r/{short_code}" target="_blank">Go to Link</a>
        </div>
    </body>
    </html>
    """
