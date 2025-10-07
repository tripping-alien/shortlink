# --- Pure Python Fallback Implementation ---
def _to_bijective_base6_py(n: int) -> str:
    if n <= 0:
        raise ValueError("Input must be a positive integer")
    chars = "123456"
    result = []
    while n > 0:
        n, remainder = divmod(n - 1, 6)
        result.append(chars[remainder])
    return "".join(reversed(result))

def _from_bijective_base6_py(s: str) -> int:
    if not s or not s.isalnum():
        raise ValueError("Invalid short code format")
    n = 0
    for char in s:
        try:
            n = n * 6 + "123456".index(char) + 1
        except ValueError:
            raise ValueError("Invalid character in short code")
    return n

# --- C++ Extension Loader ---
try:
    # This will import the compiled C++ module created by setup.py
    from mymath_cpp import to_bijective_base6_cpp, from_bijective_base6_cpp

    # --- Define the public functions to use the C++ versions ---
    def to_bijective_base6(n: int) -> str:
        return to_bijective_base6_cpp(n)

    def from_bijective_base6(s: str) -> int:
        result = from_bijective_base6_cpp(s)
        if result == -1:
            raise ValueError("Invalid short code format")
        return result

    print("Successfully loaded C++ mymath library.")

except ImportError:
    print("WARNING: Could not load C++ mymath library. Falling back to pure Python implementation.")
    # Fallback to Python implementations if the C++ library is not found
    to_bijective_base6 = _to_bijective_base6_py
    from_bijective_base6 = _from_bijective_base6_py