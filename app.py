import asyncio
import os
import secrets
import html
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Literal, Callable, List, Tuple
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request, Depends, Path, BackgroundTasks, status, APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

from slowapi import Limiter, _rate_limit_exceeded_handler, errors
from slowapi.util import get_remote_address

# Import core modules
import config
from db_manager import (
    init_db, create_link as db_create_link, get_link_by_id as db_get_link, 
    delete_link_by_id_and_token as db_delete_link, get_db_connection,
    update_link_metadata as db_update_link_metadata
)
from models import LinkResponse, LinkCreatePayload

# Import core_logic functions/classes
from core_logic import (
    logger, load_translations_from_json, get_translation,
    get_browser_locale, get_common_context, get_translator, get_api_translator,
    get_current_locale, 
    CleanupWorker, URLValidator, SecurityException, ValidationException,
    ResourceNotFoundException, ResourceExpiredException, 
    BOOTSTRAP_CDN, BOOTSTRAP_JS,
    AISummarizer, MetadataFetcher, generate_qr_code_data_uri 
)

# --- GLOBAL INSTANCES ---
worker_instance: CleanupWorker = None
limiter = Limiter(key_func=get_remote_address)
templates = Jinja2Templates(directory="templates")
summarizer = AISummarizer()
metadata_fetcher = MetadataFetcher()

# --- LIFESPAN AND APP SETUP ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    global worker_instance
    try:
        config.config.validate() 
        load_translations_from_json()
        init_db()
        
        cleanup_worker = CleanupWorker()
        worker_instance = cleanup_worker
        cleanup_worker.start()
        
        logger.info("Application started successfully")
        yield
        
    finally:
        if worker_instance:
            worker_instance.stop()
        logger.info("Application shutdown complete")

# Main app instance
app = FastAPI(
    title="Shortlinks.art",
    lifespan=lifespan
)

# --- MIDDLEWARE ---
app.add_middleware(GZipMiddleware, minimum_size=1000)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.state.limiter = limiter
app.add_exception_handler(errors.RateLimitExceeded, _rate_limit_exceeded_handler)


# --- STATIC FILES SETUP ---
app.mount("/static", StaticFiles(directory="static"), name="static")


# --- ROUTERS DEFINITION (API) ---

api_router = APIRouter(prefix="/api/v1", tags=["API"])

@api_router.post("/links", response_model=LinkResponse)
@limiter.limit(config.RATE_LIMIT_CREATE) 
async def api_create_link(
    request: Request,
    payload: LinkCreatePayload,
    background_tasks: BackgroundTasks,
    translator: Callable = Depends(get_api_translator),
):
    """Create a new shortened link"""
    try:
        deletion_token = secrets.token_urlsafe(32)
        long_url = await URLValidator.validate_and_sanitize(payload.long_url)
        
        if payload.utm_tags:
            cleaned_tags = payload.utm_tags.lstrip("?&")
            if cleaned_tags:
                separator = "&" if "?" in long_url else "?"
                long_url = f"{long_url}{separator}{cleaned_tags}"
        
        short_code = await db_create_link(
            long_url=long_url,
            ttl=payload.ttl,
            deletion_token=deletion_token,
            custom_code=payload.custom_code,
            owner_id=payload.owner_id,
            utm_tags=payload.utm_tags
        )
        
        locale = get_browser_locale(request)
        localized_preview_url = f"{config.BASE_URL}/{locale}/preview/{short_code}"
        qr_code_data = generate_qr_code_data_uri(localized_preview_url)
        
        # Add background task to fetch metadata
        background_tasks.add_task(summarizer.summarize_in_background, short_code, long_url)
        
        return LinkResponse(
            short_url=f"{config.BASE_URL}/r/{short_code}",
            stats_url=f"{config.BASE_URL}/{locale}/stats/{short_code}",
            delete_url=f"{config.BASE_URL}/{locale}/delete/{short_code}?token={deletion_token}",
            qr_code_data=qr_code_data
        )
    
    except ValueError as e: # This is specifically for db_manager's "already in use" error
        if "already in use" in str(e):
            logger.warning(f"Custom code conflict: {e}")
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e))
        logger.error(f"Link creation validation failed (ValueError): {e}")
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=translator("invalid_payload"))
    except (ValidationException, SecurityException) as e:
        logger.error(f"Link creation validation failed (Security/Validation): {e.detail}")
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error creating link: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=translator("error_creating_link")
        )

