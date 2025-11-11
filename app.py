import os
import secrets
import html
import string
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any, Literal, Callable

import socket
import ipaddress
import asyncio
import io
import base64

import validators
from pydantic import BaseModel, constr
from firebase_admin.firestore import transactional

import qrcode
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from starlette.staticfiles import StaticFiles

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from fastapi.templating import Jinja2Templates

from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, get_app

from google.cloud.firestore_v1.base_query import FieldFilter
from google.cloud.firestore_v1.query import Query

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

# ---------------- LOCALIZATION (i18n) ----------------

# 1. Define supported languages
SUPPORTED_LOCALES = ["en", "es", "zh", "hi", "pt", "fr", "de", "ar"]
DEFAULT_LOCALE = "en"

# 2. Store all translations in a dictionary
# NOTE: This is now very large. For future growth,
# consider loading these from separate JSON files.
translations = {
    "en": {
        "app_title": "Shortlinks.art - Free & Open Source URL Shortener",
        "link_not_found": "Link not found",
        "link_expired": "Link expired",
        "invalid_url": "Invalid URL provided.",
        "custom_code_exists": "Custom code already exists",
        "id_generation_failed": "Could not generate unique short code.",
        "owner_id_required": "Owner ID is required",
        "token_missing": "Deletion token is missing",
        "delete_success": "Link successfully deleted.",
        "delete_invalid_token": "Invalid deletion token. Link was not deleted.",
        "create_link_heading": "Create a Short Link",
        "long_url_placeholder": "Enter your long URL (e.g., https://...)",
        "create_button": "Shorten",
        "custom_code_label": "Custom code (optional)",
        "ttl_label": "Expires after",
        "ttl_1h": "1 Hour",
        "ttl_24h": "24 Hours",
        "ttl_1w": "1 Week",
        "ttl_never": "Never",
    },
    "es": {
        "app_title": "Shortlinks.art - Acortador de URL gratuito y de código abierto",
        "link_not_found": "Enlace no encontrado",
        "link_expired": "El enlace ha caducado",
        "invalid_url": "La URL proporcionada no es válida.",
        "custom_code_exists": "Este código personalizado ya existe",
        "id_generation_failed": "No se pudo generar un código corto único.",
        "owner_id_required": "Se requiere ID de propietario",
        "token_missing": "Falta el token de eliminación",
        "delete_success": "Enlace eliminado con éxito.",
        "delete_invalid_token": "Token de eliminación no válido. El enlace no fue eliminado.",
        "create_link_heading": "Crear un enlace corto",
        "long_url_placeholder": "Introduce tu URL larga (ej., https://...)",
        "create_button": "Acortar",
        "custom_code_label": "Código personalizado (opcional)",
        "ttl_label": "Expira después de",
        "ttl_1h": "1 Hora",
        "ttl_24h": "24 Horas",
        "ttl_1w": "1 Semana",
        "ttl_never": "Nunca",
    },
    "zh": { # Mandarin Chinese (Simplified)
        "app_title": "Shortlinks.art - 免费的开源网址缩短服务",
        "link_not_found": "链接未找到",
        "link_expired": "链接已过期",
        "invalid_url": "提供了无效的URL。",
        "custom_code_exists": "自定义代码已存在",
        "id_generation_failed": "无法生成唯一的短代码。",
        "owner_id_required": "需要所有者ID",
        "token_missing": "缺少删除令牌",
        "delete_success": "链接已成功删除。",
        "delete_invalid_token": "删除令牌无效。链接未被删除。",
        "create_link_heading": "创建短链接",
        "long_url_placeholder": "输入您的长网址 (例如 https://...)",
        "create_button": "缩短",
        "custom_code_label": "自定义代码 (可选)",
        "ttl_label": "过期时间",
        "ttl_1h": "1 小时",
        "ttl_24h": "24 小时",
        "ttl_1w": "1 周",
        "ttl_never": "从不",
    },
    "hi": { # Hindi
        "app_title": "Shortlinks.art - मुफ़्त और ओपन सोर्स यूआरएल शॉर्टनर",
        "link_not_found": "लिंक नहीं मिला",
        "link_expired": "लिंक समाप्त हो गया है",
        "invalid_url": "अमान्य यूआरएल प्रदान किया गया।",
        "custom_code_exists": "कस्टम कोड पहले से मौजूद है",
        "id_generation_failed": "अद्वितीय शॉर्ट कोड उत्पन्न नहीं किया जा सका।",
        "owner_id_required": "मालिक आईडी की आवश्यकता है",
        "token_missing": "विलोपन टोकन गायब है",
        "delete_success": "लिंक सफलतापूर्वक हटा दिया गया।",
        "delete_invalid_token": "अमान्य विलोपन टोकन। लिंक हटाया नहीं गया।",
        "create_link_heading": "एक छोटा लिंक बनाएं",
        "long_url_placeholder": "अपना लंबा यूआरएल दर्ज करें (जैसे, https://...)",
        "create_button": "छोटा करें",
        "custom_code_label": "कस्टम कोड (वैकल्पिक)",
        "ttl_label": "इसके बाद समाप्त हो जाएगा",
        "ttl_1h": "1 घंटा",
        "ttl_24h": "24 घंटे",
        "ttl_1w": "1 सप्ताह",
        "ttl_never": "कभी नहीं",
    },
    "pt": { # Portuguese
        "app_title": "Shortlinks.art - Encurtador de URL gratuito e de código aberto",
        "link_not_found": "Link não encontrado",
        "link_expired": "O link expirou",
        "invalid_url": "URL fornecida é inválida.",
        "custom_code_exists": "O código personalizado já existe",
        "id_generation_failed": "Não foi possível gerar um código curto único.",
        "owner_id_required": "ID do proprietário é obrigatório",
        "token_missing": "Token de exclusão ausente",
        "delete_success": "Link excluído com sucesso.",
        "delete_invalid_token": "Token de exclusão inválido. O link não foi excluído.",
        "create_link_heading": "Criar um link curto",
        "long_url_placeholder": "Digite sua URL longa (ex: https://...)",
        "create_button": "Encurtar",
        "custom_code_label": "Código personalizado (opcional)",
        "ttl_label": "Expira em",
        "ttl_1h": "1 Hora",
        "ttl_24h": "24 Horas",
        "ttl_1w": "1 Semana",
        "ttl_never": "Nunca",
    },
    "fr": { # French
        "app_title": "Shortlinks.art - Raccourcisseur d'URL gratuit et open source",
        "link_not_found": "Lien non trouvé",
        "link_expired": "Le lien a expiré",
        "invalid_url": "URL fournie invalide.",
        "custom_code_exists": "Le code personnalisé existe déjà",
        "id_generation_failed": "Impossible de générer un code court unique.",
        "owner_id_required": "ID du propriétaire requis",
        "token_missing": "Jeton de suppression manquant",
        "delete_success": "Lien supprimé avec succès.",
        "delete_invalid_token": "Jeton de suppression non valide. Le lien n'a pas été supprimé.",
        "create_link_heading": "Créer un lien court",
        "long_url_placeholder": "Entrez votre URL longue (ex: https://...)",
        "create_button": "Raccourcir",
        "custom_code_label": "Code personnalisé (optionnel)",
        "ttl_label": "Expire après",
        "ttl_1h": "1 Heure",
        "ttl_24h": "24 Heures",
        "ttl_1w": "1 Semaine",
        "ttl_never": "Jamais",
    },
    "de": { # German
        "app_title": "Shortlinks.art - Kostenloser Open-Source-URL-Shortener",
        "link_not_found": "Link nicht gefunden",
        "link_expired": "Link ist abgelaufen",
        "invalid_url": "Ungültige URL angegeben.",
        "custom_code_exists": "Benutzerdefinierter Code existiert bereits",
        "id_generation_failed": "Konnte keinen eindeutigen Kurzcode generieren.",
        "owner_id_required": "Besitzer-ID erforderlich",
        "token_missing": "Lösch-Token fehlt",
        "delete_success": "Link erfolgreich gelöscht.",
        "delete_invalid_token": "Ungültiges Lösch-Token. Link wurde nicht gelöscht.",
        "create_link_heading": "Einen Kurzlink erstellen",
        "long_url_placeholder": "Geben Sie Ihre lange URL ein (z.B. https://...)",
        "create_button": "Kürzen",
        "custom_code_label": "Benutzerdefinierter Code (optional)",
        "ttl_label": "Läuft ab nach",
        "ttl_1h": "1 Stunde",
        "ttl_24h": "24 Stunden",
        "ttl_1w": "1 Woche",
        "ttl_never": "Nie",
    },
    "ar": { # Arabic
        "app_title": "Shortlinks.art - خدمة تقصير روابط مجانية ومفتوحة المصدر",
        "link_not_found": "الرابط غير موجود",
        "link_expired": "انتهت صلاحية الرابط",
        "invalid_url": "الرابط المُقدم غير صالح.",
        "custom_code_exists": "الرمز المخصص موجود بالفعل",
        "id_generation_failed": "لم يمكن إنشاء رمز قصير فريد.",
        "owner_id_required": "معرف المالك مطلوب",
        "token_missing": "رمز الحذف مفقود",
        "delete_success": "تم حذف الرابط بنجاح.",
        "delete_invalid_token": "رمز الحذف غير صالح. لم يتم حذف الرابط.",
        "create_link_heading": "إنشاء رابط قصير",
        "long_url_placeholder": "أدخل الرابط الطويل (مثال: https://...)",
        "create_button": "تقصير",
        "custom_code_label": "رمز مخصص (اختياري)",
        "ttl_label": "تنتهي الصلاحية بعد",
        "ttl_1h": "1 ساعة",
        "ttl_24h": "24 ساعة",
        "ttl_1w": "1 أسبوع",
        "ttl_never": "أبداً",
    }
}


