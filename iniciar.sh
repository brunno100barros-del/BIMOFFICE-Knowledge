#!/usr/bin/env bash
# Inicia o BIMOFFICE Knowledge (Linux/macOS)
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
# Pesquisa semântica (opcional; sem ela o sistema avisa e usa só a busca por palavras).
# PyTorch só-CPU (bem menor que a versão para placa de vídeo).
python -c "import torch" 2>/dev/null || pip install -q torch --index-url https://download.pytorch.org/whl/cpu \
  || echo "AVISO: PyTorch não instalado; pesquisa semântica indisponível."
pip install -q -r requirements-ml.txt || echo "AVISO: sentence-transformers não instalado."
echo "Abra no navegador: http://127.0.0.1:8000/"
uvicorn backend.main:app --host 127.0.0.1 --port 8000
