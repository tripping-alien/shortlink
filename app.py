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
import tempfile # Needed for robust firebase init

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

from fastapi import FastAPI, HTTPException, Request, Depends, Path
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

SUPPORTED_LOCALES = ["en", "es", "zh", "hi", "pt", "fr", "de", "ar", "ru", "he"]
DEFAULT_LOCALE = "en"
RTL_LOCALES = ["ar", "he"] # List of Right-to-Left languages

# UPDATED: Added new 'lang_name_xx' keys for flag alt text
translations = {
    "en": {
        "lang_name_en": "English", "lang_name_es": "Spanish", "lang_name_zh": "Chinese", "lang_name_hi": "Hindi", "lang_name_pt": "Portuguese", "lang_name_fr": "French", "lang_name_de": "German", "lang_name_ar": "Arabic", "lang_name_ru": "Russian", "lang_name_he": "Hebrew",
        "app_title": "Shortlinks.art - Fast & Simple URL Shortener",
        "meta_description_main": "Create free short links with previews. Shortlinks.art is a fast, simple URL shortener that offers custom expiration times and link previews.",
        "meta_keywords_main": "url shortener, link shortener, free url shortener, url shortener with preview, link shortener with preview, custom short link, expiring links, temporary links, short url, shorten link, fast url shortener, simple url shortener, shortlinks.art",
        "meta_description_og": "A fast, free, and simple URL shortener with link previews and custom expiration times.",
        "my_links_button": "My Links",
        "tagline": "A fast, simple URL shortener with link previews.",
        "create_link_heading": "Create a Short Link",
        "long_url_placeholder": "Enter your long URL (e.g., https://...)",
        "create_button": "Shorten",
        "advanced_options_button": "Advanced Options",
        "custom_code_label": "Custom code (optional)",
        "utm_tags_placeholder": "UTM tags (e.g., utm_source=twitter)",
        "ttl_label": "Expires after",
        "ttl_1h": "1 Hour",
        "ttl_24h": "24 Hours",
        "ttl_1w": "1 Week",
        "ttl_never": "Never",
        "result_short_link": "Short Link",
        "copy_button": "Copy",
        "result_stats_page": "Stats Page",
        "result_view_clicks": "View Clicks",
        "result_save_link_strong": "Save this link!",
        "result_save_link_text": "This is your unique deletion link. Keep it safe if you ever want to remove your shortlink.",
        "nav_home": "Home",
        "nav_about": "About",
        "language_switcher_label": "Select a language",
        "link_not_found": "Link not found",
        "link_expired": "Link expired",
        "invalid_url": "Invalid URL provided.",
        "custom_code_exists": "Custom code already exists",
        "id_generation_failed": "Could not generate unique short code.",
        "owner_id_required": "Owner ID is required",
        "token_missing": "Deletion token is missing",
        "delete_success": "Link successfully deleted.",
        "delete_invalid_token": "Invalid deletion token. Link was not deleted.",
        "js_enter_url": "Please enter a URL.",
        "js_error_creating": "Error creating short link",
        "js_error_server": "Failed to connect to the server.",
        "js_copied": "Copied!",
        "js_copy_failed": "Failed!",
    },
    "es": {
        "lang_name_en": "Inglés", "lang_name_es": "Español", "lang_name_zh": "Chino", "lang_name_hi": "Hindi", "lang_name_pt": "Portugués", "lang_name_fr": "Francés", "lang_name_de": "Alemán", "lang_name_ar": "Árabe", "lang_name_ru": "Ruso", "lang_name_he": "Hebreo",
        "app_title": "Shortlinks.art - Acortador de URL rápido y sencillo",
        "meta_description_main": "Cree enlaces cortos gratuitos con vistas previas. Shortlinks.art es un acortador de URL rápido y sencillo que ofrece vistas previas y tiempos de caducidad personalizados.",
        "meta_keywords_main": "acortador de url, acortador de enlaces, acortador de url gratuito, acortador de url con vista previa, enlace corto personalizado, enlaces que expiran, enlaces temporales, short url, acortar enlace, shortlinks.art",
        "meta_description_og": "Un acortador de URL rápido, gratuito y sencillo con vistas previas de enlaces y tiempos de caducidad personalizados.",
        "my_links_button": "Mis Enlaces",
        "tagline": "Un acortador de URL rápido y sencillo con vistas previas de enlaces.",
        "create_link_heading": "Crear un enlace corto",
        "long_url_placeholder": "Introduce tu URL larga (ej., https://...)",
        "create_button": "Acortar",
        "advanced_options_button": "Opciones Avanzadas",
        "custom_code_label": "Código personalizado (opcional)",
        "utm_tags_placeholder": "Etiquetas UTM (ej., utm_source=twitter)",
        "ttl_label": "Expira después de",
        "ttl_1h": "1 Hora",
        "ttl_24h": "24 Horas",
        "ttl_1w": "1 Semana",
        "ttl_never": "Nunca",
        "result_short_link": "Enlace Corto",
        "copy_button": "Copiar",
        "result_stats_page": "Página de Estadísticas",
        "result_view_clicks": "Ver Clics",
        "result_save_link_strong": "¡Guarda este enlace!",
        "result_save_link_text": "Este es tu enlace de eliminación único. Guárdalo bien si alguna vez quieres eliminar tu enlace corto.",
        "nav_home": "Inicio",
        "nav_about": "Acerca de",
        "language_switcher_label": "Seleccione un idioma",
        "link_not_found": "Enlace no encontrado",
        "link_expired": "El enlace ha caducado",
        "invalid_url": "La URL proporcionada no es válida.",
        "custom_code_exists": "Este código personalizado ya existe",
        "id_generation_failed": "No se pudo generar un código corto único.",
        "owner_id_required": "Se requiere ID de propietario",
        "token_missing": "Falta el token de eliminación",
        "delete_success": "Enlace eliminado con éxito.",
        "delete_invalid_token": "Token de eliminación no válido. El enlace no fue eliminado.",
        "js_enter_url": "Por favor, introduce una URL.",
        "js_error_creating": "Error al crear el enlace corto",
        "js_error_server": "No se pudo conectar al servidor.",
        "js_copied": "¡Copiado!",
        "js_copy_failed": "¡Falló!",
    },
    "zh": { 
        "lang_name_en": "英语", "lang_name_es": "西班牙语", "lang_name_zh": "简体中文", "lang_name_hi": "印地语", "lang_name_pt": "葡萄牙语", "lang_name_fr": "法语", "lang_name_de": "德语", "lang_name_ar": "阿拉伯语", "lang_name_ru": "俄语", "lang_name_he": "希伯来语",
        "app_title": "Shortlinks.art - 快速简洁的网址缩短服务",
        "meta_description_main": "创建带预览的免费短链接。Shortlinks.art 是一个快速、简单的网址缩短器，提供自定义过期时间和链接预览。",
        "meta_keywords_main": "网址缩短, 链接缩短, 免费网址缩短, 带预览的网址缩短, 自定义短链接, 过期链接, 临时链接, short url, 缩短链接, shortlinks.art",
        "meta_description_og": "一个快速、免费、简单的网址缩短器，带链接预览和自定义过期时间。",
        "my_links_button": "我的链接",
        "tagline": "一个快速、简单的网址缩短器，带链接预览。",
        "create_link_heading": "创建短链接",
        "long_url_placeholder": "输入您的长网址 (例如 https://...)",
        "create_button": "缩短",
        "advanced_options_button": "高级选项",
        "custom_code_label": "自定义代码 (可选)",
        "utm_tags_placeholder": "UTM 标签 (例如 utm_source=twitter)",
        "ttl_label": "过期时间",
        "ttl_1h": "1 小时",
        "ttl_24h": "24 小时",
        "ttl_1w": "1 周",
        "ttl_never": "从不",
        "result_short_link": "短链接",
        "copy_button": "复制",
        "result_stats_page": "统计页面",
        "result_view_clicks": "查看点击",
        "result_save_link_strong": "保存此链接！",
        "result_save_link_text": "这是您的专属删除链接。请妥善保管，以便将来删除您的短链接。",
        "nav_home": "首页",
        "nav_about": "关于",
        "language_switcher_label": "选择一种语言",
        "link_not_found": "链接未找到",
        "link_expired": "链接已过期",
        "invalid_url": "提供了无效的URL。",
        "custom_code_exists": "自定义代码已存在",
        "id_generation_failed": "无法生成唯一的短代码。",
        "owner_id_required": "需要所有者ID",
        "token_missing": "缺少删除令牌",
        "delete_success": "链接已成功删除。",
        "delete_invalid_token": "删除令牌无效。链接未被删除。",
        "js_enter_url": "请输入一个URL。",
        "js_error_creating": "创建短链接时出错",
        "js_error_server": "无法连接到服务器。",
        "js_copied": "已复制！",
        "js_copy_failed": "失败！",
    },
    "hi": {
        "lang_name_en": "अंग्रेज़ी", "lang_name_es": "स्पेनिश", "lang_name_zh": "चीनी", "lang_name_hi": "हिन्दी", "lang_name_pt": "पुर्तगाली", "lang_name_fr": "फ्रेंच", "lang_name_de": "जर्मन", "lang_name_ar": "अरबी", "lang_name_ru": "रूसी", "lang_name_he": "हिब्रू",
        "app_title": "Shortlinks.art - तेज़ और सरल यूआरएल शॉर्टनर",
        "meta_description_main": "प्रीव्यू के साथ मुफ़्त शॉर्ट लिंक बनाएं। Shortlinks.art एक तेज़, सरल यूआरएल शॉर्टनर है जो कस्टम समाप्ति समय और लिंक प्रीव्यू प्रदान करता है।",
        "meta_keywords_main": "यूआरएल शॉर्टनर, लिंक शॉर्टनर, मुफ़्त यूआरएल शॉर्टनर, प्रीव्यू के साथ यूआरएल शॉर्टनर, कस्टम शॉर्ट लिंक, एक्सपायरिंग लिंक, अस्थायी लिंक, शॉर्ट यूआरएल, शॉर्टन लिंक, shortlinks.art",
        "meta_description_og": "लिंक प्रीव्यू और कस्टम समाप्ति समय के साथ एक तेज़, मुफ़्त और सरल यूआरएल शॉर्टनर।",
        "my_links_button": "मेरे लिंक",
        "tagline": "लिंक प्रीव्यू के साथ एक तेज़, सरल यूआरएल शॉर्टनर।",
        "create_link_heading": "एक छोटा लिंक बनाएं",
        "long_url_placeholder": "अपना लंबा यूआरएल दर्ज करें (जैसे, https://...)",
        "create_button": "छोटा करें",
        "advanced_options_button": "उन्नत विकल्प",
        "custom_code_label": "कस्टम कोड (वैकल्पिक)",
        "utm_tags_placeholder": "UTM टैग (जैसे, utm_source=twitter)",
        "ttl_label": "इसके बाद समाप्त हो जाएगा",
        "ttl_1h": "1 घंटा",
        "ttl_24h": "24 घंटे",
        "ttl_1w": "1 सप्ताह",
        "ttl_never": "कभी नहीं",
        "result_short_link": "शॉर्ट लिंक",
        "copy_button": "कॉपी",
        "result_stats_page": "सांख्यिकी पृष्ठ",
        "result_view_clicks": "क्लिक देखें",
        "result_save_link_strong": "इस लिंक को सहेजें!",
        "result_save_link_text": "यह आपका अद्वितीय विलोपन लिंक है। यदि आप कभी भी अपना शॉर्टलिंक हटाना चाहते हैं तो इसे सुरक्षित रखें।",
        "nav_home": "होम",
        "nav_about": "बारे में",
        "language_switcher_label": "एक भाषा चुनें",
        "link_not_found": "लिंक नहीं मिला",
        "link_expired": "लिंक समाप्त हो गया है",
        "invalid_url": "अमान्य यूआरएल प्रदान किया गया।",
        "custom_code_exists": "कस्टम कोड पहले से मौजूद है",
        "id_generation_failed": "अद्वितीय शॉर्ट कोड उत्पन्न नहीं किया जा सका।",
        "owner_id_required": "मालिक आईडी की आवश्यकता है",
        "token_missing": "विलोपन टोकन गायब है",
        "delete_success": "लिंक सफलतापूर्वक हटा दिया गया।",
        "delete_invalid_token": "अमान्य विलोपन टोकन। लिंक हटाया नहीं गया।",
        "js_enter_url": "कृपया एक यूआरएल दर्ज करें।",
        "js_error_creating": "शॉर्ट लिंक बनाने में त्रुटि",
        "js_error_server": "सर्वर से कनेक्ट करने में विफल।",
        "js_copied": "कॉपी किया गया!",
        "js_copy_failed": "विफल!",
    },
    "pt": {
        "lang_name_en": "Inglês", "lang_name_es": "Espanhol", "lang_name_zh": "Chinês", "lang_name_hi": "Hindi", "lang_name_pt": "Português", "lang_name_fr": "Francês", "lang_name_de": "Alemão", "lang_name_ar": "Árabe", "lang_name_ru": "Russo", "lang_name_he": "Hebraico",
        "app_title": "Shortlinks.art - Encurtador de URL rápido e simples",
        "meta_description_main": "Crie links curtos gratuitos com pré-visualizações. Shortlinks.art é um encurtador de URL rápido e simples que oferece tempos de expiração personalizados e pré-visualizações de links.",
        "meta_keywords_main": "encurtador de url, encurtador de link, encurtador de url gratuito, encurtador de url com pré-visualização, link curto personalizado, links que expiram, links temporários, short url, encurtar link, shortlinks.art",
        "meta_description_og": "Um encurtador de URL rápido, gratuito e simples com pré-visualizações de links e tempos de expiração personalizados.",
        "my_links_button": "Meus Links",
        "tagline": "Um encurtador de URL rápido e simples com pré-visualizações de links.",
        "create_link_heading": "Criar um link curto",
        "long_url_placeholder": "Digite sua URL longa (ex: https://...)",
        "create_button": "Encurtar",
        "advanced_options_button": "Opções Avançadas",
        "custom_code_label": "Código personalizado (opcional)",
        "utm_tags_placeholder": "Tags UTM (ex: utm_source=twitter)",
        "ttl_label": "Expira em",
        "ttl_1h": "1 Hora",
        "ttl_24h": "24 Horas",
        "ttl_1w": "1 Semana",
        "ttl_never": "Nunca",
        "result_short_link": "Link Curto",
        "copy_button": "Copiar",
        "result_stats_page": "Página de Estatísticas",
        "result_view_clicks": "Ver Cliques",
        "result_save_link_strong": "Salve este link!",
        "result_save_link_text": "Este é o seu link de exclusão exclusivo. Mantenha-o seguro se você quiser remover seu link curto.",
        "nav_home": "Início",
        "nav_about": "Sobre",
        "language_switcher_label": "Selecione um idioma",
        "link_not_found": "Link não encontrado",
        "link_expired": "O link expirou",
        "invalid_url": "URL fornecida é inválida.",
        "custom_code_exists": "O código personalizado já existe",
        "id_generation_failed": "Não foi possível gerar um código curto único.",
        "owner_id_required": "ID do proprietário é obrigatório",
        "token_missing": "Token de exclusão ausente",
        "delete_success": "Link excluído com sucesso.",
        "delete_invalid_token": "Token de exclusão inválido. O link não foi excluído.",
        "js_enter_url": "Por favor, insira uma URL.",
        "js_error_creating": "Erro ao criar link curto",
        "js_error_server": "Falha ao conectar ao servidor.",
        "js_copied": "Copiado!",
        "js_copy_failed": "Falhou!",
    },
    "fr": {
        "lang_name_en": "Anglais", "lang_name_es": "Espagnol", "lang_name_zh": "Chinois", "lang_name_hi": "Hindi", "lang_name_pt": "Portugais", "lang_name_fr": "Français", "lang_name_de": "Allemand", "lang_name_ar": "Arabe", "lang_name_ru": "Russe", "lang_name_he": "Hébreu",
        "app_title": "Shortlinks.art - Raccourcisseur d'URL rapide et simple",
        "meta_description_main": "Créez des liens courts gratuits avec aperçus. Shortlinks.art est un raccourcisseur d'URL rapide et simple qui offre des temps d'expiration personnalisés et des aperçus de liens.",
        "meta_keywords_main": "raccourcisseur d'url, raccourcisseur de lien, raccourcisseur d'url gratuit, raccourcisseur d'url avec aperçu, lien court personnalisé, liens expirants, liens temporaires, short url, raccourcir lien, shortlinks.art",
        "meta_description_og": "Un raccourcisseur d'URL rapide, gratuit et simple avec aperçus de liens et temps d'expiration personnalisés.",
        "my_links_button": "Mes Liens",
        "tagline": "Un raccourcisseur d'URL rapide et simple avec aperçus de liens.",
        "create_link_heading": "Créer un lien court",
        "long_url_placeholder": "Entrez votre URL longue (ex: https://...)",
        "create_button": "Raccourcir",
        "advanced_options_button": "Options Avancées",
        "custom_code_label": "Code personnalisé (optionnel)",
        "utm_tags_placeholder": "Tags UTM (ex: utm_source=twitter)",
        "ttl_label": "Expire après",
        "ttl_1h": "1 Heure",
        "ttl_24h": "24 Heures",
        "ttl_1w": "1 Semaine",
        "ttl_never": "Jamais",
        "result_short_link": "Lien Court",
        "copy_button": "Copier",
        "result_stats_page": "Page de Stats",
        "result_view_clicks": "Voir les Clics",
        "result_save_link_strong": "Sauvegardez ce lien !",
        "result_save_link_text": "C'est votre lien de suppression unique. Gardez-le en sécurité si vous souhaitez un jour supprimer votre lien court.",
        "nav_home": "Accueil",
        "nav_about": "À propos",
        "language_switcher_label": "Sélectionnez une langue",
        "link_not_found": "Lien non trouvé",
        "link_expired": "Le lien a expiré",
        "invalid_url": "URL fournie invalide.",
        "custom_code_exists": "Le code personnalisé existe déjà",
        "id_generation_failed": "Impossible de générer un code court unique.",
        "owner_id_required": "ID du propriétaire requis",
        "token_missing": "Jeton de suppression manquant",
        "delete_success": "Lien supprimé avec succès.",
        "delete_invalid_token": "Jeton de suppression non valide. Le lien n'a pas été supprimé.",
        "js_enter_url": "Veuillez entrer une URL.",
        "js_error_creating": "Erreur lors de la création du lien court",
        "js_error_server": "Échec de la connexion au serveur.",
        "js_copied": "Copié !",
        "js_copy_failed": "Échoué !",
    },
    "de": {
        "lang_name_en": "Englisch", "lang_name_es": "Spanisch", "lang_name_zh": "Chinesisch", "lang_name_hi": "Hindi", "lang_name_pt": "Portugiesisch", "lang_name_fr": "Französisch", "lang_name_de": "Deutsch", "lang_name_ar": "Arabisch", "lang_name_ru": "Russisch", "lang_name_he": "Hebräisch",
        "app_title": "Shortlinks.art - Schneller & einfacher URL-Shortener",
        "meta_description_main": "Erstellen Sie kostenlose Kurzlinks mit Vorschau. Shortlinks.art ist ein schneller, einfacher URL-Shortener, der benutzerdefinierte Ablaufzeiten und Link-Vorschauen bietet.",
        "meta_keywords_main": "url shortener, link shortener, kostenloser url shortener, url shortener mit vorschau, benutzerdefinierter short link, ablaufende links, temporäre links, short url, link kürzen, shortlinks.art",
        "meta_description_og": "Ein schneller, kostenloser und einfacher URL-Shortener mit Link-Vorschauen und benutzerdefinierten Ablaufzeiten.",
        "my_links_button": "Meine Links",
        "tagline": "Ein schneller, einfacher URL-Shortener mit Link-Vorschauen.",
        "create_link_heading": "Einen Kurzlink erstellen",
        "long_url_placeholder": "Geben Sie Ihre lange URL ein (z.B. https://...)",
        "create_button": "Kürzen",
        "advanced_options_button": "Erweiterte Optionen",
        "custom_code_label": "Benutzerdefinierter Code (optional)",
        "utm_tags_placeholder": "UTM-Tags (z.B. utm_source=twitter)",
        "ttl_label": "Läuft ab nach",
        "ttl_1h": "1 Stunde",
        "ttl_24h": "24 Stunden",
        "ttl_1w": "1 Woche",
        "ttl_never": "Nie",
        "result_short_link": "Kurzlink",
        "copy_button": "Kopieren",
        "result_stats_page": "Statistik-Seite",
        "result_view_clicks": "Klicks ansehen",
        "result_save_link_strong": "Speichern Sie diesen Link!",
        "result_save_link_text": "Dies ist Ihr eindeutiger Löschlink. Bewahren Sie ihn sicher auf, falls Sie Ihren Kurzlink jemals entfernen möchten.",
        "nav_home": "Startseite",
        "nav_about": "Über",
        "language_switcher_label": "Wähle eine Sprache",
        "link_not_found": "Link nicht gefunden",
        "link_expired": "Link ist abgelaufen",
        "invalid_url": "Ungültige URL angegeben.",
        "custom_code_exists": "Benutzerdefinierter Code existiert bereits",
        "id_generation_failed": "Konnte keinen eindeutigen Kurzcode generieren.",
        "owner_id_required": "Besitzer-ID erforderlich",
        "token_missing": "Lösch-Token fehlt",
        "delete_success": "Link erfolgreich gelöscht.",
        "delete_invalid_token": "Ungültiges Lösch-Token. Link wurde nicht gelöscht.",
        "js_enter_url": "Bitte geben Sie eine URL ein.",
        "js_error_creating": "Fehler beim Erstellen des Kurzlinks",
        "js_error_server": "Verbindung zum Server fehlgeschlagen.",
        "js_copied": "Kopiert!",
        "js_copy_failed": "Fehlgeschlagen!",
    },
    "ar": {
        "lang_name_en": "الإنجليزية", "lang_name_es": "الإسبانية", "lang_name_zh": "الصينية", "lang_name_hi": "الهندية", "lang_name_pt": "البرتغالية", "lang_name_fr": "الفرنسية", "lang_name_de": "الألمانية", "lang_name_ar": "العربية", "lang_name_ru": "الروسية", "lang_name_he": "العبرية",
        "app_title": "Shortlinks.art - خدمة تقصير روابط سريعة وبسيطة",
        "meta_description_main": "أنشئ روابط قصيرة مجانية مع معاينات. Shortlinks.art هو مقصر روابط سريع وبسيط يوفر أوقات انتهاء صلاحية مخصصة ومعاينات للروابط.",
        "meta_keywords_main": "مقصر روابط, تقصير روابط, مقصر روابط مجاني, مقصر روابط مع معاينة, رابط قصير مخصص, روابط تنتهي صلاحيتها, روابط مؤقتة, short url, تقصير رابط, shortlinks.art",
        "meta_description_og": "مقصر روابط سريع ومجاني وبسيط مع معاينات للروابط وأوقات انتهاء صلاحية مخصصة.",
        "my_links_button": "روابطي",
        "tagline": "مقصر روابط سريع وبسيط مع معاينات للروابط.",
        "create_link_heading": "إنشاء رابط قصير",
        "long_url_placeholder": "أدخل الرابط الطويل (مثال: https://...)",
        "create_button": "تقصير",
        "advanced_options_button": "خيارات متقدمة",
        "custom_code_label": "رمز مخصص (اختياري)",
        "utm_tags_placeholder": "علامات UTM (مثال: utm_source=twitter)",
        "ttl_label": "تنتهي الصلاحية بعد",
        "ttl_1h": "1 ساعة",
        "ttl_24h": "24 ساعة",
        "ttl_1w": "1 أسبوع",
        "ttl_never": "أبداً",
        "result_short_link": "الرابط القصير",
        "copy_button": "نسخ",
        "result_stats_page": "صفحة الإحصائيات",
        "result_view_clicks": "عرض النقرات",
        "result_save_link_strong": "احفظ هذا الرابط!",
        "result_save_link_text": "هذا هو رابط الحذف الفريد الخاص بك. احتفظ به بأمان إذا أردت يومًا إزالة الرابط القصير.",
        "nav_home": "الرئيسية",
        "nav_about": "حول",
        "language_switcher_label": "اختر لغة",
        "link_not_found": "الرابط غير موجود",
        "link_expired": "انتهت صلاحية الرابط",
        "invalid_url": "الرابط المُقدم غير صالح.",
        "custom_code_exists": "الرمز المخصص موجود بالفعل",
        "id_generation_failed": "لم يمكن إنشاء رمز قصير فريد.",
        "owner_id_required": "معرف المالك مطلوب",
        "token_missing": "رمز الحذف مفقود",
        "delete_success": "تم حذف الرابط بنجاح.",
        "delete_invalid_token": "رمز الحذف غير صالح. لم يتم حذف الرابط.",
        "js_enter_url": "الرجاء إدخال رابط.",
        "js_error_creating": "خطأ أثناء إنشاء الرابط القصير",
        "js_error_server": "فشل الاتصال بالخادم.",
        "js_copied": "تم النسخ!",
        "js_copy_failed": "فشل!",
    },
    "ru": {
        "lang_name_en": "Английский", "lang_name_es": "Испанский", "lang_name_zh": "Китайский", "lang_name_hi": "Хинди", "lang_name_pt": "Португальский", "lang_name_fr": "Французский", "lang_name_de": "Немецкий", "lang_name_ar": "Арабский", "lang_name_ru": "Русский", "lang_name_he": "Иврит",
        "app_title": "Shortlinks.art - Быстрый и простой сервис сокращения URL",
        "meta_description_main": "Создавайте бесплатные короткие ссылки с предпросмотром. Shortlinks.art - это быстрый и простой сервис, предлагающий настройку времени жизни ссылок и их предпросмотр.",
        "meta_keywords_main": "сократить ссылку, сокращатель ссылок, бесплатный сокращатель ссылок, ссылка с предпросмотром, кастомная короткая ссылка, истекающие ссылки, временные ссылки, короткий url, shortlinks.art",
        "meta_description_og": "Быстрый, бесплатный и простой сокращатель URL с предпросмотром ссылок и настраиваемым временем жизни.",
        "my_links_button": "Мои ссылки",
        "tagline": "Быстрый и простой сокращатель URL с предпросмотром ссылок.",
        "create_link_heading": "Создать короткую ссылку",
        "long_url_placeholder": "Введите ваш длинный URL (например, https://...)",
        "create_button": "Сократить",
        "advanced_options_button": "Дополнительные параметры",
        "custom_code_label": "Свой код (необязательно)",
        "utm_tags_placeholder": "UTM-метки (например, utm_source=twitter)",
        "ttl_label": "Ссылка истекает через",
        "ttl_1h": "1 час",
        "ttl_24h": "24 часа",
        "ttl_1w": "1 неделю",
        "ttl_never": "Никогда",
        "result_short_link": "Короткая ссылка",
        "copy_button": "Копир.",
        "result_stats_page": "Страница статистики",
        "result_view_clicks": "Посмотреть клики",
        "result_save_link_strong": "Сохраните эту ссылку!",
        "result_save_link_text": "Это ваша уникальная ссылка для удаления. Сохраните ее, если захотите удалить ссылку.",
        "nav_home": "Главная",
        "nav_about": "О проекте",
        "language_switcher_label": "Выберите язык",
        "link_not_found": "Ссылка не найдена",
        "link_expired": "Срок действия ссылки истек",
        "invalid_url": "Неверный URL.",
        "custom_code_exists": "Этот код уже используется",
        "id_generation_failed": "Не удалось создать уникальный код.",
        "owner_id_required": "Требуется ID владельца",
        "token_missing": "Отсутствует токен удаления",
        "delete_success": "Ссылка успешно удалена.",
        "delete_invalid_token": "Неверный токен удаления. Ссылка не удалена.",
        "js_enter_url": "Пожалуйста, введите URL.",
        "js_error_creating": "Ошибка при создании ссылки",
        "js_error_server": "Ошибка соединения с сервером.",
        "js_copied": "Скопировано!",
        "js_copy_failed": "Ошибка!",
    },
    "he": {
        "lang_name_en": "אנגלית", "lang_name_es": "ספרדית", "lang_name_zh": "סינית", "lang_name_hi": "הינדי", "lang_name_pt": "פורטוגזית", "lang_name_fr": "צרפתית", "lang_name_de": "גרמנית", "lang_name_ar": "ערבית", "lang_name_ru": "רוסית", "lang_name_he": "עברית",
        "app_title": "Shortlinks.art - מקצר כתובות URL מהיר ופשוט",
        "meta_description_main": "צרו קישורים קצרים בחינם עם תצוגה מקדימה. Shortlinks.art הוא מקצר כתובות מהיר ופשוט המציע זמני תפוגה מותאמים אישית ותצוגה מקדימה של קישורים.",
        "meta_keywords_main": "מקצר כתובות, קיצור קישורים, מקצר קישורים חינם, מקצר כתובות עם תצוגה מקדימה, קישור קצר מותאם אישית, קישורים פגי תוקף, קישורים זמניים, short url, shortlinks.art",
        "meta_description_og": "מקצר כתובות URL מהיר, חינמי ופשוט עם תצוגה מקדימה של קישורים וזמני תפוגה מותאמים אישית.",
        "my_links_button": "הקישורים שלי",
        "tagline": "מקצר כתובות URL מהיר ופשוט עם תצוגה מקדימה.",
        "create_link_heading": "יצירת קישור קצר",
        "long_url_placeholder": "הזן את הכתובת הארוכה שלך (לדוגמה, https://...)",
        "create_button": "קצר",
        "advanced_options_button": "אפשרויות מתקדמות",
        "custom_code_label": "קוד מותאם אישית (אופציונלי)",
        "utm_tags_placeholder": "תגיות UTM (לדוגמה, utm_source=twitter)",
        "ttl_label": "יפוג לאחר",
        "ttl_1h": "שעה",
        "ttl_24h": "24 שעות",
        "ttl_1w": "שבוע",
        "ttl_never": "אף פעם",
        "result_short_link": "קישור קצר",
        "copy_button": "העתק",
        "result_stats_page": "דף סטטיסטיקה",
        "result_view_clicks": "צפה בלחיצות",
        "result_save_link_strong": "שמור את הקישור הזה!",
        "result_save_link_text": "זהו קישור המחיקה הייחודי שלך. שמור אותו למקרה שתרצה למחוק את הקישור המקוצר שלך.",
        "nav_home": "ראשי",
        "nav_about": "אודות",
        "language_switcher_label": "בחר שפה",
        "link_not_found": "הקישור לא נמצא",
        "link_expired": "הקישור פג תוקף",
        "invalid_url": "כתובת URL לא חוקית.",
        "custom_code_exists": "קוד מותאם אישית זה כבר קיים",
        "id_generation_failed": "לא ניתן היה ליצור קוד קצר ייחודי.",
        "owner_id_required": "נדרש מזהה בעלים",
        "token_missing": "חסר אסימון מחיקה",
        "delete_success": "הקישור נמחק בהצלחה.",
        "delete_invalid_token": "אסימון מחיקה לא חוקי. הקישור לא נמחק.",
        "js_enter_url": "אנא הזן כתובת URL.",
        "js_error_creating": "שגיאה ביצירת קישור קצר",
        "js_error_server": "החיבור לשרת נכשל.",
        "js_copied": "הועתק!",
        "js_copy_failed": "נכשל!",
    }
}