# 3. Detect locale from request header
def get_locale(request: Request) -> str:
    """Parses the Accept-Language header to find the best matching locale."""
    try:
        lang_header = request.headers.get("accept-language")
        if not lang_header:
            return DEFAULT_LOCALE
        
        # Simple parser: gets the first language, e.g., "es-ES,en;q=0.9" -> "es"
        primary_lang = lang_header.split(',')[0].split('-')[0].lower()
        
        if primary_lang in SUPPORTED_LOCALES:
            return primary_lang
    except Exception:
        pass # Fallback to default
    return DEFAULT_LOCALE

# 4. Create a translator "getter" dependency
def get_translator_and_locale(request: Request) -> (Callable[[str], str], str):
    """
    Returns a 'gettext' style function (named '_') and the locale.
    """
    locale = get_locale(request)
    
    def _(key: str) -> str:
        # Get the translated string for the detected locale
        translated = translations.get(locale, {}).get(key)
        if translated:
            return translated
        
        # Fallback to the default locale (English)
        fallback = translations.get(DEFAULT_LOCALE, {}).get(key)
        if fallback:
            return fallback
            
        # As a last resort, return the key itself
        return key
        
    return _, locale

# Wrapper dependency to just get the translator function
def get_translator(tr: tuple = Depends(get_translator_and_locale)) -> Callable[[str], str]:
    return tr[0]

