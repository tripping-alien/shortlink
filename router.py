import asyncio
import logging
import secrets
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from hashids import Hashids

import database
from encoding import decode_id, encode_id, get_hashids
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

    # Use the browser's Accept-Language header to provide a good first-time experience.
    accept_language = request.headers.get("accept-language")
    if accept_language: # e.g., "fr-CH, fr;q=0.9, en;q=0.8, de;q=0.7, *;q=0.5"
        # Parse the header to find the best match based on user preference.
        languages = []
        for lang_part in accept_language.split(','):
            parts = lang_part.strip().split(';')
            lang_code = parts[0].split('-')[0].lower()
            q = 1.0
            if len(parts) > 1 and parts[1].startswith('q='):
                try:
                    q = float(parts[1][2:])
                except ValueError:
                    pass
            languages.append((lang_code, q))
        
        # Sort by quality value, descending
        languages.sort(key=lambda x: x[1], reverse=True)

        # Find the first supported language in the user's preferred list
        for preferred_lang, _ in languages:
            if preferred_lang in TRANSLATIONS:
                lang = preferred_lang
                break

    return RedirectResponse(url=f"/ui/{lang}/index")


@ui_router.get(
    "/ui/{lang_code:str}/index",
    response_class=HTMLResponse,
    summary="Serve Frontend UI"
)
async def read_root(request: Request, lang_code: str):
    """
    Serves the main index page for a given language.
    """
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    translator = get_translator(lang_code)
    return templates.TemplateResponse("index.html", {"request": request, "_": translator, "lang_code": lang_code})


@ui_router.get("/health", response_class=HTMLResponse, summary="Health Check", tags=["Monitoring"])
async def health_check(request: Request):
    """
    Performs a deep health check on the application and its dependencies,
    and renders an HTML status page.
    """
    health_status = {
        "status": "ok",
        "services": {}
    }
    status_code = 200

    # 1. Check Translation System
    if TRANSLATIONS and len(TRANSLATIONS) > 0:
        health_status["services"]["translations"] = "ok"
    else:
        health_status["services"]["translations"] = "error"
        health_status["status"] = "error"
        status_code = 503

    # 2. Check Database Connection
    try:
        with database.get_db_connection() as conn:
            conn.execute("SELECT 1")
        health_status["services"]["database_connection"] = "ok"
    except Exception:
        health_status["services"]["database_connection"] = "error"
        health_status["status"] = "error"
        status_code = 503

    context = {
        "request": request,
        "overall_status": health_status["status"],
        "services": health_status["services"],
        "timestamp": datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    }
    return templates.TemplateResponse("health.html", context, status_code=status_code)


@ui_router.get("/robots.txt", include_in_schema=False)
async def robots_txt(settings: Settings = Depends(get_settings)):
    """
    Provides a modern, explicit robots.txt file to guide web crawlers.
    """
    content = """User-agent: *
Disallow: /api/
Disallow: /get/
Disallow: /health
Sitemap: {settings.base_url}/sitemap.xml
"""
    return Response(content=content, media_type="text/plain")


