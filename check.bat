@echo off
cd /d "%~dp0"
call venv311\Scripts\activate.bat
cd backend
python check_setup.py
