#include <Python.h>
#include <string>
#include <vector>
#include <algorithm>
#include <iostream>

const std::string ALPHABET = "123456";
const int BASE = ALPHABET.length();

// C++ implementation of to_bijective_base6
static PyObject* to_bijective_base6_cpp(PyObject* self, PyObject* args) {
    long long n;
    if (!PyArg_ParseTuple(args, "L", &n)) {
        return NULL; // Error parsing arguments
    }

    if (n <= 0) {
        PyErr_SetString(PyExc_ValueError, "Input must be a positive integer for bijective conversion.");
        return NULL;
    }

    std::string result_str;
    while (n > 0) {
        long long remainder;
        n--; // Adjust for 0-based index
        remainder = n % BASE;
        n = n / BASE;
        result_str += ALPHABET[remainder];
    }
    std::reverse(result_str.begin(), result_str.end());

    return PyUnicode_FromString(result_str.c_str());
}

// C++ implementation of from_bijective_base6
static PyObject* from_bijective_base6_cpp(PyObject* self, PyObject* args) {
    const char* s;
    if (!PyArg_ParseTuple(args, "s", &s)) {
        return NULL; // Error parsing arguments
    }

    std::string input_str(s);
    if (input_str.empty()) {
        PyErr_SetString(PyExc_ValueError, "Input string cannot be empty.");
        return NULL;
    }

    long long n = 0;
    for (char const &c : input_str) {
        size_t pos = ALPHABET.find(c);
        if (pos == std::string::npos) {
            PyErr_SetString(PyExc_ValueError, "Invalid character in short code. Only '1'-'6' are allowed.");
            return NULL;
        }
        n = n * BASE + pos + 1;
    }

    return PyLong_FromLongLong(n);
}

// Method definition table for the module
static PyMethodDef MyMathMethods[] = {
    {
        "to_bijective_base6_cpp", // Python function name
        to_bijective_base6_cpp,   // C++ function
        METH_VARARGS,             // Use PyArg_ParseTuple
        "Converts a positive integer to its bijective base-6 representation (C++ version)."
    },
    {
        "from_bijective_base6_cpp",
        from_bijective_base6_cpp,
        METH_VARARGS,
        "Converts a bijective base-6 string back to a positive integer (C++ version)."
    },
    {NULL, NULL, 0, NULL} // Sentinel
};

// Module definition structure
static struct PyModuleDef mymath_cpp_module = {
    PyModuleDef_HEAD_INIT,
    "mymath_cpp", // Module name
    "A C++ extension for high-performance bijective base-6 encoding.", // Module docstring
    -1,
    MyMathMethods
};

// Module initialization function
PyMODINIT_FUNC PyInit_mymath_cpp(void) {
    return PyModule_Create(&mymath_cpp_module);
}