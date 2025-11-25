#!/usr/bin/env bash
set -e
PYTHON_BIN="${PYTHON_BIN:-python3}"
echo "Using $PYTHON_BIN"
$PYTHON_BIN -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
echo "✅ venv ready. Activate with: source venv/bin/activate"