# Wrapper dependency to just get the locale
def get_current_locale(tr: tuple = Depends(get_translator_and_locale)) -> str:
    return tr[1]


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
        .where(filter=FieldFilter("expires_at", "<", now))
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

def generate_qr_code_data_uri(text: str) -> str:
    img = qrcode.make(text, box_size=10, border=2)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64_str = base64.b64encode(buf.getvalue()).decode("utf-8")
    return f"data:image/png;base64,{b64_str}"

def create_link_in_db(long_url: str, ttl: str, custom_code: Optional[str] = None, owner_id: Optional[str] = None) -> Dict[str, Any]:
    collection = init_firebase().collection("links")
    if custom_code:
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
        "created_at": datetime.now(timezone.utc),
        "click_count": 0,
        "clicks_by_day": {},
        "meta_fetched": False,
        "meta_title": None,
        "meta_description": None,
        "meta_image": None,
        "meta_favicon": None,
        "owner_id": owner_id
    }
    if expires_at:
        data["expires_at"] = expires_at
    collection.document(code).set(data)
    
    short_url_preview = f"{BASE_URL}/preview/{code}"
    stats_url = f"{BASE_URL}/stats/{code}"
    delete_url = f"{BASE_URL}/delete/{code}?token={deletion_token}"

    return {
        **data,
        "short_code": code,
        "short_url_preview": short_url_preview,
        "stats_url": stats_url,
        "delete_url": delete_url
    }

