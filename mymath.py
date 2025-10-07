import ctypes
import os
import platform

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

# --- C++ Implementation Loader ---

mymath_lib = None
try:
    # Determine the library extension based on the OS
    if platform.system() == "Windows":
        lib_name = "mymath.dll"
    elif platform.system() == "Linux":
        lib_name = "mymath.so"
    elif platform.system() == "Darwin": # macOS
        lib_name = "mymath.dylib"
    else:
        raise ImportError("Unsupported OS")

    # Load the shared library
    lib_path = os.path.join(os.path.dirname(__file__), lib_name)
    mymath_lib = ctypes.CDLL(lib_path)

    # Define function signatures for type safety
    mymath_lib.to_bijective_base6_cpp.argtypes = [ctypes.c_longlong]
    mymath_lib.to_bijective_base6_cpp.restype = ctypes.c_char_p

    mymath_lib.from_bijective_base6_cpp.argtypes = [ctypes.c_char_p]
    mymath_lib.from_bijective_base6_cpp.restype = ctypes.c_longlong

    # --- Define the public functions to use the C++ versions ---
    def to_bijective_base6(n: int) -> str:
        result_bytes = mymath_lib.to_bijective_base6_cpp(n)
        return result_bytes.decode('utf-8')

    def from_bijective_base6(s: str) -> int:
        result = mymath_lib.from_bijective_base6_cpp(s.encode('utf-8'))
        if result == -1:
            raise ValueError("Invalid short code format")
        return result

    print("Successfully loaded C++ mymath library.")

except (ImportError, OSError):
    print("WARNING: Could not load C++ mymath library. Falling back to pure Python implementation.")
    # Fallback to Python implementations if the C++ library is not found
    to_bijective_base6 = _to_bijective_base6_py
    from_bijective_base6 = _from_bijective_base6_py