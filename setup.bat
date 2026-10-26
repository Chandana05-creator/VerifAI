@echo off
setlocal
cd /d "%~dp0"
echo === VerifAI setup ===
py -3.11 --version >nul 2>&1
if errorlevel 1 (
  echo Python 3.11 was not found. Install Python 3.11 from python.org, then run setup.bat again.
  exit /b 1
)
if not exist venv311 py -3.11 -m venv venv311
call venv311\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt
if errorlevel 1 (
  echo Package installation failed. Scroll up for the error.
  exit /b 1
)
if not exist .env copy .env.example .env >nul
echo.
echo Setup finished.
echo NEXT: open the file named .env in this folder, paste your GEMINI_API_KEY and TAVILY_API_KEY, save it,
echo       then run  check.bat  and then  start.bat
