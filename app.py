
import uvicorn
import os
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import PlainTextResponse
from datetime import date

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
app.mount("/assets", StaticFiles(directory="assets"), name="assets")
templates = Jinja2Templates(directory="templates")

# This function is kept ONLY for generating the reference tables on the server.
def to_bijective_base6(n: int) -> str:
    if n <= 0: return "(N/A)"
    chars = "123456"
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, 6)
        result.append(chars[remainder])
    return "".join(reversed(result))

@app.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/robots.txt", response_class=PlainTextResponse)
def robots():
    return """# For all crawlers
User-agent: *
Disallow:

# Yandex-specific directive for the main mirror
Host: https://base6.art

# Sitemap location
Sitemap: https://base6.art/sitemap.xml
"""

@app.get("/sitemap.xml")
def sitemap():
    base_url = "https://base6.art"
    supported_langs = ["en", "ru", "de", "fr", "he", "ar", "zh", "ja"]  # Keep this in sync with your frontend
    today = date.today().isoformat()
    
    xml_content = '<?xml version="1.0" encoding="UTF-8"?>\n'
    xml_content += '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
    xml_content += '  <url>\n'
    xml_content += f'    <loc>{base_url}/</loc>\n'
    xml_content += f'    <lastmod>{today}</lastmod>\n'
    xml_content += '    <changefreq>monthly</changefreq>\n'
    xml_content += '    <priority>1.0</priority>\n'
    # Add x-default for users whose language is not supported
    xml_content += f'    <xhtml:link rel="alternate" hreflang="x-default" href="{base_url}/?lang=en"/>\n'
    for lang in supported_langs:
        xml_content += f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{base_url}/?lang={lang}"/>\n'
    xml_content += '  </url>\n'
    xml_content += '</urlset>'
    
    return Response(content=xml_content, media_type="application/xml")

@app.get("/locales/{lang}.json")
async def get_locale(lang: str):
    file_path = os.path.join("locales", f"{lang}.json")
    if os.path.exists(file_path):
        return FileResponse(file_path)
    return {"error": "Language not found"}, 404

@app.get("/get-tables")
async def get_tables():
    table_size = 24
    header = [to_bijective_base6(i) for i in range(1, table_size + 1)]
    add_table = [[to_bijective_base6(i + j) for j in range(1, table_size + 1)] for i in range(1, table_size + 1)]
    mul_table = [[to_bijective_base6(i * j) for j in range(1, table_size + 1)] for i in range(1, table_size + 1)]
    return {"header": header, "addition": add_table, "multiplication": mul_table}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
