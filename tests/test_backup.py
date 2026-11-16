"""Backup, restauração (ida e volta completa) e migração SQLite -> banco atual (PostgreSQL)."""
import json
import os

import pytest

pytest.importorskip("ifcopenshell")

from backend import backup, config, jobs  # noqa: E402
from backend.database.db import dialect, get_conn, init_db  # noqa: E402
from backend.memorials import service as msvc  # noqa: E402
from backend.projects import service as psvc  # noqa: E402
from backend.semantic_search import vector_store  # noqa: E402
from backend.services import library_service as lib  # noqa: E402
from backend.storage import get_storage  # noqa: E402
from tests.conftest import make_docx  # noqa: E402
from tests.ifc_factory import build_model  # noqa: E402


def _populate(tmp_path):
    lib.import_document("a.docx", make_docx(tmp_path / "a.docx").read_bytes(), {"unit": "Porto Velho"})
    vector_store.index_pending()
    p = psvc.create_project("Projeto Backup")
    ifc = build_model(tmp_path / "m.ifc", "IFC4")
    with open(ifc, "rb") as fh:
        psvc.store_file(p["id"], "m.ifc", fh)
    jobs.run_pending()
    m = msvc.create_memorial(p["id"])
    msvc.update_chapter(m["chapters"][0]["id"], text="Texto revisado pelo engenheiro.")
    return p, m, ifc.read_bytes()


def _switch_to_empty_target(tmp_path, monkeypatch, name):
    """Simula um servidor novo: banco e armazenamento vazios."""
    new = tmp_path / name
    monkeypatch.setattr(config, "DOCUMENTS_DIR", new / "documents")
    monkeypatch.setattr(config, "PROJECT_FILES_DIR", new / "projects")
    monkeypatch.setattr(config, "S3_PREFIX", f"{name}/")
    if dialect() == "postgres":
        import psycopg
        with psycopg.connect(config.DATABASE_URL, autocommit=True) as c:
            c.execute("DROP SCHEMA IF EXISTS public CASCADE")
            c.execute("CREATE SCHEMA public")
    else:
        monkeypatch.setattr(config, "DB_PATH", new / "database" / "novo.db")
    init_db()


def test_backup_and_restore_round_trip(tmp_path, monkeypatch):
    p, m, ifc_bytes = _populate(tmp_path)
    dest = backup.backup(tmp_path / "backups")
    man = json.loads((dest / "manifesto.json").read_text(encoding="utf-8"))
    assert man["contagens"]["ifc_elements"] == 18 and len(man["arquivos"]) == 2 and not man["arquivos_ausentes"]
    _switch_to_empty_target(tmp_path, monkeypatch, "servidor_novo")
    assert lib.list_documents() == []                                  # destino realmente vazio
    r = backup.restore(dest)
    assert r["contagens"] == man["contagens"]
    # tudo de volta: arquivos idênticos, busca, inventário, memorial com a edição
    f = psvc.list_files(p["id"])[0]
    with get_storage().local_path(psvc.file_key(f["id"])) as local:
        assert local.read_bytes() == ifc_bytes
    assert lib.search_text("sanitarios")
    assert psvc.list_models(p["id"])[0]["n_elements"] == 18
    assert msvc.get_memorial(m["id"])["chapters"][0]["text"] == "Texto revisado pelo engenheiro."
    # novos registros continuam a numeração (sequências restauradas)
    assert psvc.create_project("Depois do restore")["id"] > p["id"]


def test_restore_refuses_non_empty_database_and_corrupted_files(tmp_path):
    _populate(tmp_path)
    dest = backup.backup(tmp_path / "backups")
    with pytest.raises(backup.BackupError, match="vazio"):
        backup.restore(dest)
    key = next(iter(json.loads((dest / "manifesto.json").read_text(encoding="utf-8"))["arquivos"]))
    (dest / "arquivos" / key).write_bytes(b"adulterado")
    with pytest.raises(backup.BackupError, match="corrompido"):
        backup.restore(dest)


@pytest.mark.skipif(not os.environ.get("BIMOFFICE_TEST_DATABASE_URL"), reason="migração para a nuvem: destino PostgreSQL")
def test_migrate_local_sqlite_to_postgres(tmp_path, monkeypatch):
    # 1) dados num SQLite local, como o programa instalado no computador do usuário
    pg = config.DATABASE_URL
    local_data = tmp_path / "pc_do_usuario"
    monkeypatch.setattr(config, "DATABASE_URL", "")
    monkeypatch.setattr(config, "DB_PATH", local_data / "database" / "bimoffice.db")
    monkeypatch.setattr(config, "DOCUMENTS_DIR", local_data / "documents")
    monkeypatch.setattr(config, "PROJECT_FILES_DIR", local_data / "projects")
    monkeypatch.setattr(config, "STORAGE", "local")
    init_db()
    p, m, ifc_bytes = _populate(tmp_path)
    with get_conn() as conn:
        n_chunks = conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    sqlite_db = config.DB_PATH
    # 2) destino "nuvem": PostgreSQL vazio + armazenamento novo
    monkeypatch.setattr(config, "DATABASE_URL", pg)
    _switch_to_empty_target(tmp_path, monkeypatch, "nuvem")
    r = backup.migrate_sqlite(sqlite_db, local_data)
    assert r["linhas"]["ifc_elements"] == 18 and r["linhas"]["chunks"] == n_chunks and r["arquivos_enviados"] == 2
    assert lib.search_text("sanitarios")                               # busca textual reconstruída no PostgreSQL
    assert psvc.get_project(p["id"])["name"] == "Projeto Backup"       # ids preservados
    assert msvc.get_memorial(m["id"])["chapters"][0]["text"] == "Texto revisado pelo engenheiro."
    f = psvc.list_files(p["id"])[0]
    with get_storage().local_path(psvc.file_key(f["id"])) as local:
        assert local.read_bytes() == ifc_bytes
    assert psvc.create_project("Novo na nuvem")["id"] > p["id"]        # sequência ajustada


def test_restore_ignores_only_harmless_version_settings():
    """pg_dump mais novo que o servidor (ex.: 17 -> 16) gera 'SET transaction_timeout': ignorado; o resto não."""
    ok = ('pg_restore: error: could not execute query: ERROR:  unrecognized configuration parameter '
          '"transaction_timeout"\nCommand was: SET transaction_timeout = 0;\n')
    assert backup._restore_errors(ok) == []
    bad = ok + 'pg_restore: error: could not execute query: ERROR:  relation "chunks" does not exist\n'
    assert len(backup._restore_errors(bad)) == 1