@ui_router.get("/sitemap.xml", include_in_schema=False)
async def sitemap(settings: Settings = Depends(get_settings), hashids: Hashids = Depends(get_hashids)):
    today = date.today().isoformat()
    now = datetime.now(tz=timezone.utc)
    urlset = []
    base_url = str(settings.base_url).rstrip('/')

    # Generate hreflang links for a given path (e.g., "/ui/{lang}/")
    def generate_hreflang_links(path_template: str) -> str:
        links = []
        for code in TRANSLATIONS.keys():
            links.append(f'    <xhtml:link rel="alternate" hreflang="{code}" href="{base_url}{path_template.format(lang=code)}"/>')
        # Add x-default for the default language
        links.append(f'    <xhtml:link rel="alternate" hreflang="x-default" href="{base_url}{path_template.format(lang=DEFAULT_LANGUAGE)}"/>')
        return "\n".join(links)

    # 1. Add an entry for each supported language homepage
    # We only need to create one entry for each "page" and list the language alternatives within it.
    
    # Homepage
    urlset.append(f"""  <url>
    <loc>{base_url}/ui/en/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>monthly</changefreq>
    <priority>1.0</priority>
{generate_hreflang_links("/ui/{lang}/")}
  </url>""")

    # 2. Add an entry for each active short link
    active_links = await asyncio.to_thread(database.get_all_active_links, now)

    for link in active_links:
        short_code = encode_id(link['id'], hashids)
        urlset.append(f"""  <url>
    <loc>{base_url}/{short_code}</loc>
    <changefreq>never</changefreq>
    <priority>0.5</priority>
  </url>""")
        # Also add the preview page to the sitemap
        urlset.append(f"""  <url>
    <loc>{base_url}/get/{short_code}</loc>
    <changefreq>never</changefreq>
    <priority>0.4</priority>
  </url>""")

    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:xhtml="http://www.w3.org/1999/xhtml">
{"".join(urlset)}
</urlset>
"""
    return Response(content=xml_content, media_type="application/xml")


# --- API Routes ---

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
@limiter.limit("10/minute")
async def create_short_link(link_data: LinkBase, request: Request, settings: Settings = Depends(get_settings), hashids: Hashids = Depends(get_hashids)):
    """
    Creates a new short link from a long URL.

    - **ID Reuse**: It will first try to reuse an expired ID to keep codes short.
    - **TTL**: Links can be set to expire after a specific duration.
    """
    
    # Calculate the expiration datetime
    expires_at = None
    if link_data.ttl != TTL.NEVER:
        expires_at = datetime.now(tz=timezone.utc) + TTL_MAP[link_data.ttl]
    deletion_token = secrets.token_urlsafe(16)

    try:
        new_id = await asyncio.to_thread(database.create_link, str(link_data.long_url), expires_at, deletion_token)
        short_code = encode_id(new_id, hashids)

        # Define both the preview and direct redirect URLs
        base_url = str(settings.base_url).rstrip('/')
        preview_url = f"{base_url}/get/{short_code}"
        redirect_url = f"{base_url}/{short_code}"
        resource_location = preview_url # The Location header should point to the new resource

        # Prepare the response object that matches the LinkResponse model
        response_content = {
            "short_url": str(preview_url), # The primary URL is now the safe preview link
            "long_url": str(link_data.long_url),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "deletion_token": deletion_token,
            "links": [
                {
                    "rel": "preview",
                    "href": str(preview_url),
                    "method": "GET"
                },
                {
                    "rel": "redirect",
                    "href": str(redirect_url),
                    "method": "GET"
                },
                {
                    "rel": "self",
                    "href": str(request.url_for('get_link_details', short_code=short_code)),
                    "method": "GET"
                },
                {
                    "rel": "delete",
                    "href": str(request.url_for('delete_short_link', short_code=short_code)),
                    "method": "DELETE"
                }
            ]
        }

        # Return 201 Created with a Location header and the response body
        return JSONResponse(
            status_code=201,
            content=response_content,
            headers={"Location": resource_location}
        )
    except Exception as e:
        logger.error(f"Database insert failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to create link in the database.")


@api_router.get(
    "/links/{short_code}",
    response_model=LinkResponse,
    summary="Get Link Details",
    name="get_link_details",  # Add a name to the route so we can reference it
    responses={404: {"model": ErrorResponse, "description": "Not Found: The link does not exist or has expired."}}
)
async def get_link_details(short_code: str, request: Request, settings: Settings = Depends(get_settings), hashids: Hashids = Depends(get_hashids)):
    """
    Retrieves the details of a short link, such as the original URL and its
    expiration time, without performing a redirect.
    """
    translator = get_translator()  # Defaults to 'en' for API responses
    # The ValueError from an invalid short_code is now handled by the exception handler
    url_id = decode_id(short_code, hashids)
    if url_id is None:
        # This handles cases where the short_code is malformed or invalid
        raise HTTPException(status_code=404, detail=translator("Short link not found"))
    
    record = await asyncio.to_thread(database.get_link_by_id, url_id)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Check for expiration but do not delete it here (let the background task handle it)
    expires_at = record["expires_at"]
    if expires_at and datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    base_url = str(settings.base_url).rstrip('/')
    return {
        "short_url": f"{base_url}/get/{short_code}",  # Return the preview URL as the canonical one
        "long_url": record["long_url"],
        "expires_at": record["expires_at"],
        "deletion_token": record["deletion_token"],
        "links": [
            {
                "rel": "self",
                "href": str(request.url_for('get_link_details', short_code=short_code)),
                "method": "GET"
            },
            {
                "rel": "delete",
                "href": str(request.url_for('delete_short_link', short_code=short_code)),
                "method": "DELETE"
            }
        ]
    }


@api_router.delete(
    "/links/{short_code}",
    status_code=204,
    summary="Delete Link",
    name="delete_short_link",  # Add a name to the route
    responses={404: {"model": ErrorResponse, "description": "Not Found: The link does not exist."}}
)
async def delete_short_link(short_code: str, request: Request, hashids: Hashids = Depends(get_hashids)):
    """
    Permanently deletes a short link. Requires the secret deletion token,
    which is provided when the link is created.
    """
    try:
        body = await request.json()
        token = body.get("deletion_token")
        if not token:
            raise HTTPException(status_code=400, detail="Deletion token is required.")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid request body. Expecting JSON with 'deletion_token'.")

    url_id = decode_id(short_code, hashids)
    if url_id is None:
        translator = get_translator()
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # For enhanced security, first fetch the record, then perform a constant-time comparison
    # on the token. This prevents potential timing attacks.
    record = await asyncio.to_thread(database.get_link_by_id, url_id)
    
    if not record or not secrets.compare_digest(token, record["deletion_token"]):
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # If the token is valid, proceed with deletion.
    await asyncio.to_thread(database.delete_link_by_id_and_token, url_id, token)

    # Return a 204 No Content response, which is standard for successful deletions.
    return Response(status_code=204)