@api_router.get("/my-links")
@limiter.limit(config.RATE_LIMIT_STATS)
async def api_get_my_links(
    request: Request,
    owner_id: str,
    translator: Callable = Depends(get_api_translator),
):
    """Get all links for an owner (MOCKED)"""
    if not owner_id:
        raise ValidationException(translator("owner_id_required"))
    
    links = [] 
    return {"links": links, "count": len(links)}

# --- ROUTERS DEFINITION (WEB PAGES) ---

web_router = APIRouter()
i18n_router = APIRouter()

@web_router.get("/", include_in_schema=False)
async def root_redirect(request: Request):
    """Redirect to localized homepage"""
    locale = get_browser_locale(request)
    response = RedirectResponse(url=f"/{locale}", status_code=status.HTTP_302_FOUND)
    response.set_cookie("lang", locale, max_age=365*24*60*60, samesite="lax")
    return response

@web_router.get("/health")
async def health_check():
    """Health check endpoint"""
    translator = lambda key: get_translation(config.DEFAULT_LOCALE, key)
    try:
        with get_db_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchone()
        return {"status": "healthy", "database": "connected", "timestamp": datetime.now(timezone.utc).isoformat()}
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        error_detail = translator("db_connection_error")
        return JSONResponse(status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "database": "error", "error": error_detail})

@web_router.get("/r/{short_code}")
async def redirect_short_code(short_code: str, request: Request, translator: Callable = Depends(get_translator)):
    """Redirect short code to preview page"""
    try:
        if not short_code.isalnum() or len(short_code) < 4:
            raise ValidationException(translator("invalid_short_code"))
        
        locale = get_browser_locale(request) 
        preview_url = f"/{locale}/preview/{short_code}"
        full_redirect_url = f"{config.BASE_URL}{preview_url}"
        
        return RedirectResponse(url=full_redirect_url, status_code=status.HTTP_301_MOVED_PERMANENTLY)
    except ValidationException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error redirecting {short_code}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=translator("redirect_error"))

@web_router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    """Robots.txt for SEO"""
    return f"""User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /r/\nDisallow: /health\nDisallow: /*/delete/\nSitemap: {config.BASE_URL}/sitemap.xml\n"""

