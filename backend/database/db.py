"""Banco de dados SQLite (metadados, seções, trechos) + FTS5 (busca textual)."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from backend import config

SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS documents (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    title             TEXT NOT NULL,
    unit              TEXT NOT NULL DEFAULT '',
    project           TEXT NOT NULL DEFAULT '',
    discipline        TEXT NOT NULL DEFAULT '',
    doc_date          TEXT NOT NULL DEFAULT '',
    description       TEXT NOT NULL DEFAULT '',
    tags              TEXT NOT NULL DEFAULT '[]',      -- lista JSON
    original_filename TEXT NOT NULL,
    sha256            TEXT NOT NULL,
    stored_path       TEXT NOT NULL,                   -- relativo a DOCUMENTS_DIR
    n_sections        INTEGER NOT NULL DEFAULT 0,
    n_chunks          INTEGER NOT NULL DEFAULT 0,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    indexed_at        TEXT,
    deleted_at        TEXT                              -- exclusão lógica (lixeira)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_sha_active
    ON documents(sha256) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS sections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    level       INTEGER NOT NULL,
    title       TEXT NOT NULL,
    path        TEXT NOT NULL,        -- "1 OBRAS > 1.2 Revestimentos"
    position    INTEGER NOT NULL      -- índice do bloco no documento original
);
CREATE INDEX IF NOT EXISTS ix_sections_doc ON sections(document_id);

CREATE TABLE IF NOT EXISTS chunks (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id      INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    section_path    TEXT NOT NULL,
    position_start  INTEGER NOT NULL, -- primeiro bloco (parágrafo/tabela) no original
    position_end    INTEGER NOT NULL,
    est_page        INTEGER,          -- página ESTIMADA (o DOCX não guarda páginas)
    text            TEXT NOT NULL,
    char_count      INTEGER NOT NULL,
    embedding       BLOB,             -- preenchido na Etapa 2
    embedding_model TEXT
);
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id);

CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
    text, section_path,
    content='chunks', content_rowid='id',
    tokenize='unicode61 remove_diacritics 2'
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE OF text, section_path ON chunks BEGIN
    INSERT INTO chunks_fts(chunks_fts, rowid, text, section_path)
    VALUES ('delete', old.id, old.text, old.section_path);
    INSERT INTO chunks_fts(rowid, text, section_path)
    VALUES (new.id, new.text, new.section_path);
END;
"""


def init_db(db_path: Path | None = None) -> None:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


@contextmanager
def get_conn(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    """Abre uma conexão com transação: commit ao sair, rollback em caso de erro."""
    path = db_path or config.DB_PATH
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
