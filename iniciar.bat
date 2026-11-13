@echo off
cd /d "%~dp0"
if not exist .venv (py -m venv .venv)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
rem Pesquisa semantica (opcional). No Windows o PyTorch do PyPI ja e a versao so-CPU.
pip install -q -r requirements-ml.txt || echo AVISO: pesquisa semantica indisponivel.
echo Abra no navegador: http://127.0.0.1:8000/docs
uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause
