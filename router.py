import asyncio
import logging
import secrets
from datetime import datetime, timezone
import xml.etree.ElementTree as ET

from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from starlette.staticfiles import StaticFiles

import database
# Retained for dependency resolution, though not used for primary link generation
from encoding import get_hashids 
from i18n import TRANSLATIONS, DEFAULT_LANGUAGE, get_translator
from models import LinkBase, LinkResponse, ErrorResponse
from config import TTL, TTL_MAP, Settings, get_settings
from limiter import limiter

# --- Router Setup ---

# API Router for versioning and organization.
api_router = APIRouter(
    prefix="/api/v1",
    tags=["Links"],  # Group endpoints in the docs
)

# UI Router for serving HTML pages.
ui_router = APIRouter(
    tags=["UI"],
)

# Mount static files and templates
templates = Jinja2Templates(directory="templates")

# --- Constants and Logger ---

logger = logging.getLogger(__name__)

# --- UI Routes ---

@ui_router.get("/", include_in_schema=False)
async def redirect_to_default_lang(request: Request):
    """Redirects the root path to the default language."""
    lang = DEFAULT_LANGUAGE
    accept_language = request.headers.get("accept-language")
    if accept_language: 
        languages = []
        for lang_part in accept_language.split(','):
            parts = lang_part.strip().split(';')
            lang_code = parts[0].split('-')[0].lower()
            q = 1.0
            if len(parts) > 1 and parts[1].startswith('q='):
                try: q = float(parts[1][2:])
                except ValueError: pass
            languages.append((lang_code, q))
        languages.sort(key=lambda x: x[1], reverse=True)
        for preferred_lang, _ in languages:
            if preferred_lang in TRANSLATIONS:
                lang = preferred_lang
                break
    
    # Correctly redirects to the localized route using the detected language
    return RedirectResponse(url=f"/ui/{lang}/index", status_code=307)


@ui_router.get(
    "/ui/{lang_code:str}/index",
    response_class=HTMLResponse,
    summary="Serve Frontend UI (Index Page)",
    name="home_page" # <-- FIX: This is the name your layout.html expects
)
async def read_root(request: Request, lang_code: str, settings: Settings = Depends(get_settings)):
    """Serves the main index page for a given language."""
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    translator = get_translator(lang_code)
    return templates.TemplateResponse("index.html", {
        "request": request,
        "_": translator,
        "lang_code": lang_code,
        "base_url": str(settings.base_url).rstrip('/')
    })

# Add placeholder/example routes for the rest of your header links
@ui_router.get(
    "/ui/{lang_code:str}/about",
    response_class=HTMLResponse,
    summary="Serve About Page",
    name="about_page" # <-- FIX: Template will now find this
)
async def about_page(request: Request, lang_code: str, settings: Settings = Depends(get_settings)):
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")
    translator = get_translator(lang_code)
    # NOTE: You need a template named 'about.html'
    return templates.TemplateResponse("about.html", {
        "request": request,
        "_": translator,
        "lang_code": lang_code,
        "base_url": str(settings.base_url).rstrip('/')
    })

@ui_router.get(
    "/ui/{lang_code:str}/dashboard",
    response_class=HTMLResponse,
    summary="Serve Dashboard",
    name="dashboard_page" # <-- FIX: Template will now find this
)
async def dashboard_page(request: Request, lang_code: str, settings: Settings = Depends(get_settings)):
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")
    translator = get_translator(lang_code)
    # NOTE: You need a template named 'dashboard.html'
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "_": translator,
        "lang_code": lang_code,
        "base_url": str(settings.base_url).rstrip('/')
    })

# The rest of the UI routes follow...

@ui_router.get("/health", response_class=HTMLResponse, summary="Health Check", tags=["Monitoring"])
async def health_check(request: Request):
    """Performs a deep health check."""
    health_status = {"status": "ok", "services": {}}
    status_code = 200

    if TRANSLATIONS and len(TRANSLATIONS) > 0:
        health_status["services"]["translations"] = "ok"
    else:
        health_status["services"]["translations"] = "error"
        health_status["status"] = "error"
        status_code = 503

    try:
        database.get_db_connection()
        health_status["services"]["database_connection"] = "ok"
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        health_status["services"]["database_connection"] = "error"
        health_status["status"] = "error"
        status_code = 503

    return JSONResponse(content=health_status, status_code=status_code)