# --- i18n Functions ---

def get_browser_locale(request: Request) -> str:
    lang_cookie = request.cookies.get("lang")
    if lang_cookie and lang_cookie in SUPPORTED_LOCALES:
        return lang_cookie
            
    try:
        lang_header = request.headers.get("accept-language")
        if lang_header:
            primary_lang = lang_header.split(',')[0].split('-')[0].lower()
            if primary_lang in SUPPORTED_LOCALES:
                return primary_lang
    except Exception:
        pass
    return DEFAULT_LOCALE

def get_translator_and_locale(
    request: Request, 
    locale: str = Path(..., description="The language code, e.g., 'en', 'es'")
) -> (Callable[[str], str], str):
    valid_locale = locale if locale in SUPPORTED_LOCALES else DEFAULT_LOCALE
    
    def _(key: str) -> str:
        translated = translations.get(valid_locale, {}).get(key)
        if translated:
            return translated
        fallback = translations.get(DEFAULT_LOCALE, {}).get(key)
        if fallback:
            return fallback
        return key
        
    return _, valid_locale

def get_api_translator(request: Request) -> Callable[[str], str]:
    locale = get_browser_locale(request)
    def _(key: str) -> str:
        translated = translations.get(locale, {}).get(key)
        if translated:
            return translated
        fallback = translations.get(DEFAULT_LOCALE, {}).get(key)
        if fallback:
            return fallback
        return key
    return _

