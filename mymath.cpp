#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <string>
#include <algorithm>

// --- C++ Implementation of Bijective Functions ---

std::string to_bijective_base6_impl(long long n) {
    if (n <= 0) {
        PyErr_SetString(PyExc_ValueError, "Input must be a positive integer");
        return "";
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
    return result_str;
}

long long from_bijective_base6_impl(const char* s) {
    long long n = 0;
    std::string chars = "123456";

    for (int i = 0; s[i] != '\0'; ++i) {
        size_t pos = chars.find(s[i]);
        if (pos == std::string::npos) {
            PyErr_SetString(PyExc_ValueError, "Invalid character in short code");
            return -1;
        }
        n = n * 6 + pos + 1;
    }
    return n;
}

// --- Python C API Wrapper Functions ---

static PyObject* to_bijective_base6_cpp(PyObject* self, PyObject* args) {
    long long n;
    if (!PyArg_ParseTuple(args, "L", &n)) {
        return NULL;
    }
    std::string result = to_bijective_base6_impl(n);
    if (PyErr_Occurred()) {
        return NULL;
    }
    return PyUnicode_FromString(result.c_str());
}

static PyObject* from_bijective_base6_cpp(PyObject* self, PyObject* args) {
    const char* s;
    if (!PyArg_ParseTuple(args, "s", &s)) {
        return NULL;
    }
    long long result = from_bijective_base6_impl(s);
    if (PyErr_Occurred()) {
        return NULL;
    }
    return PyLong_FromLongLong(result);
}

// --- Module Definition ---

static PyMethodDef MyMathMethods[] = {
    {"to_bijective_base6_cpp", to_bijective_base6_cpp, METH_VARARGS, "Converts an integer to a bijective base-6 string."},
    {"from_bijective_base6_cpp", from_bijective_base6_cpp, METH_VARARGS, "Converts a bijective base-6 string to an integer."},
    {NULL, NULL, 0, NULL}
};

static struct PyModuleDef mymath_cpp_module = {
    PyModuleDef_HEAD_INIT,
    "mymath_cpp",
    "A C++ extension module for bijective base-6 conversions.",
    -1,
    MyMathMethods
};

PyMODINIT_FUNC PyInit_mymath_cpp(void) {
    return PyModule_Create(&mymath_cpp_module);
}