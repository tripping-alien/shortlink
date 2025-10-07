# --- Bijective Base-6 Logic ---
def to_bijective_base6(n: int) -> str:
    if n <= 0:
        raise ValueError("Input must be a positive integer")
    chars = "123456"
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, 6)
        result.append(chars[remainder])
    return "".join(reversed(result))


def from_bijective_base6(s: str) -> int:
    if not s or not s.isalnum():
        raise ValueError("Invalid short code format")
    n = 0
    for char in s:
        n = n * 6 + "123456".index(char) + 1
    return n