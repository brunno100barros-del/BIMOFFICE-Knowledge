"""Worker separado: retomada só de tarefas paradas, tempo limite, processo independente e concorrência."""
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

pytest.importorskip("ifcopenshell")

from backend import config, jobs  # noqa: E402
from backend.database.db import dialect, get_conn, init_db  # noqa: E402
from backend.projects import service as psvc  # noqa: E402
from tests.ifc_factory import build_model  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent


def _enqueue_ifc(tmp_path, name="m.ifc"):
    p = psvc.create_project("P")
    f = build_model(tmp_path / name, "IFC4")
    with open(f, "rb") as fh:
        return psvc.store_file(p["id"], name, fh)


def test_recover_only_requeues_stale_jobs(tmp_path):
    _, j1 = _enqueue_ifc(tmp_path, "a.ifc")
    (tmp_path / "b").mkdir()
    _, j2 = _enqueue_ifc(tmp_path / "b", "b.ifc")
    with get_conn() as conn:  # j1: worker vivo (sinal de vida agora) · j2: worker parado há 1 hora
        conn.execute("UPDATE jobs SET status='executando', heartbeat_at=? WHERE id=?", (jobs._utc(), j1["id"]))
        conn.execute("UPDATE jobs SET status='executando', heartbeat_at=? WHERE id=?", (jobs._utc(-3600), j2["id"]))
    assert jobs.recover() == 1
    assert jobs.get(j1["id"])["status"] == "executando"
    assert jobs.get(j2["id"])["status"] == "na fila"


def test_job_timeout(tmp_path, monkeypatch):
    f, job = _enqueue_ifc(tmp_path)
    monkeypatch.setattr(config, "JOB_TIMEOUT_SECONDS", -1)
    jobs.run_pending()
    j = jobs.get(job["id"])
    assert j["status"] == "erro" and "Tempo limite" in j["error"]
    assert psvc.get_file(f["id"])["status"] == "erro"


@pytest.mark.skipif(os.environ.get("BIMOFFICE_TEST_STORAGE") == "s3", reason="S3 simulado só existe neste processo")
def test_worker_runs_as_separate_process(tmp_path, monkeypatch):
    if dialect() == "sqlite":  # o processo separado encontra o banco pelo caminho padrão da pasta de dados
        monkeypatch.setattr(config, "DB_PATH", tmp_path / "database" / "bimoffice.db")
        init_db()
    f, job = _enqueue_ifc(tmp_path)
    env = {**os.environ, "BIMOFFICE_DATA_DIR": str(tmp_path), "BIMOFFICE_DATABASE_URL": config.DATABASE_URL}
    r = subprocess.run([sys.executable, "-m", "backend.worker", "--once"], cwd=ROOT, env=env,
                       capture_output=True, text=True, timeout=180)
    assert r.returncode == 0, r.stderr[-800:]
    assert jobs.get(job["id"])["status"] == "concluído"
    assert psvc.get_file(f["id"])["ifc_model"]["n_elements"] == 18


@pytest.mark.skipif(not os.environ.get("BIMOFFICE_TEST_DATABASE_URL"), reason="concorrência real só no PostgreSQL")
def test_concurrent_workers_never_take_the_same_job(tmp_path):
    ids = []
    for i in range(6):
        d = tmp_path / str(i)
        d.mkdir()
        ids.append(_enqueue_ifc(d, f"m{i}.ifc")[1]["id"])
    taken, lock = [], threading.Lock()

    def worker():
        while True:
            j = jobs._claim()
            if not j:
                return
            with lock:
                taken.append(j["id"])

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(taken) == sorted(ids)            # todas pegas, nenhuma duas vezes
