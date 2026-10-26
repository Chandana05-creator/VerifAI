#!/usr/bin/env bash
cd "$(dirname "$0")" && source venv311/bin/activate && cd backend && python check_setup.py
