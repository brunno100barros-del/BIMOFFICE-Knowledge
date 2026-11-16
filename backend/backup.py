"""Backup, restauração e migração para a nuvem.

    python -m backend.backup backup  <pasta_destino>          # banco + arquivos originais + manifesto
    python -m backend.backup restore <pasta_do_backup>        # restaura num banco/armazenamento VAZIOS
    python -m backend.backup migrar  <bimoffice.db> <pasta_data>   # SQLite local -> banco/armazenamento atuais

Usa a configuração atual (BIMOFFICE_DATABASE_URL, BIMOFFICE_STORAGE...). O manifesto guarda o SHA-256 de
cada arquivo: a restauração confere a integridade de tudo.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from backend import config
from backend.database.db import dialect, get_conn, init_db
from backend.storage import get_storage

# ordem respeita as chaves estrangeiras
TABLES = ["documents", "sections", "chunks", "projects", "project_files", "ifc_models", "ifc_elements", "jobs",
          "project_history", "memorials", "memorial_chapters", "memorial_versions", "users", "project_members",
          "audit_log"]


class BackupError(RuntimeError):
    pass


def _file_keys() -> list[str]:
    with get_conn() as conn:
        docs = [f"documents/{r[0]}" for r in conn.execute("SELECT DISTINCT stored_path FROM documents")]
        files = [f"projects/{r[0]}" for r in conn.execute("SELECT DISTINCT stored_path FROM project_files")]
    return docs + files


def backup(dest_root: Path) -> Path:
    """Cria <dest_root>/bimoffice_backup_<data>/ com banco, arquivos e manifesto. Retorna a pasta."""
    dest = Path(dest_root) / f"bimoffice_backup_{datetime.now():%Y%m%d_%H%M%S}"
    (dest / "arquivos").mkdir(parents=True)
    if dialect() == "postgres":
        if not shutil.which("pg_dump"):
            raise BackupError("pg_dump não encontrado (instale o cliente PostgreSQL).")
        subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--file", str(dest / "banco.dump"),
                        config.DATABASE_URL], check=True, capture_output=True, timeout=3600)
        db_file = "banco.dump"
    else:
        src, dst = sqlite3.connect(config.DB_PATH), sqlite3.connect(dest / "banco.db")
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        db_file = "banco.db"
    st = get_storage()
    files, missing = {}, []
    for key in _file_keys():
        out = dest / "arquivos" / key
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            with st.local_path(key) as p:
                shutil.copyfile(p, out)
        except Exception:
            missing.append(key)
            continue
        files[key] = hashlib.sha256(out.read_bytes()).hexdigest()
    with get_conn() as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    manifest = {"formato": "bimoffice-backup/1", "criado_em": datetime.now().isoformat(timespec="seconds"),
                "banco": {"dialeto": dialect(), "arquivo": db_file}, "contagens": counts,
                "arquivos": files, "arquivos_ausentes": missing}
    (dest / "manifesto.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    return dest


def _empty_db() -> bool:
    with get_conn() as conn:
        try:
            return sum(conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("documents", "projects")) == 0
        except Exception:
            return True


def restore(src: Path) -> dict:
    """Restaura num banco e armazenamento VAZIOS (não sobrescreve dados existentes)."""
    src = Path(src)
    man = json.loads((src / "manifesto.json").read_text(encoding="utf-8"))
    if man["banco"]["dialeto"] != dialect():
        raise BackupError(f"Backup de {man['banco']['dialeto']} não pode ser restaurado em {dialect()} "
                          "(use 'migrar' para levar SQLite à nuvem).")
    # 1) confere a integridade de TODO o backup antes de mexer em qualquer coisa
    for key, sha in man["arquivos"].items():
        f = src / "arquivos" / key
        if not f.exists() or hashlib.sha256(f.read_bytes()).hexdigest() != sha:
            raise BackupError(f"Arquivo corrompido ou ausente no backup: {key}")
    if not (src / man["banco"]["arquivo"]).exists():
        raise BackupError("Arquivo do banco ausente no backup.")
    if not _empty_db():
        raise BackupError("O banco de destino já tem dados: restaure num banco vazio.")
    # 2) arquivos
    st = get_storage()
    for key in man["arquivos"]:
        f = src / "arquivos" / key
        if not st.exists(key):
            tmp = src / "arquivos" / (key + ".restaurando")
            shutil.copyfile(f, tmp)
            st.put_file(key, tmp)
    # 3) banco
    if dialect() == "postgres":
        import psycopg
        with psycopg.connect(config.DATABASE_URL, autocommit=True) as c:  # o pg_restore recria o esquema inteiro
            c.execute("DROP SCHEMA IF EXISTS public CASCADE")
            c.execute("CREATE SCHEMA public")
        r = subprocess.run(["pg_restore", "--no-owner", "--dbname", config.DATABASE_URL, str(src / "banco.dump")],
                           capture_output=True, text=True, timeout=3600)
        bad = _restore_errors(r.stderr) if r.returncode != 0 else []
        if bad:
            raise BackupError(f"pg_restore falhou: {' | '.join(bad)[-500:]}")
    else:
        config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src / "banco.db", config.DB_PATH)
    init_db()
    with get_conn() as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in TABLES}
    if counts != man["contagens"]:
        raise BackupError(f"Contagens diferentes após restaurar: {counts} x {man['contagens']}")
    return {"restaurado": str(src), "contagens": counts, "arquivos": len(man["arquivos"])}


# pg_dump mais novo que o servidor grava ajustes que o servidor antigo não conhece (ex.: pg_dump 17 -> PostgreSQL 16).
# São só parâmetros da sessão de restauração, sem efeito nos dados; as contagens são conferidas depois.
_HARMLESS = ('unrecognized configuration parameter "transaction_timeout"',)


def _restore_errors(stderr: str) -> list[str]:
    errs = [ln.strip() for ln in stderr.splitlines() if "ERROR:" in ln]
    return [e for e in errs if not any(h in e for h in _HARMLESS)]


def migrate_sqlite(sqlite_path: Path, data_dir: Path) -> dict:
    """Copia um banco SQLite local (versões anteriores) + seus arquivos para o banco/armazenamento ATUAIS
    (ex.: PostgreSQL + S3 na nuvem). Os ids são preservados; o destino precisa estar vazio."""
    if not _empty_db():
        raise BackupError("O banco de destino já tem dados: a migração exige um banco vazio.")
    init_db()
    src = sqlite3.connect(sqlite_path)
    src.row_factory = sqlite3.Row
    copied = {}
    try:
        for t in TABLES:
            try:
                rows = src.execute(f"SELECT * FROM {t}").fetchall()
            except sqlite3.OperationalError:
                copied[t] = 0  # tabela ainda não existia na versão antiga
                continue
            if not rows:
                copied[t] = 0
                continue
            with get_conn() as conn:
                dest_cols = _columns(conn, t)
                cols = [c for c in rows[0].keys() if c in dest_cols]
                sql = f"INSERT INTO {t}({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})"
                for r in rows:
                    conn.execute(sql + (" RETURNING 1" if dialect() == "postgres" and t != "project_members" else ""),
                                 [r[c] for c in cols])
                if dialect() == "postgres" and "id" in cols:
                    conn.execute(f"SELECT setval(pg_get_serial_sequence('{t}', 'id'), (SELECT MAX(id) FROM {t}))")
            copied[t] = len(rows)
    finally:
        src.close()
    st = get_storage()
    sent = 0
    for key in _file_keys():
        local = Path(data_dir) / key
        if local.exists() and not st.exists(key):
            tmp = local.with_name(local.name + ".migrando")
            shutil.copyfile(local, tmp)
            st.put_file(key, tmp)
            sent += 1
    return {"linhas": copied, "arquivos_enviados": sent}


def _columns(conn, table: str) -> set[str]:
    if dialect() == "postgres":
        return {r[0] for r in conn.execute("SELECT column_name FROM information_schema.columns WHERE table_name=?", (table,))}
    return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[0] == "backup":
        print("Backup criado em:", backup(Path(argv[1])))
    elif len(argv) >= 2 and argv[0] == "restore":
        print(json.dumps(restore(Path(argv[1])), ensure_ascii=False, indent=1))
    elif len(argv) >= 3 and argv[0] == "migrar":
        print(json.dumps(migrate_sqlite(Path(argv[1]), Path(argv[2])), ensure_ascii=False, indent=1))
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
