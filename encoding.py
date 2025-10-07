"""
Handles the bijective conversion between an integer and a base-6 string.
This ensures that every integer has a unique, short, and collision-free representation.
"""

ALPHABET = "123456"
BASE = len(ALPHABET)


def to_bijective_base6(n: int) -> str:
    """Converts a positive integer to its bijective base-6 representation."""
    if n <= 0:
        raise ValueError("Input must be a positive integer for bijective conversion.")
    
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, BASE)
        result.append(ALPHABET[remainder])
    return "".join(reversed(result))


def from_bijective_base6(s: str) -> int:
    """Converts a bijective base-6 string back to a positive integer."""
    if not s or not all(c in ALPHABET for c in s):
        raise ValueError("Invalid character in short code. Only '1'-'6' are allowed.")
    
    n = 0
    for char in s:
        n = n * BASE + ALPHABET.index(char) + 1
    return n