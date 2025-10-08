import asyncio
import logging
import secrets
from datetime import date, datetime, timezone, timedelta

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

import database
from encoding import decode_id, encode_id
from i18n import TRANSLATIONS, DEFAULT_LANGUAGE, get_translator
from models import LinkBase, LinkResponse, ErrorResponse, TTL

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

TTL_MAP = {
    TTL.ONE_HOUR: timedelta(hours=1),
    TTL.ONE_DAY: timedelta(days=1),
    TTL.ONE_WEEK: timedelta(weeks=1),
}


# --- UI Routes ---

@ui_router.get("/", include_in_schema=False)
async def redirect_to_default_lang(request: Request):
    """Redirects the root path to the default language."""
    lang = DEFAULT_LANGUAGE

    # 1. Prioritize the language cookie set by the user.
    user_lang_cookie = request.cookies.get("lang")
    if user_lang_cookie and user_lang_cookie in TRANSLATIONS:
        lang = user_lang_cookie
    else:
        # 2. Fallback to browser's Accept-Language header for a good first-time experience.
        accept_language = request.headers.get("accept-language")
        if accept_language:
            browser_lang = accept_language.split(",")[0].split("-")[0].lower()
            if browser_lang in TRANSLATIONS:
                lang = browser_lang

    return RedirectResponse(url=f"/ui/{lang}")


@ui_router.get(
    "/ui/{lang_code:str}",
    response_class=HTMLResponse,
    summary="Serve Frontend UI"
)
async def read_root(request: Request, lang_code: str):
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    # Pass the translator function to the template context
    translator = get_translator(lang_code)
    return templates.TemplateResponse("index.html", {"request": request, "_": translator, "lang_code": lang_code})


@ui_router.get(
    "/ui/{lang_code:str}/about",
    response_class=HTMLResponse,
    summary="Serve About Page"
)
async def read_about(request: Request, lang_code: str):
    """Serves the about page for a given language."""
    if lang_code not in TRANSLATIONS and lang_code != DEFAULT_LANGUAGE:
        raise HTTPException(status_code=404, detail="Language not supported")

    translator = get_translator(lang_code)
    return templates.TemplateResponse("about.html", {"request": request, "_": translator, "lang_code": lang_code})


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


@ui_router.get("/sitemap.xml", include_in_schema=False)
async def sitemap():
    today = date.today().isoformat()
    now = datetime.now(tz=timezone.utc)
    urlset = []
    base_url = "https://shortlinks.art"

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

    # About Page
    urlset.append(f"""  <url>
    <loc>{base_url}/ui/en/about/</loc>
    <lastmod>{today}</lastmod>
    <changefreq>yearly</changefreq>
    <priority>0.8</priority>
{generate_hreflang_links("/ui/{lang}/about/")}
  </url>""")

    # 2. Add an entry for each active short link
    def get_active_links():
        with database.get_db_connection() as conn:
            return conn.execute("SELECT id FROM links WHERE expires_at IS NULL OR expires_at > ?", (now,)).fetchall()

    active_links = await asyncio.to_thread(get_active_links)

    for link in active_links:
        short_code = encode_id(link['id'])
        urlset.append(f"""  <url>
    <loc>{base_url}/{short_code}</loc>
    <changefreq>never</changefreq>
    <priority>0.5</priority>
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
async def create_short_link(link_data: LinkBase, request: Request):
    """
    Creates a new short link from a long URL.

    - **ID Reuse**: It will first try to reuse an expired ID to keep codes short.
    - **TTL**: Links can be set to expire after a specific duration.
    """
    
    def db_insert():
        # Calculate the expiration datetime
        if link_data.ttl == TTL.NEVER:
            expires_at = None
        else:
            expires_at = datetime.now(tz=timezone.utc) + TTL_MAP[link_data.ttl]
        deletion_token = secrets.token_urlsafe(16)
            
        with database.get_db_connection() as conn:
            cursor = conn.execute(
                "INSERT INTO links (long_url, expires_at, deletion_token) VALUES (?, ?, ?)",
                (str(link_data.long_url), expires_at, deletion_token)
            )
            new_id = cursor.lastrowid
            conn.commit()
            return new_id, expires_at, deletion_token

    try:
        new_id, expires_at, deletion_token = await asyncio.to_thread(db_insert)
        short_code = encode_id(new_id)
        canonical_url = f"https://shortlinks.art/{short_code}"
        resource_location = canonical_url # The Location header should also be the canonical URL

        # Prepare the response object that matches the LinkResponse model
        response_content = {
            "short_url": str(canonical_url),
            "long_url": str(link_data.long_url),
            "expires_at": expires_at.isoformat() if expires_at else None,
            "deletion_token": deletion_token,
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
async def get_link_details(short_code: str, request: Request):
    """
    Retrieves the details of a short link, such as the original URL and its
    expiration time, without performing a redirect.
    """
    translator = get_translator()  # Defaults to 'en' for API responses
    # The ValueError from an invalid short_code is now handled by the exception handler
    url_id = decode_id(short_code)
    if url_id is None:
        # This handles cases where the short_code is malformed or invalid
        raise HTTPException(status_code=404, detail=translator("Short link not found"))
    
    def db_select():
        with database.get_db_connection() as conn:
            return conn.execute("SELECT long_url, expires_at, deletion_token FROM links WHERE id = ?", (url_id,)).fetchone()
            
    record = await asyncio.to_thread(db_select)
    if not record:
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Check for expiration but do not delete it here (let the background task handle it)
    expires_at = record["expires_at"]
    if expires_at and datetime.now(timezone.utc) > expires_at:
        raise HTTPException(status_code=404, detail=translator("Short link has expired"))

    return {
        "short_url": f"https://shortlinks.art/{short_code}",  # Use canonical URL
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
async def delete_short_link(short_code: str, request: Request):
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

    url_id = decode_id(short_code)
    if url_id is None:
        translator = get_translator()
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    def db_delete():
        return database.delete_link_by_id_and_token(url_id, token)

    rows_deleted = await asyncio.to_thread(db_delete)

    if rows_deleted == 0:
        translator = get_translator()
        raise HTTPException(status_code=404, detail=translator("Short link not found"))

    # Return a 204 No Content response, which is standard for successful deletions.
    return Response(status_code=204)