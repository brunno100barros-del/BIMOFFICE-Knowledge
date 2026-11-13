"""Configurações centrais do BIMOFFICE Knowledge."""
from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Pasta de dados (documentos originais, banco, backups, logs).
# Pode ser alterada pela variável de ambiente BIMOFFICE_DATA_DIR.
DATA_DIR = Path(os.environ.get("BIMOFFICE_DATA_DIR", BASE_DIR / "data")).resolve()
DOCUMENTS_DIR = DATA_DIR / "documents"
DATABASE_DIR = DATA_DIR / "database"
EMBEDDINGS_DIR = DATA_DIR / "embeddings"
BACKUPS_DIR = DATA_DIR / "backups"
LOGS_DIR = DATA_DIR / "logs"
DB_PATH = DATABASE_DIR / "bimoffice.db"

ALLOWED_EXTENSIONS = {".docx", ".pdf"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Parâmetros de divisão em trechos (caracteres)
CHUNK_TARGET_CHARS = 1000
CHUNK_MAX_CHARS = 1800
CHUNK_MIN_CHARS = 150


def ensure_dirs() -> None:
    for d in (DOCUMENTS_DIR, DATABASE_DIR, EMBEDDINGS_DIR, BACKUPS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)

# ------------------------------------------------------------------ Etapa 2: pesquisa semântica
# Modelo local de embeddings (roda no próprio computador; nenhum texto sai da máquina).
EMBEDDING_MODEL = os.environ.get("BIMOFFICE_EMBEDDING_MODEL", "intfloat/multilingual-e5-base")
# Pasta onde o modelo baixado fica guardado (dentro de data/, fora do Git).
MODELS_DIR = EMBEDDINGS_DIR / "modelos"
EMBEDDING_BATCH_SIZE = 16
# Gerar os vetores logo ao importar/reindexar (se o modelo estiver disponível).
EMBED_ON_IMPORT = os.environ.get("BIMOFFICE_EMBED_ON_IMPORT", "1") == "1"
# Pesquisa híbrida: quantos candidatos cada busca fornece e constante k da fusão RRF.
HYBRID_CANDIDATES = 50
RRF_K = 60

# ------------------------------------------------------------------ acesso pela web
# Origens (sites) que podem chamar a API pelo navegador. Separe por vírgula.
# Inclui o GitHub Pages do projeto e o próprio computador.
CORS_ORIGINS = [o.strip() for o in os.environ.get(
    "BIMOFFICE_CORS_ORIGINS",
    "http://127.0.0.1:8000,http://localhost:8000,https://brunno100barros-del.github.io",
).split(",") if o.strip()]
# Senha de acesso à API (opcional). Se definida, toda chamada /api/* precisa do cabeçalho
# "Authorization: Bearer <senha>". Obrigatória quando o backend estiver na internet.
API_TOKEN = os.environ.get("BIMOFFICE_API_TOKEN", "")
FRONTEND_DIR = BASE_DIR / "frontend"
