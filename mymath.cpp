#include <string>
#include <vector>
#include <algorithm>
#include <stdexcept>

// Use a static buffer for the result of to_bijective_base6 to avoid memory management issues across the C boundary.
// This is not thread-safe, but for this application's usage pattern, it's a simple and effective approach.
char result_buffer[256];

extern "C" {

    __declspec(dllexport) const char* to_bijective_base6_cpp(long long n) {
        if (n <= 0) {
            // It's generally better to handle errors on the Python side,
            // but we can return an error string.
            return "Error: Input must be a positive integer";
        }
        const char* chars = "123456";
        std::string result_str = "";
        
        while (n > 0) {
            long long remainder;
            n--; // Adjust to be 0-indexed
            remainder = n % 6;
            n = n / 6;
            result_str += chars[remainder];
        }
        
        std::reverse(result_str.begin(), result_str.end());
        
        // Copy to the static buffer
        strncpy_s(result_buffer, sizeof(result_buffer), result_str.c_str(), _TRUNCATE);
        
        return result_buffer;
    }

    __declspec(dllexport) long long from_bijective_base6_cpp(const char* s) {
        long long n = 0;
        std::string chars = "123456";
        
        for (int i = 0; s[i] != '\0'; ++i) {
            size_t pos = chars.find(s[i]);
            if (pos == std::string::npos) {
                // Return -1 to indicate an error, which can be checked in Python.
                return -1;
            }
            n = n * 6 + pos + 1;
        }
        return n;
    }

}