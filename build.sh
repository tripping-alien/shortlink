#!/usr/bin/env bash
# Exit on error
set -o errexit

# 1. Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt

# 2. Compile the C++ extension
# This command tells pip to run the setup.py file and build the C++ module
# in a way that the Python application can find and import it.
echo "Compiling C++ extension..."
pip install .