"""
Handles the encoding and decoding of database IDs into short, non-sequential,
and reversible strings using the hashids library. This is the core protection
against scraping and enumeration attacks.
"""
from typing import Optional
from functools import lru_cache

from hashids import Hashids
from config import get_settings


@lru_cache()
def get_hashids() -> Hashids:
    """
    Returns a cached, singleton instance of the Hashids object.
    This ensures the object is created only once with the final, correct settings.
    """
    settings = get_settings()
    return Hashids(salt=settings.hashids_salt, min_length=settings.hashids_min_length, alphabet=settings.hashids_alphabet)


def encode_id(n: int) -> str:
    """Encodes a single integer ID into a short, non-sequential string."""
    return get_hashids().encode(n)


def decode_id(s: str) -> int | None:
    """Decodes a short string back into an integer ID."""
    decoded_tuple = get_hashids().decode(s)
    if decoded_tuple:
        return decoded_tuple[0]  # hashids.decode returns a tuple, e.g., (123,)
    return None