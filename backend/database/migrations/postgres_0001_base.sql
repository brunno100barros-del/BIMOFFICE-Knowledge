-- Esquema PostgreSQL do BIMOFFICE Knowledge (equivalente ao esquema SQLite de backend/database/db.py)
CREATE EXTENSION IF NOT EXISTS unaccent;
-- configuração de busca sem acento e sem maiúsculas (equivalente ao FTS5 unicode61 remove_diacritics)
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_ts_config WHERE cfgname = 'bimoffice') THEN
    CREATE TEXT SEARCH CONFIGURATION bimoffice (COPY = simple);
    ALTER TEXT SEARCH CONFIGURATION bimoffice ALTER MAPPING FOR hword, hword_part, word WITH unaccent, simple;
  END IF;
END $$;


CREATE TABLE IF NOT EXISTS documents (
    id                BIGSERIAL PRIMARY KEY,
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
    created_at        TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    indexed_at        TEXT,
    deleted_at        TEXT,                             -- exclusão lógica (lixeira)
    file_type         TEXT NOT NULL DEFAULT 'docx',
    source            TEXT NOT NULL DEFAULT 'upload',
    source_ref        TEXT NOT NULL DEFAULT '{}'
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_documents_sha_active
    ON documents(sha256) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS sections (
    id          BIGSERIAL PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    level       INTEGER NOT NULL,
    title       TEXT NOT NULL,
    path        TEXT NOT NULL,        -- "1 OBRAS > 1.2 Revestimentos"
    position    INTEGER NOT NULL      -- índice do bloco no documento original
);
CREATE INDEX IF NOT EXISTS ix_sections_doc ON sections(document_id);

CREATE TABLE IF NOT EXISTS chunks (
    id              BIGSERIAL PRIMARY KEY,
    document_id     INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    section_id      INTEGER REFERENCES sections(id) ON DELETE SET NULL,
    section_path    TEXT NOT NULL,
    position_start  INTEGER NOT NULL, -- primeiro bloco (parágrafo/tabela) no original
    position_end    INTEGER NOT NULL,
    est_page        INTEGER,          -- página ESTIMADA (o DOCX não guarda páginas)
    text            TEXT NOT NULL,
    char_count      INTEGER NOT NULL,
    embedding       BYTEA,             -- preenchido na Etapa 2
    embedding_model TEXT,
    tsv             tsvector          -- busca textual (equivalente ao FTS5), mantido por gatilho
);
CREATE INDEX IF NOT EXISTS ix_chunks_tsv ON chunks USING GIN (tsv);
CREATE OR REPLACE FUNCTION bimoffice_chunks_tsv() RETURNS trigger AS $$
BEGIN
  NEW.tsv := to_tsvector('bimoffice', coalesce(NEW.text, '') || ' ' || coalesce(NEW.section_path, ''));
  RETURN NEW;
END $$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS chunks_tsv ON chunks;
CREATE TRIGGER chunks_tsv BEFORE INSERT OR UPDATE OF text, section_path ON chunks
  FOR EACH ROW EXECUTE FUNCTION bimoffice_chunks_tsv();
CREATE INDEX IF NOT EXISTS ix_chunks_doc ON chunks(document_id);



-- ================================================================ PROJETOS (v0.4)
-- Separado da biblioteca: projetos em elaboração nunca alteram a biblioteca de memoriais.
CREATE TABLE IF NOT EXISTS projects (
    id          BIGSERIAL PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    location    TEXT NOT NULL DEFAULT '',
    disciplines TEXT NOT NULL DEFAULT '[]',            -- lista JSON
    created_at  TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    updated_at  TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    deleted_at  TEXT
);

CREATE TABLE IF NOT EXISTS project_files (
    id                BIGSERIAL PRIMARY KEY,
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
    created_at        TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    deleted_at        TEXT
);
CREATE INDEX IF NOT EXISTS ix_pfiles_project ON project_files(project_id);
CREATE UNIQUE INDEX IF NOT EXISTS ux_pfiles_sha_active
    ON project_files(project_id, sha256) WHERE deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS ifc_models (
    id            BIGSERIAL PRIMARY KEY,
    file_id       INTEGER NOT NULL UNIQUE REFERENCES project_files(id) ON DELETE CASCADE,
    project_id    INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    schema_name   TEXT NOT NULL,
    header        TEXT NOT NULL DEFAULT '{}',          -- JSON: aplicativo, data, nome do projeto IFC
    units         TEXT NOT NULL DEFAULT '{}',          -- JSON: escalas para SI
    summary       TEXT NOT NULL DEFAULT '{}',          -- JSON: inventário técnico
    n_elements    INTEGER NOT NULL DEFAULT 0,
    parse_seconds REAL,
    processed_at  TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
);

CREATE TABLE IF NOT EXISTS ifc_elements (
    id              BIGSERIAL PRIMARY KEY,
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
    id               BIGSERIAL PRIMARY KEY,
    kind             TEXT NOT NULL,                    -- ex.: ifc_parse
    project_id       INTEGER,
    target_id        INTEGER,                          -- ex.: id do arquivo
    status           TEXT NOT NULL DEFAULT 'na fila',  -- na fila | executando | concluído | erro | cancelado
    progress         REAL NOT NULL DEFAULT 0,
    message          TEXT NOT NULL DEFAULT '',
    error            TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    attempts         INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    started_at       TEXT,
    finished_at      TEXT
);
CREATE INDEX IF NOT EXISTS ix_jobs_status ON jobs(status);

CREATE TABLE IF NOT EXISTS project_history (
    id         BIGSERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    at         TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    event      TEXT NOT NULL,
    detail     TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS ix_phist_project ON project_history(project_id);

-- ================================================================ MEMORIAL EM ELABORAÇÃO (v0.5)
-- Separado da biblioteca: editar o memorial nunca altera documentos da biblioteca.
CREATE TABLE IF NOT EXISTS memorials (
    id         BIGSERIAL PRIMARY KEY,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    model_id   INTEGER REFERENCES ifc_models(id) ON DELETE SET NULL,
    title      TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    updated_at TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    deleted_at TEXT
);
CREATE TABLE IF NOT EXISTS memorial_chapters (
    id             BIGSERIAL PRIMARY KEY,
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
    updated_at     TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS'))
);
CREATE INDEX IF NOT EXISTS ix_mchap_memorial ON memorial_chapters(memorial_id);
CREATE TABLE IF NOT EXISTS memorial_versions (
    id         BIGSERIAL PRIMARY KEY,
    chapter_id INTEGER NOT NULL REFERENCES memorial_chapters(id) ON DELETE CASCADE,
    at         TEXT NOT NULL DEFAULT (to_char(now() at time zone 'utc', 'YYYY-MM-DD HH24:MI:SS')),
    event      TEXT NOT NULL,
    title      TEXT NOT NULL,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_mver_chapter ON memorial_versions(chapter_id);
