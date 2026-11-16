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

-- ================================================================ PROJETOS (v0.4)
-- Separado da biblioteca: projetos em elaboração nunca alteram a biblioteca de memoriais.
CREATE TABLE IF NOT EXISTS projects (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    disciplines TEXT NOT NULL DEFAULT '[]',            -- lista JSON
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at  TEXT
);

CREATE TABLE IF NOT EXISTS project_files (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id        INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind              TEXT NOT NULL,                   -- ifc | pdf | docx | image
    original_filename TEXT NOT NULL,
    sha256            TEXT NOT NULL,
    stored_path       TEXT NOT NULL,                   -- relativo a PROJECT_FILES_DIR (somente leitura)
    size_bytes        INTEGER NOT NULL,
    discipline        TEXT NOT NULL DEFAULT '',
    version           INTEGER NOT NULL DEFAULT 1,      -- mesmo nome com conteúdo novo = nova versão
    previous_file_id  INTEGER REFERENCES project_files(id),
    status            TEXT NOT NULL DEFAULT 'armazenado', -- armazenado | na fila | processando | processado | erro | cancelado
    error             TEXT,
    created_at        TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_pfiles_project ON project_files(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pfiles_sha_active
    ON project_files(project_id, sha256) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS ifc_models (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    file_id       INTEGER NOT NULL UNIQUE REFERENCES project_files(id) ON DELETE CASCADE,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    schema_name   TEXT NOT NULL,
    header        TEXT NOT NULL DEFAULT '{}',          -- JSON: aplicativo, data, nome do projeto IFC
    units         TEXT NOT NULL DEFAULT '{}',          -- JSON: escalas para SI
    summary       TEXT NOT NULL DEFAULT '{}',          -- JSON: inventário técnico
    n_elements    INTEGER NOT NULL DEFAULT 0,
    parse_seconds REAL,
    processed_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS ifc_elements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    model_id        INTEGER NOT NULL REFERENCES ifc_models(id) ON DELETE CASCADE,
    project_id      INTEGER NOT NULL,
    global_id       TEXT,
    ifc_class       TEXT NOT NULL,
    predefined_type TEXT,
    name            TEXT,
    type_name       TEXT,
    storey          TEXT,
    discipline      TEXT NOT NULL,
    confidence      TEXT NOT NULL,                     -- alta | média | baixa
    missing         TEXT NOT NULL DEFAULT '[]',        -- JSON: informações não encontradas
    data            TEXT NOT NULL                      -- JSON completo (psets, materiais, quantidades, origem)
);
CREATE INDEX IF NOT EXISTS ix_ifcel_model ON ifc_elements(model_id);
CREATE INDEX IF NOT EXISTS ix_ifcel_disc ON ifc_elements(model_id, discipline);
CREATE INDEX IF NOT EXISTS ix_ifcel_class ON ifc_elements(model_id, ifc_class);

-- Tarefas em segundo plano (persistidas: sobrevivem a reinício e são retomadas)
CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    kind             TEXT NOT NULL,                    -- ex.: ifc_parse
    project_id       INTEGER,
    target_id        INTEGER,                          -- ex.: id do arquivo
    status           TEXT NOT NULL DEFAULT 'na fila',  -- na fila | executando | concluído | erro | cancelado
    progress         REAL NOT NULL DEFAULT 0,
    message          TEXT NOT NULL DEFAULT '',
    error            TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    attempts         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (datetime('now')),
    started_at       TEXT,
    finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS project_history (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    at         TEXT NOT NULL DEFAULT (datetime('now')),
    event      TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_phist_project ON project_history(project_id);

-- ================================================================ MEMORIAL EM ELABORAÇÃO (v0.5)
-- Separado da biblioteca: editar o memorial nunca altera documentos da biblioteca.
CREATE TABLE IF NOT EXISTS memorials (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_id   INTEGER REFERENCES ifc_models(id) ON DELETE SET NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now')),
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS memorial_chapters (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    memorial_id    INTEGER NOT NULL REFERENCES memorials(id) ON DELETE CASCADE,
    position       INTEGER NOT NULL,
    key            TEXT NOT NULL,                  -- ex.: vedacoes; "custom" para capítulos criados pelo usuário
    title          TEXT NOT NULL,
    generated_text TEXT NOT NULL DEFAULT '',       -- texto ORIGINAL gerado a partir do IFC (não é editado)
    text           TEXT NOT NULL DEFAULT '',       -- texto ATUAL (adaptado/revisado pelo usuário)
    status         TEXT NOT NULL DEFAULT 'rascunho', -- rascunho | aprovado
    facts          TEXT NOT NULL DEFAULT '[]',     -- dados do IFC usados (origem, método, GlobalIds)
    pending        TEXT NOT NULL DEFAULT '[]',     -- informações ausentes
    tables_json    TEXT NOT NULL DEFAULT '[]',     -- quadros (ambientes, esquadrias...)
    suggestions    TEXT NOT NULL DEFAULT '[]',     -- trechos de referência sugeridos (NÃO inseridos)
    inserted_refs  TEXT NOT NULL DEFAULT '[]',     -- trechos inseridos: texto ORIGINAL + origem
    query          TEXT NOT NULL DEFAULT '',
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS ix_mchap_memorial ON memorial_chapters(memorial_id);
CREATE TABLE IF NOT EXISTS memorial_versions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    chapter_id INTEGER NOT NULL REFERENCES memorial_chapters(id) ON DELETE CASCADE,
    at         TEXT NOT NULL DEFAULT (datetime('now')),
    event      TEXT NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mver_chapter ON memorial_versions(chapter_id);
"""


# Colunas acrescentadas depois da 1ª versão (migração automática, sem perder dados).
MIGRATIONS = {
    "documents": [
        ("file_type", "TEXT NOT NULL DEFAULT 'docx'"),      # docx | pdf
        ("source", "TEXT NOT NULL DEFAULT 'upload'"),       # upload | gdrive
        ("source_ref", "TEXT NOT NULL DEFAULT '{}'"),       # JSON: pasta/arquivo de origem
    ],
}


def _migrate(conn: sqlite3.Connection) -> None:
    for table, cols in MIGRATIONS.items():
        existing = {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
        for name, ddl in cols:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def init_db(db_path: Path | None = None) -> None:
    path = db_path or config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
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
