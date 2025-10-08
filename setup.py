from setuptools import setup, Extension

# Define the C++ extension module
mymath_cpp_module = Extension(
    'mymath_cpp',                # Name of the module in Python
    sources=['mymath_cpp.cpp'],  # The C++ source file
    language='c++'
)

setup(
    name='mymath_cpp',
    version='1.0',
    description='A C++ extension for bijective base-6 encoding.',
    ext_modules=[mymath_cpp_module]
)