import os
import re
from urllib.request import Request
from .config import TRANSLATIONS, DEFAULT_LANGUAGE

def load_translations():
    """
    Parses .po files from the locales directory and loads them into memory.
    This is a simple parser that handles the basic msgid/msgstr format.
    """
    locales_dir = "locales"
    if not os.path.isdir(locales_dir):
        return

    for lang in os.listdir(locales_dir):
        po_file = os.path.join(locales_dir, lang, "LC_MESSAGES", "messages.po")
        if os.path.exists(po_file):
            with open(po_file, "r", encoding="utf-8") as f:
                content = f.read()

            translations = {}
            # Regex to find msgid "" and msgstr "" pairs
            pattern = re.compile(r'msgid "((?:\\.|[^"])*)"\s+msgstr "((?:\\.|[^"])*)"', re.DOTALL)

            for match in pattern.finditer(content):
                msgid = match.group(1).replace('\\"', '"').replace('\\n', '\n')
                msgstr = match.group(2).replace('\\"', '"').replace('\\n', '\n')
                if msgid:  # Ensure msgid is not empty
                    translations[msgid] = msgstr

            TRANSLATIONS[lang] = translations
            print(f"Loaded {len(translations)} translations for language: {lang}")


def gettext(text: str, lang: str = DEFAULT_LANGUAGE) -> str:
    """
    Translates a given text to the specified language.
    Falls back to the original text if no translation is found.
    """
    return TRANSLATIONS.get(lang, {}).get(text, text)


def lazy_gettext(request: Request, text: str) -> str:
    """A 'lazy' version of gettext that uses the language from the request scope."""
    lang = request.scope.get("language", DEFAULT_LANGUAGE)
    return gettext(text, lang)