"""
Handles the encoding and decoding of database IDs into short, non-sequential,
and reversible strings using the hashids library. This is the core protection
against scraping and enumeration attacks.
"""
from hashids import Hashids
from config import settings

# Initialize the Hashids instance with our secret salt and configuration.
# This instance is created only once when the module is imported.
hashids = Hashids(
     salt=settings.hashids_salt,
     min_length=settings.hashids_min_length,
     alphabet=settings.hashids_alphabet
 )


def encode_id(n: int) -> str:
    """Encodes a single integer ID into a short, non-sequential string."""
    return hashids.encode(n)


def decode_id(s: str) -> int | None:
    """Decodes a short string back into an integer ID."""
    decoded_tuple = hashids.decode(s)
    if decoded_tuple:
        return decoded_tuple[0]  # hashids.decode returns a tuple, e.g., (123,)
    return None