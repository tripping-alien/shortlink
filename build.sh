#!/usr/bin/env bash
# Exit on error
set -o errexit

# 1. Install Python dependencies
echo "Installing Python dependencies..."
pip install -r requirements.txt