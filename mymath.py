"""
Bijective base-6 conversion functions.
"""

def to_bijective_base6(n: int) -> str:
    """
    Converts a positive integer into a bijective base-6 string.
    """
    if n <= 0:
        raise ValueError("Input must be a positive integer")
    chars = "123456"
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, 6)
        result.append(chars[remainder])
    return "".join(reversed(result))


def from_bijective_base6(s: str) -> int:
    """
    Converts a bijective base-6 string back to a positive integer.
    """
    if not s or not all(c in "123456" for c in s):
        raise ValueError("Invalid short code format")
    n = 0
    for char in s:
        n = n * 6 + "123456".index(char) + 1
    return n