@web_router.get("/sitemap.xml", response_class=Response)
async def sitemap():
    """Generate sitemap for SEO"""
    last_mod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    urls = []
    for locale in config.SUPPORTED_LOCALES:
        for page in ["", "/about", "/dashboard"]:
            urls.append(f"""  <url>\n    <loc>{config.BASE_URL}/{locale}{page}</loc>\n    <lastmod>{last_mod}</lastmod>\n    <priority>{1.0 if not page else 0.8}</priority>\n  </url>""")
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{chr(10).join(urls)}\n</urlset>"""
    return Response(content=xml, media_type="application/xml")

# --- TEMPLATE CONTEXT DEPENDENCY (FIXED) ---

BOOTSTRAP_CDN = '<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet" integrity="sha384-QWTKZyjpPEjISv5WaRU9OFeRpok6YctnYmDr5pNlyT2bRjXh0JMhjY6hW+ALEwIH" crossorigin="anonymous">'
BOOTSTRAP_JS = '<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js" integrity="sha384-YvpcrYf0tY3lHB60NNkmXc5s9fDVZLESaAA55NDzOxhy9GkcIdslK1eN7N6jIeHz" crossorigin="anonymous"></script>'

def get_hreflang_tags(request: Request, locale: str = Depends(get_current_locale)) -> List[Dict]:
    """Generate hreflang tags for SEO"""
    tags = []
    current_path = request.url.path
    
    base_path = current_path.replace(f"/{locale}", "", 1) or "/"
    
    for lang in config.SUPPORTED_LOCALES:
        lang_path = f"/{lang}{base_path}".replace("//", "/")
        tags.append({
            "rel": "alternate",
            "hreflang": lang,
            "href": str(request.url.replace(path=lang_path))
        })
    
    default_path = f"/{config.DEFAULT_LOCALE}{base_path}".replace("//", "/")
    tags.append({
        "rel": "alternate",
        "hreflang": "x-default",
        "href": str(request.url.replace(path=default_path))
    })
    
    return tags

def get_lang_url_generator(request: Request, locale: str) -> Callable[[str], str]:
    """
    Returns a function that can generate a URL for a different language,
    preserving the current page path. This is passed to the template context.
    """
    # Get the path without the current locale prefix (e.g., /en/about -> /about)
    base_path = request.url.path.replace(f"/{locale}", "", 1) or "/"
    if not base_path.startswith("/"):
        base_path = "/" + base_path

    def get_lang_url(new_locale: str) -> str:
        """
        Constructs the full URL for the given new_locale.
        This is the actual function that will be called from the Jinja2 template.
        """
        # Reconstruct the path for the new locale (e.g., /fr/about)
        new_path = f"/{new_locale}{base_path}".replace("//", "/")
        return str(request.url.replace(path=new_path))

    return get_lang_url

async def get_common_context(
    request: Request,
    translator: Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale),
    hreflang_tags: List = Depends(get_hreflang_tags)
) -> Dict:
    """Get common template context"""
    return {
        "request": request,
        "ADSENSE_SCRIPT": config.ADSENSE_SCRIPT, 
        "_": translator,
        "locale": locale,
        "hreflang_tags": hreflang_tags,
        "current_year": datetime.now(timezone.utc).year,
        "RTL_LOCALES": config.RTL_LOCALES,
        "LOCALE_TO_FLAG_CODE": config.LOCALE_TO_FLAG_CODE,
        "BOOTSTRAP_CDN": BOOTSTRAP_CDN,
        "BOOTSTRAP_JS": BOOTSTRAP_JS,
        "config": config,
        "get_lang_url": get_lang_url_generator(request, locale) # FIX: Add the URL generator function to the context
    }

# --- LOCALIZED ROUTES (i18n_router) ---

# 🟢 FIX: Parameters reordered to prevent SyntaxError
# Required arguments (no default/Path(...)) must come before optional arguments (Path(...), Depends(...), None)

@i18n_router.get("/", response_class=HTMLResponse)
async def index(
    locale: str = Path(..., description="The language code"),
    common_context: Dict = Depends(get_common_context)
):
    """Homepage"""
    return templates.TemplateResponse("index.html", common_context)

@i18n_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    locale: str = Path(..., description="The language code"),
    common_context: Dict = Depends(get_common_context)
):
    """Dashboard page"""
    return templates.TemplateResponse("dashboard.html", common_context)

@i18n_router.get("/about", response_class=HTMLResponse)
async def about(
    locale: str = Path(..., description="The language code"),
    common_context: Dict = Depends(get_common_context)
):
    """About page"""
    return templates.TemplateResponse("about.html", common_context)

@i18n_router.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(
    short_code: str, # REQUIRED
    background_tasks: BackgroundTasks, # REQUIRED
    locale: str = Path(..., description="The language code"), # OPTIONAL/DEFAULTED
    common_context: Dict = Depends(get_common_context) # OPTIONAL/DEFAULTED
):
    """Preview page with metadata and security warning"""
    translator = common_context["_"]
    try:
        link = await db_get_link(short_code)
        if not link:
            raise ResourceNotFoundException(translator("link_not_found")) 
        
        long_url = link["long_url"]
        safe_href_url = long_url if long_url.startswith(("http://", "https://")) else f"https://{long_url}"
        
        summary_status = link.get("summary_status", "pending")
        summary = link.get("summary_text")
        meta_description = link.get("meta_description")

        if summary_status == "complete" and summary:
            display_description = summary
        elif summary_status in ["pending", "in_progress"]:
            display_description = translator("preview_summary_pending")
        elif summary_status == "failed":
            display_description = translator("preview_summary_failed")
        else:
            display_description = meta_description or translator("no_description")
        
        context = {
            **common_context, 
            "short_code": short_code, 
            "escaped_long_url_href": html.escape(safe_href_url, quote=True),
            "escaped_long_url_display": html.escape(long_url),
            "meta_title": html.escape(link.get("meta_title") or translator("no_title")),
            "meta_description": html.escape(display_description),
            "meta_image_url": html.escape(link.get("meta_image") or "", quote=True),
            "has_image": bool(link.get("meta_image"))
        }
        
        return templates.TemplateResponse("preview.html", context)
    
    except (ResourceNotFoundException, ResourceExpiredException) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error in preview for {short_code}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=translator("preview_error"))

@i18n_router.get("/preview/{short_code}/redirect", response_class=RedirectResponse)
async def continue_to_link(
    short_code: str, # REQUIRED
    locale: str = Path(..., description="The language code"), # OPTIONAL/DEFAULTED
    translator: Callable = Depends(get_translator) # OPTIONAL/DEFAULTED
):
    """Continue to final destination (Click increment logic requires refactoring)"""
    try:
        link = await db_get_link(short_code)
        if not link:
            raise ResourceNotFoundException(translator("link_not_found"))
        long_url = link["long_url"]
        
        if not long_url.startswith(("http://", "https://")):
            long_url = f"https://{long_url}"
        return RedirectResponse(url=long_url, status_code=status.HTTP_302_FOUND)
    except (ResourceNotFoundException, ResourceExpiredException) as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error redirecting {short_code}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=translator("redirect_error"))

@i18n_router.get("/stats/{short_code}", response_class=HTMLResponse)
@limiter.limit(config.RATE_LIMIT_STATS)
async def stats(
    request: Request, # REQUIRED (Note: Request is often treated as required and usually placed first)
    short_code: str, # REQUIRED
    locale: str = Path(..., description="The language code"), # OPTIONAL/DEFAULTED
    common_context: Dict = Depends(get_common_context), # OPTIONAL/DEFAULTED
):
    """Statistics page"""
    translator = common_context["_"]
    try:
        link = await db_get_link(short_code)
        if not link:
            raise ResourceNotFoundException(translator("link_not_found"))
        context = {**common_context, "link": link}
        return templates.TemplateResponse("stats.html", context)
    except ResourceNotFoundException as e:
        raise HTTPException(status_code=e.status_code, detail=e.detail)
    except Exception as e:
        logger.error(f"Error fetching stats for {short_code}: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=translator("stats_error"))

# app.py

@i18n_router.get("/terms", response_class=HTMLResponse)
async def terms_of_service(
    locale: str = Path(..., description="The language code"),
    common_context: Dict = Depends(get_common_context)
):
    """Terms of Service page"""
    return templates.TemplateResponse("terms.html", common_context)


@i18n_router.get("/delete/{short_code}", response_class=HTMLResponse)
async def delete_link(
    short_code: str, # REQUIRED
    locale: str = Path(..., description="The language code"), # OPTIONAL/DEFAULTED
    token: Optional[str] = None, # OPTIONAL/DEFAULTED
    common_context: Dict = Depends(get_common_context) # OPTIONAL/DEFAULTED
):
    """Delete link page"""
    translator = common_context["_"]
    if not token:
        context = {"success": False, "message": translator("token_missing"), **common_context}
        return templates.TemplateResponse("delete_status.html", context)
    try:
        # The db_delete_link function now raises exceptions on failure, 
        # so we don't need to check its return value.
        await db_delete_link(short_code, token)
        context = {"success": True, "message": translator("delete_success"), **common_context}
    except ResourceNotFoundException:
        context = {"success": False, "message": translator("link_not_found"), **common_context}
    except ValueError:
        # Raised by db_delete_link on invalid token
        context = {"success": False, "message": translator("token_invalid"), **common_context} 
    except Exception as e:
        logger.error(f"Error deleting {short_code}: {e}")
        context = {"success": False, "message": translator("delete_error"), **common_context}
    return templates.TemplateResponse("delete_status.html", context)


# --- APPLICATION MOUNTING ---

app.include_router(api_router)
app.include_router(web_router)
app.mount("/{locale}", i18n_router, name="localized")


# --- GLOBAL ERROR HANDLER ---

def is_localized_route(path: str) -> bool:
    if not path.startswith('/'): return False
    segments = path.split('/')
    if len(segments) < 2: return False
    return segments[1] in config.SUPPORTED_LOCALES 

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    if exc.status_code in [status.HTTP_404_NOT_FOUND, status.HTTP_410_GONE] and is_localized_route(request.url.path):
        try:
            locale = request.url.path.split('/')[1]
            if locale not in config.SUPPORTED_LOCALES: locale = config.DEFAULT_LOCALE
        except:
            locale = config.DEFAULT_LOCALE
            
        translator = lambda key: get_translation(locale, key)
        
        # 🟢 FIX: Explicitly pass datetime/timezone to the error handler context
        context = {"request": request, "status_code": exc.status_code, "message": translator(exc.detail), 
                   "_": translator, "locale": locale, "BOOTSTRAP_CDN": BOOTSTRAP_CDN, "BOOTSTRAP_JS": BOOTSTRAP_JS,
                   "current_year": datetime.now(timezone.utc).year, 
                   "RTL_LOCALES": config.RTL_LOCALES,
                   "datetime": datetime,
                   "timezone": timezone}
        
        return templates.TemplateResponse("error.html", context, status_code=exc.status_code)

    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail or get_translation(get_browser_locale(request), "generic_error_message")})


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True, log_level="info")
