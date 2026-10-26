#!/usr/bin/env bash
cd "$(dirname "$0")" && source venv311/bin/activate && cd backend
echo "First start downloads small AI models and can take a few minutes. When you see Ready, open http://localhost:8000/"
python -m uvicorn main:app --port 8000
