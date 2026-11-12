#!/usr/bin/env bash
# Inicia o BIMOFFICE Knowledge (Linux/macOS)
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
echo "Abra no navegador: http://127.0.0.1:8000/docs"
uvicorn backend.main:app --host 127.0.0.1 --port 8000