def get_link(code: str) -> Optional[Dict[str, Any]]:
    collection = init_firebase().collection("links")
    doc = collection.document(code).get()
    if not doc.exists:
        return None
    data = doc.to_dict()
    data["short_code"] = doc.id
    return data

def is_public_ip(ip_str: str) -> bool:
    try:
        ip = ipaddress.ip_address(ip_str)
        return ip.is_global
    except ValueError:
        return False

async def fetch_metadata(url: str) -> dict:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    meta = {
        "title": None,
        "description": None,
        "image": None,
        "favicon": None
    }
    try:
        parsed_url = urlparse(url)
        hostname = parsed_url.hostname
        if not hostname:
            raise ValueError("Invalid hostname")

        try:
            ip_address = await asyncio.to_thread(socket.gethostbyname, hostname)
        except socket.gaierror:
            raise ValueError("Could not resolve hostname")

        if not is_public_ip(ip_address):
            raise SecurityException(f"Blocked request to non-public IP: {ip_address}")

        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers, follow_redirects=True, timeout=5.0)
            response.raise_for_status()
            
            final_url = str(response.url)
            soup = BeautifulSoup(response.text, "lxml")

            if og_title := soup.find("meta", property="og:title"):
                meta["title"] = og_title.get("content")
            elif title := soup.find("title"):
                meta["title"] = title.string
            if og_desc := soup.find("meta", property="og:description"):
                meta["description"] = og_desc.get("content")
            elif desc := soup.find("meta", name="description"):
                meta["description"] = desc.get("content")
            if og_image := soup.find("meta", property="og:image"):
                meta["image"] = urljoin(final_url, og_image.get("content"))
            if favicon := soup.find("link", rel="icon") or soup.find("link", rel="shortcut icon"):
                meta["favicon"] = urljoin(final_url, favicon.get("href"))
            else:
                parsed_url_fallback = urlparse(final_url)
                meta["favicon"] = f"{parsed_url_fallback.scheme}://{parsed_url_fallback.netloc}/favicon.ico"

    except (httpx.RequestError, httpx.HTTPStatusError) as e:
        print(f"Error fetching metadata for {url}: {e}")
    except SecurityException as e:
        print(f"SSRF Prevention: {e}")
    except Exception as e:
        print(f"Error parsing or validating URL for {url}: {e}")
    return meta

# ---------------- APP ----------------
limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="Shortlinks.art URL Shortener")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class LinkCreatePayload(BaseModel):
    long_url: str
    ttl: Literal["1h", "24h", "1w", "never"] = "24h"
    custom_code: Optional[constr(pattern=r'^[a-zA-Z0-9]*$', max_length=20)] = None
    utm_tags: Optional[str] = None
    owner_id: Optional[str] = None

