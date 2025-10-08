import os
import re

TRANSLATIONS = {}
DEFAULT_LANGUAGE = "en"


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


def get_translator(lang: str = DEFAULT_LANGUAGE):
    """Dependency to get a translator function for the current request's language."""

    def translator(text: str, **kwargs) -> str:
        translated = TRANSLATIONS.get(lang, {}).get(text, text)
        return translated.format(**kwargs) if kwargs else translated

    return translator