def get_translator(tr: tuple = Depends(get_translator_and_locale)) -> Callable[[str], str]:
    return tr[0]

def get_current_locale(tr: tuple = Depends(get_translator_and_locale)) -> str:
    return tr[1]

def get_hreflang_tags(request: Request, locale: str = Depends(get_current_locale)) -> list[dict]:
    tags = []
    current_path = request.url.path
    
    base_path = current_path.replace(f"/{locale}", "", 1)
    if not base_path: 
        base_path = "/"
        
    for lang in SUPPORTED_LOCALES:
        lang_path = f"/{lang}{base_path}"
        if lang_path.startswith('//'):
            lang_path = lang_path[1:]
            
        tags.append({
            "rel": "alternate",
            "hreflang": lang,
            "href": str(request.url.replace(path=lang_path))
        })
    
    default_path = f"/{DEFAULT_LOCALE}{base_path}"
    if default_path.startswith('//'):
            default_path = default_path[1:]

    tags.append({
        "rel": "alternate",
        "hreflang": "x-default",
        "href": str(request.url.replace(path=default_path))
    })
    return tags

async def get_common_context(
    request: Request,
    _: Callable = Depends(get_translator),
    locale: str = Depends(get_current_locale),
    hreflang_tags: list = Depends(get_hreflang_tags)
) -> dict:
    return {
        "request": request,
        "ADSENSE_SCRIPT": ADSENSE_SCRIPT,
        "_": _,
        "locale": locale,
        "hreflang_tags": hreflang_tags,
        "current_year": datetime.now(timezone.utc).year,
        "RTL_LOCALES": RTL_LOCALES # Pass RTL list to template
    }