# ---------------- ROUTES ----------------
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
@limiter.limit("10/minute")
async def api_create_link(
    request: Request, 
    payload: LinkCreatePayload, 
    _ : Callable = Depends(get_translator)
):
    long_url = payload.long_url
    
    if not long_url.startswith(("http://", "https://")):
        long_url = "https://" + long_url

    if not validators.url(long_url, public=True):
        raise HTTPException(status_code=400, detail=_("invalid_url"))

    if payload.utm_tags:
        cleaned_tags = payload.utm_tags.lstrip("?&")
        if cleaned_tags:
            if "?" in long_url:
                long_url = f"{long_url}&{cleaned_tags}"
            else:
                long_url = f"{long_url}?{cleaned_tags}"

    try:
        link = create_link_in_db(long_url, payload.ttl, payload.custom_code, payload.owner_id)
        qr_code_data_uri = generate_qr_code_data_uri(link["short_url_preview"])
        return {
            "short_url": link["short_url_preview"],
            "stats_url": link["stats_url"],
            "delete_url": link["delete_url"],
            "qr_code_data": qr_code_data_uri
        }
    except ValueError as e:
        if "Custom code already exists" in str(e):
            raise HTTPException(status_code=409, detail=_("custom_code_exists"))
        raise HTTPException(status_code=400, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=_("id_generation_failed"))

@app.get("/", response_class=HTMLResponse)
async def index(
    request: Request, 
    _ : Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale)
):
    context = {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "_": _,
        "locale": locale # Pass locale for RTL check
    }
    return templates.TemplateResponse("index.html", context)
    
@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request, 
    _ : Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale)
):
    context = {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "_": _,
        "locale": locale
    }
    return templates.TemplateResponse("dashboard.html", context)

@app.get("/about", response_class=HTMLResponse)
async def about(
    request: Request, 
    _ : Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale)
):
    context = {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "_": _,
        "locale": locale
    }
    return templates.TemplateResponse("about.html", context)

@app.get("/api/v1/my-links")
async def get_my_links(owner_id: str, _ : Callable = Depends(get_translator)):
    if not owner_id:
        raise HTTPException(status_code=400, detail=_("owner_id_required"))

    db = init_firebase()
    links_query = (
        db.collection("links")
        .where(filter=FieldFilter("owner_id", "==", owner_id))
        .order_by("created_at", direction=Query.DESCENDING)
        .limit(100)
    )
    docs = links_query.stream()
    
    links_list = []
    for doc in docs:
        data = doc.to_dict()
        short_code = doc.id
        data["short_code"] = short_code
        data["short_url_preview"] = f"{BASE_URL}/preview/{short_code}"
        data["stats_url"] = f"{BASE_URL}/stats/{short_code}"
        data["delete_url"] = f"{BASE_URL}/delete/{short_code}?token={data['deletion_token']}"
        data["created_at"] = data["created_at"].isoformat()
        if "expires_at" in data and data["expires_at"]:
            data["expires_at"] = data["expires_at"].isoformat()
            
        links_list.append(data)
        
    return {"links": links_list}

@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots():
    content = f"""User-agent: *
Disallow: /api/
Disallow: /r/
Disallow: /preview/
Disallow: /health
Disallow: /dashboard
Disallow: /api/v1/my-links
Sitemap: {BASE_URL}/sitemap.xml
"""
    return content

@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    last_mod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>{BASE_URL}/</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{BASE_URL}/about</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>0.8</priority>
  </url>
