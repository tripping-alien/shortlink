"""
Handles the bijective conversion between an integer and a base-6 string.
This ensures that every integer has a unique, short, and collision-free representation.
This module will attempt to load a compiled C++ extension for performance,
falling back to a pure Python implementation if it's not available.
"""

ALPHABET = "123456"
BASE = len(ALPHABET)

# --- Pure Python Fallback Implementation ---

def _to_bijective_base6_py(n: int) -> str:
    """Converts a positive integer to its bijective base-6 representation."""
    if n <= 0:
        raise ValueError("Input must be a positive integer for bijective conversion.")
    
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, BASE)
        result.append(ALPHABET[remainder])
    return "".join(reversed(result))


def _from_bijective_base6_py(s: str) -> int:
    """Converts a bijective base-6 string back to a positive integer."""
    if not s or not all(c in ALPHABET for c in s):
        raise ValueError("Invalid character in short code. Only '1'-'6' are allowed.")
    
    n = 0
    for char in s:
        n = n * BASE + ALPHABET.index(char) + 1
    return n

# --- C++ Extension Loader ---
try:
    from mymath_cpp import to_bijective_base6_cpp, from_bijective_base6_cpp
    to_bijective_base6 = to_bijective_base6_cpp
    from_bijective_base6 = from_bijective_base6_cpp
    print("Successfully loaded C++ encoding library for high performance.")
except ImportError:
    print("WARNING: C++ encoding library not found. Falling back to pure Python implementation.")
    to_bijective_base6 = _to_bijective_base6_py
    from_bijective_base6 = _from_bijective_base6_py