@ui_router.get("/robots.txt", include_in_schema=False)
async def robots_txt(settings: Settings = Depends(get_settings)):
    """Provides a modern, explicit robots.txt file."""
    content = f"""User-agent: *
Disallow: /api/
Disallow: /get/
Disallow: /health
Sitemap: {settings.base_url}/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@ui_router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(settings: Settings = Depends(get_settings)):
    """Generates a sitemap.xml."""
    now = datetime.now(tz=timezone.utc)
    base_url = str(settings.base_url).rstrip('/')

    urlset = ET.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")

    # Homepage
    url_el = ET.SubElement(urlset, "url")
    ET.SubElement(url_el, "loc").text = f"{base_url}/ui/en/index"
    ET.SubElement(url_el, "lastmod").text = now.date().isoformat()
    ET.SubElement(url_el, "changefreq").text = "monthly"
    ET.SubElement(url_el, "priority").text = "1.0"

    # Active Links
    active_links = await asyncio.to_thread(database.get_all_active_links, now)

    for link in active_links:
        short_code = link['id']
        url_el = ET.SubElement(urlset, "url")
        ET.SubElement(url_el, "loc").text = f"{base_url}/get/{short_code}"
        ET.SubElement(url_el, "changefreq").text = "never"
        ET.SubElement(url_el, "priority").text = "0.4"

    xml_content = ET.tostring(urlset, encoding='unicode', method='xml')
    return Response(content=f'<?xml version="1.0" encoding="UTF-8"?>\n{xml_content}', media_type="application/xml")


# --- API Routes ---

@api_router.get("/translations/{lang_code}", include_in_schema=False)
async def get_translations(lang_code: str):
    """Provides a set of translated strings to the frontend JavaScript."""
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    return get_translator(lang_code).all_translations


@api_router.post(
    "/links",
    response_model=LinkResponse,
    status_code=201,
    summary="Create a new short link",
    responses={
        400: {"model": ErrorResponse, "description": "Bad Request: Invalid input or failed bot check."},
        500: {"model": ErrorResponse, "description": "Internal Server Error: Failed to create unique short code or database error."},
        422: {"model": ErrorResponse, "description": "Validation Error: The request body is malformed."},
    }
)
@limiter.limit("10/minute")
async def create_short_link(link_data: LinkBase, request: Request, settings: Settings = Depends(get_settings)):
    """
    Creates a new short link from a long URL.
    """
    
    # Calculate the expiration datetime
    expires_at = None
    if link_data.ttl != TTL.NEVER:
        expires_at = datetime.now(tz=timezone.utc) + TTL_MAP[link_data.ttl]
    deletion_token = secrets.token_urlsafe(16)

    try:
        # 1. Calls database.create_link, which handles ID generation and collision retry.
        short_code = await asyncio.to_thread(database.create_link, str(link_data.long_url), expires_at, deletion_token)

        if not short_code:
            logger.error("Short code was empty after database creation. Raising 500.")
            raise HTTPException(status_code=500, detail="Failed to generate a valid short code.")

        # 2. Build the response using the successfully generated short_code
        base_url = str(settings.base_url).rstrip('/')
        preview_url = f"{base_url}/get/{short_code}"
        redirect_url = f"{base_url}/{short_code}"
        resource_location = preview_url

        response_content = {
            "short_url": str(preview_url),
            "long_url": str(link_data.long_url),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "deletion_token": deletion_token,
            "links": [
                {"rel": "preview", "href": str(preview_url), "method": "GET"},
                {"rel": "redirect", "href": str(redirect_url), "method": "GET"},
                {"rel": "self", "href": str(request.url_for('get_link_details', short_code=short_code)), "method": "GET"},
                {"rel": "delete", "href": str(request.url_for('delete_short_link', short_code=short_code)), "method": "DELETE"}
            ]
        }

        return JSONResponse(
            status_code=201,
            content=response_content,
            headers={"Location": resource_location}
        )
    except RuntimeError as e:
        # Catch the specific error from database.py if MAX_RETRIES was hit.
        logger.error(f"Database insert failed (ID exhaustion): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"System failed to generate a unique short code: {e}")
    except Exception as e:
        # Catch other unexpected database or system errors (the original trace's final step)
        logger.error(f"Database insert failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create link in the database due to an unexpected error.")


@api_router.get(
    "/links/{short_code}",
    response_model=LinkResponse,
    summary="Get Link Details",
    name="get_link_details",
    responses={404: {"model": ErrorResponse, "description": "Not Found: The link does not exist or has expired."}}
)
async def get_link_details(short_code: str, request: Request, settings: Settings = Depends(get_settings)):
    """Retrieves the details of a short link."""
    translator = get_translator()
    
    record = await asyncio.to_thread(database.get_link_by_id, short_code)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    expires_at = record["expires_at"]
    if expires_at and datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    base_url = str(settings.base_url).rstrip('/')
    return {
        "short_url": f"{base_url}/get/{short_code}",
        "long_url": record["long_url"],
        "expires_at": record["expires_at"].isoformat() if record["expires_at"] else None,
        "deletion_token": record["deletion_token"],
        "links": [
            {"rel": "self", "href": str(request.url_for('get_link_details', short_code=short_code)), "method": "GET"},
            {"rel": "delete", "href": str(request.url_for('delete_short_link', short_code=short_code)), "method": "DELETE"}
        ]
    }


@api_router.delete(
    "/links/{short_code}",
    status_code=204,
    summary="Delete Link",
    name="delete_short_link",
    responses={404: {"model": ErrorResponse, "description": "Not Found: The link does not exist."}}
)
async def delete_short_link(short_code: str, request: Request):
    """Permanently deletes a short link."""
    translator = get_translator()
    
    try:
        body = await request.json()
        token = body.get("deletion_token")
        if not token:
            raise HTTPException(status_code=400, detail="Deletion token is required.")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body. Expecting JSON with 'deletion_token'.")

    record = await asyncio.to_thread(database.get_link_by_id, short_code)
    
    if not record or not secrets.compare_digest(token, record["deletion_token"]):
        raise HTTPException(status_code=404, detail=translator("Short link not found or token is invalid."))

    await asyncio.to_thread(database.delete_link_by_id_and_token, short_code, token)

    return Response(status_code=204)
