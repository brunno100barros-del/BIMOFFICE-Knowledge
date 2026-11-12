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

ALLOWED_EXTENSIONS = {".docx"}
MAX_UPLOAD_BYTES = 50 * 1024 * 1024  # 50 MB

# Parâmetros de divisão em trechos (caracteres)
CHUNK_TARGET_CHARS = 1000
CHUNK_MAX_CHARS = 1800
CHUNK_MIN_CHARS = 150


def ensure_dirs() -> None:
    for d in (DOCUMENTS_DIR, DATABASE_DIR, EMBEDDINGS_DIR, BACKUPS_DIR, LOGS_DIR):
        d.mkdir(parents=True, exist_ok=True)