# ---------------- FIREBASE ----------------
db: firestore.Client = None
APP_INSTANCE = None

import threading
import time
import logging # Import logging

logger = logging.getLogger(__name__) # Get a logger

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

#
# =====================================================================
# UPDATED/FIXED init_firebase function
# This is much more robust and fixes the "Unable to add links" bug.
# =====================================================================
#
def init_firebase():
    global db, APP_INSTANCE
    if db:
        return db

    firebase_config_str = os.environ.get("FIREBASE_CONFIG")
    temp_file_path = None
    cred = None

    try:
        if os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            cred = credentials.ApplicationDefault()
            logger.info("Using GOOGLE_APPLICATION_CREDENTIALS path.")
        elif firebase_config_str:
            # Use a context manager for the temporary file
            with tempfile.NamedTemporaryFile(mode='w', delete=False, encoding='utf-8') as tmp_file:
                tmp_file.write(firebase_config_str)
                temp_file_path = tmp_file.name
            
            cred = credentials.Certificate(temp_file_path)
            logger.info(f"Using FIREBASE_CONFIG JSON string via temporary file: {temp_file_path}")
        
        if cred is None:
            logger.error("FIREBASE_CONFIG or GOOGLE_APPLICATION_CREDENTIALS is not set.")
            raise RuntimeError("Firebase configuration is missing.")

        try:
            APP_INSTANCE = get_app()
            logger.info("Reusing existing Firebase App instance.")
        except ValueError:
            APP_INSTANCE = firebase_admin.initialize_app(cred)
            logger.info("Initialized new Firebase App instance.")
        
        db = firestore.client(app=APP_INSTANCE)
        logger.info("Firebase Firestore client initialized successfully.")
        return db

    except Exception as e:
        logger.error(f"Error initializing Firebase or Firestore: {e}")
        raise RuntimeError("Database connection failure.") from e
    finally:
        # Clean up the temp file
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.debug(f"Cleaned up temporary credential file at {temp_file_path}")
            except Exception as cleanup_e:
                logger.warning(f"Failed to clean up temporary credential file: {cleanup_e}")