</urlset>
"""
    return Response(content=xml_content, media_type="application/xml")

@app.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(
    request: Request, 
    short_code: str, 
    _ : Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale)
):
    db_client = init_firebase()
    doc_ref = db_client.collection("links").document(short_code)
    doc = doc_ref.get()

    if not doc.exists:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    link = doc.to_dict()
    link["short_code"] = doc.id
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail=_("link_expired"))
    
    long_url = link["long_url"]
    
    if not long_url.startswith(("http://", "https://")):
        safe_href_url = "https://" + long_url
    else:
        safe_href_url = long_url
    
    if link.get("meta_fetched"):
        print(f"[CACHE HIT] for {short_code}")
        meta = {
            "title": link.get("meta_title"),
            "description": link.get("meta_description"),
            "image": link.get("meta_image"),
            "favicon": link.get("meta_favicon")
        }
    else:
        print(f"[CACHE MISS] for {short_code}. Fetching...")
        meta = await fetch_metadata(safe_href_url)
        
        try:
            doc_ref.update({
                "meta_fetched": True,
                "meta_title": meta.get("title"),
                "meta_description": meta.get("description"),
                "meta_image": meta.get("image"),
                "meta_favicon": meta.get("favicon")
            })
        except Exception as e:
            print(f"Error updating cache for {short_code}: {e}")
            
    context = {
        "request": request,
        "short_code": short_code,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "_": _,
        "locale": locale,
        "escaped_long_url_href": html.escape(safe_href_url, quote=True),
        "escaped_long_url_display": html.escape(long_url),
        "meta_title": html.escape(meta.get("title") or "Title not found"),
        "meta_description": html.escape(meta.get("description") or "No description available."),
        "meta_image_url": html.escape(meta.get("image") or "", quote=True),
        "meta_favicon_url": html.escape(meta.get("favicon") or "", quote=True),
        "has_image": bool(meta.get("image")),
        "has_favicon": bool(meta.get("favicon")),
        "has_description": bool(meta.get("description"))
    }
    
    return templates.TemplateResponse("preview.html", context)

@transactional
def update_clicks_in_transaction(transaction, doc_ref, get_text: Callable) -> str:
    doc = doc_ref.get(transaction=transaction)
    if not doc.exists:
        raise HTTPException(status_code=404, detail=get_text("link_not_found"))

    link = doc.to_dict()
    
    expires_at = link.get("expires_at")
    if expires_at and expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=410, detail=get_text("link_expired"))

    today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    day_key = f"clicks_by_day.{today_str}"
    
    transaction.update(doc_ref, {
        "click_count": firestore.Increment(1),
        day_key: firestore.Increment(1)
    })
    
    return link["long_url"]

@app.get("/r/{short_code}")
async def redirect_link(short_code: str, _ : Callable = Depends(get_translator)):
    db = init_firebase()
    doc_ref = db.collection("links").document(short_code)
    
    try:
        transaction = db.transaction()
        long_url = update_clicks_in_transaction(transaction, doc_ref, get_text=_)
    except HTTPException as e:
        raise e
    except Exception as e:
        print(f"Transaction failed: {e}")
        link = get_link(short_code)
        if not link:
            raise HTTPException(status_code=404, detail=_("link_not_found"))
        expires_at = link.get("expires_at")
        if expires_at and expires_at < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail=_("link_expired"))
        long_url = link["long_url"]

    if not long_url.startswith(("http://", "https://")):
        absolute_url = "https://" + long_url
    else:
        absolute_url = long_url

    return RedirectResponse(url=absolute_url)

@app.get("/stats/{short_code}", response_class=HTMLResponse)
async def stats(
    request: Request, 
    short_code: str, 
    _ : Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale)
):
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    context = {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "link": link,
        "_": _,
        "locale": locale
    }
    return templates.TemplateResponse("stats.html", context)

@app.get("/delete/{short_code}", response_class=HTMLResponse)
async def delete(
    request: Request, 
    short_code: str, 
    token: Optional[str] = None,
    _ : Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale)
):
    if not token:
        raise HTTPException(status_code=400, detail=_("token_missing"))
    
    collection_ref = init_firebase().collection("links")
    doc_ref = collection_ref.document(short_code)
    
    doc = doc_ref.get()
    if not doc.exists:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    link = doc.to_dict()
    
    if link.get("deletion_token") == token:
        doc_ref.delete()
        context = {
            "request": request, 
            "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
            "success": True, 
            "message": _("delete_success"),
            "_": _,
            "locale": locale
        }
    else:
        context = {
            "request": request,
            "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
            "success": False,
            "message": _("delete_invalid_token"),
            "_": _,
            "locale": locale
        }
        
    return templates.TemplateResponse("delete_status.html", context)

class SecurityException(Exception):
    pass

start_cleanup_thread()
