from setuptools import setup, Extension

# Define the C++ extension module
mymath_extension = Extension(
    'mymath_cpp',  # Name of the module when imported in Python
    sources=['mymath.cpp'],
    language='c++'
)

setup(
    name='bijective_shorty_extensions',
    version='1.0',
    description='C++ extensions for the Bijective-Shorty application.',
    ext_modules=[mymath_extension]
)