# ---------------- HELPERS ----------------
# (All helpers are correct, no changes needed)
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
    
    return {
        **data,
        "short_code": code,
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
app = FastAPI(title="Shortlinks.art URL Shortener")
i18n_router = FastAPI() # Our sub-app for all localized routes

limiter = Limiter(key_func=get_remote_address)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


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

# === NON-LOCALIZED ROUTES (Mounted on main 'app') ===

@app.get("/")
async def root_redirect(request: Request):
    locale = get_browser_locale(request)
    response = RedirectResponse(url=f"/{locale}", status_code=307) 
    response.set_cookie("lang", locale, max_age=365*24*60*60, samesite="lax")
    return response

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
    _ : Callable = Depends(get_api_translator)
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
        
        locale = get_browser_locale(request)
        short_code = link['short_code']
        token = link['deletion_token']

        localized_preview_url = f"{BASE_URL}/{locale}/preview/{short_code}"
        
        qr_code_data_uri = generate_qr_code_data_uri(localized_preview_url)
        return {
            "short_url": f"{BASE_URL}/r/{short_code}",
            "stats_url": f"{BASE_URL}/{locale}/stats/{short_code}",
            "delete_url": f"{BASE_URL}/{locale}/delete/{short_code}?token={token}",
            "qr_code_data": qr_code_data_uri
        }
    except ValueError as e:
        raise HTTPException(status_code=409, detail=_("custom_code_exists"))
    except RuntimeError as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/v1/my-links")
async def get_my_links(
    owner_id: str,
    _ : Callable = Depends(get_api_translator)
):
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
Disallow: /health
Sitemap: {BASE_URL}/sitemap.xml
"""
    return content

@app.get("/sitemap.xml", response_class=Response)
async def sitemap():
    last_mod = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    
    xml_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
"""
    for lang in SUPPORTED_LOCALES:
        xml_content += f"""
  <url>
    <loc>{BASE_URL}/{lang}</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>1.0</priority>
  </url>
  <url>
    <loc>{BASE_URL}/{lang}/about</loc>
    <lastmod>{last_mod}</lastmod>
    <priority>0.8</priority>
  </url>
"""
    xml_content += "</urlset>"
    return Response(content=xml_content, media_type="application/xml")

#
# =====================================================================
# UPDATED/FIXED update_clicks_in_transaction
# This is now more robust and fixes the click counting bug.
# =====================================================================
#
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
async def redirect_link(
    short_code: str,
    _ : Callable = Depends(get_api_translator)
):
    db = init_firebase()
    doc_ref = db.collection("links").document(short_code)
    long_url = None
    
    try:
        # 1. Try the atomic transaction
        transaction = db.transaction()
        long_url = update_clicks_in_transaction(transaction, doc_ref, get_text=_)
        
    except HTTPException as e:
        raise e 
    except Exception as e:
        # 2. Transaction failed. Log and try a non-atomic update.
        logger.warning(f"Click count transaction for {short_code} failed: {e}. Retrying non-atomically.")
        
        try:
            link_doc = doc_ref.get() 
            if not link_doc.exists:
                 raise HTTPException(status_code=404, detail=_("link_not_found"))
            
            link = link_doc.to_dict()
            expires_at = link.get("expires_at")
            if expires_at and expires_at < datetime.now(timezone.utc):
                raise HTTPException(status_code=410, detail=_("link_expired"))
            
            today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            day_key = f"clicks_by_day.{today_str}"
            doc_ref.update({
                "click_count": firestore.Increment(1),
                day_key: firestore.Increment(1)
            })
            
            long_url = link["long_url"]
            
        except HTTPException as he:
            raise he
        except Exception as e2:
            # 3. Fallback *also* failed. Just log and redirect.
            logger.error(f"Non-transactional update for {short_code} failed: {e2}. Redirecting without count.")
            if 'link' in locals() and link:
                long_url = link.get("long_url")
            
            if long_url is None:
                try:
                    link_doc = doc_ref.get()
                    if link_doc.exists:
                        long_url = link_doc.to_dict().get("long_url")
                    else:
                        raise HTTPException(status_code=404, detail=_("link_not_found"))
                except Exception as e3:
                     logger.error(f"Final attempt to get long_url for {short_code} failed: {e3}.")
                     raise HTTPException(status_code=404, detail=_("link_not_found"))

    if not long_url:
        raise HTTPException(status_code=404, detail=_("link_not_found"))

    if not long_url.startswith(("http://", "https")):
        absolute_url = "https://" + long_url
    else:
        absolute_url = long_url

    return RedirectResponse(url=absolute_url)


# === LOCALIZED PAGE ROUTES (Mounted on 'i18n_router') ===

@i18n_router.get("/", response_class=HTMLResponse)
async def index(common_context: dict = Depends(get_common_context)):
    return templates.TemplateResponse("index.html", common_context)
    
@i18n_router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(common_context: dict = Depends(get_common_context)):
    return templates.TemplateResponse("dashboard.html", common_context)

@i18n_router.get("/about", response_class=HTMLResponse)
async def about(common_context: dict = Depends(get_common_context)):
    return templates.TemplateResponse("about.html", common_context)

@i18n_router.get("/preview/{short_code}", response_class=HTMLResponse)
async def preview(
    short_code: str,
    common_context: dict = Depends(get_common_context)
):
    _ = common_context["_"]
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
        meta = {
            "title": link.get("meta_title"),
            "description": link.get("meta_description"),
            "image": link.get("meta_image"),
            "favicon": link.get("meta_favicon")
        }
    else:
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
        **common_context,
        "short_code": short_code,
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

@i18n_router.get("/stats/{short_code}", response_class=HTMLResponse)
async def stats(
    short_code: str,
    common_context: dict = Depends(get_common_context)
):
    _ = common_context["_"]
    link = get_link(short_code)
    if not link:
        raise HTTPException(status_code=404, detail=_("link_not_found"))
    
    context = { **common_context, "link": link }
    return templates.TemplateResponse("stats.html", context)

@i18n_router.get("/delete/{short_code}", response_class=HTMLResponse)
async def delete(
    short_code: str,
    token: Optional[str] = None,
    common_context: dict = Depends(get_common_context)
):
    _ = common_context["_"]
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
            **common_context, 
            "success": True, 
            "message": _("delete_success")
        }
    else:
        context = {
            **common_context,
            "success": False,
            "message": _("delete_invalid_token")
        }
        
    return templates.TemplateResponse("delete_status.html", context)


class SecurityException(Exception):
    pass

# --- Mount the localized router ---
app.mount("/{locale}", i18n_router, name="localized")

# --- Start background tasks ---
start_cleanup_thread()
