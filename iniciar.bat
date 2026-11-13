@echo off
setlocal
cd /d "%~dp0"
title BIMOFFICE Knowledge

rem ---------------------------------------------------------------------------
rem A pesquisa semantica usa o PyTorch, que so existe para Python 3.11, 3.12 e 3.13.
rem Versoes muito novas (3.14, 3.15...) ainda nao sao suportadas por ele.
rem ---------------------------------------------------------------------------
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY (
    py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo.
  echo ERRO: nao encontrei Python 3.11, 3.12 ou 3.13 neste computador.
  echo Versoes muito novas, como 3.14 ou 3.15, ainda nao tem o PyTorch,
  echo usado pela pesquisa semantica.
  echo.
  echo Instale o Python 3.13 em https://www.python.org/downloads/
  echo marcando "Add python.exe to PATH", e rode este arquivo de novo.
  echo Nao precisa desinstalar a versao atual.
  echo.
  pause
  exit /b 1
)
echo Usando: %PY%

rem Se o .venv foi criado com uma versao incompativel, apaga e recria.
if exist .venv\Scripts\python.exe (
  .venv\Scripts\python.exe -c "import sys; sys.exit(0 if (3,11) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1
  if errorlevel 1 (
    echo Recriando o ambiente .venv com a versao correta do Python...
    rmdir /s /q .venv
  )
)
if not exist .venv (%PY% -m venv .venv)
call .venv\Scripts\activate.bat

python -m pip install -q --upgrade pip
pip install -q -r requirements.txt
if errorlevel 1 (
  echo ERRO ao instalar as dependencias basicas. Veja as mensagens acima.
  pause
  exit /b 1
)
rem Pesquisa semantica (opcional). No Windows o PyTorch do PyPI ja e a versao so-CPU.
echo Instalando a pesquisa semantica (na 1a vez pode demorar varios minutos)...
pip install -q -r requirements-ml.txt || echo AVISO: pesquisa semantica indisponivel.

echo.
echo Abra no navegador: http://127.0.0.1:8000/
uvicorn backend.main:app --host 127.0.0.1 --port 8000
pause
