@echo off
set PYTHON_BIN=python
echo Using %PYTHON_BIN%
%PYTHON_BIN% -m venv venv
call venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
echo venv ready. Activate with: venv\Scripts\activate
