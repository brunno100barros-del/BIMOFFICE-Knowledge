@echo off
cd /d "%~dp0"
if not exist .venv (py -m venv .venv)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
echo Abra no navegador: http://127.0.0.1:8000/docs
uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause
