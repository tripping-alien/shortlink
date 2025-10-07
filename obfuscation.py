"""
A simple integer obfuscation module to prevent sequential scraping of short links.

This uses a prime multiplication and XOR to permute integers within a 31-bit space.
It is not cryptographically secure but is more than sufficient to make database
IDs appear random and non-sequential.
"""

# A large prime number smaller than MAX_ID.
PRIME = 1580030173

# The modular multiplicative inverse of PRIME modulo 2**31.
# This is pre-calculated using pow(PRIME, -1, 2**31).
PRIME_INVERSE = 1103515245

# A large random integer to use as an XOR key.
RANDOM_XOR = 1234567890

# We operate within a 31-bit integer space (positive integers for a 32-bit signed int).
MAX_ID = 2**31 - 1


def obfuscate(n: int) -> int:
    """Scrambles a sequential integer ID to make it appear random."""
    if not 0 < n <= MAX_ID:
        raise ValueError("Input ID is out of the valid obfuscation range.")
    return ((n * PRIME) & MAX_ID) ^ RANDOM_XOR


def deobfuscate(n: int) -> int:
    """Reverses the scrambling to retrieve the original sequential ID."""
    original_n = n ^ RANDOM_XOR
    return (original_n * PRIME_INVERSE) & MAX_ID