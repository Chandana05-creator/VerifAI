@echo off
cd /d "%~dp0"
call venv311\Scripts\activate.bat
cd backend
echo Starting VerifAI. The first start downloads small AI models and can take a few minutes.
echo When you see "Ready", open http://localhost:8000/ in your browser.
python -m uvicorn main:app --port 8000
