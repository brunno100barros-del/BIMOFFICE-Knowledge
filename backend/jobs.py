"""Tarefas em segundo plano (processamento pesado fora da requisição HTTP).

- A fila fica no banco (tabela `jobs`): sobrevive a reinícios.
- Um "trabalhador" (thread) executa uma tarefa por vez, informando progresso.
- Cancelamento: o usuário pede, a tarefa para no próximo ponto de verificação.
- Retomada: ao ligar o servidor, tarefas que estavam "executando" (servidor caiu)
  voltam para a fila, até JOB_MAX_ATTEMPTS tentativas.
"""
from __future__ import annotations

import logging
import threading
import traceback
from collections.abc import Callable

from backend import config
from backend.database.db import get_conn

log = logging.getLogger("bimoffice.jobs")
HANDLERS: dict[str, Callable] = {}
_wake = threading.Event()
_stop = threading.Event()
_thread: threading.Thread | None = None


class JobCancelled(Exception):
    pass


def handler(kind: str):
    def deco(fn):
        HANDLERS[kind] = fn
        return fn
    return deco


class JobContext:
    def __init__(self, job_id: int):
        self.job_id = job_id

    def progress(self, fraction: float, message: str = "") -> None:
        with get_conn() as conn:
            conn.execute("UPDATE jobs SET progress=?, message=? WHERE id=?",
                         (max(0.0, min(1.0, fraction)), message, self.job_id))

    def cancelled(self) -> bool:
        with get_conn() as conn:
            r = conn.execute("SELECT cancel_requested FROM jobs WHERE id=?", (self.job_id,)).fetchone()
        return bool(r and r["cancel_requested"])


def enqueue(kind: str, project_id: int | None, target_id: int | None) -> dict:
    with get_conn() as conn:
        cur = conn.execute("INSERT INTO jobs(kind, project_id, target_id, message) VALUES (?,?,?,?)",
                           (kind, project_id, target_id, "Aguardando na fila…"))
        jid = cur.lastrowid
    _wake.set()
    return get(jid)


def get(job_id: int) -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    return dict(r) if r else None


def list_jobs(project_id: int | None = None, active_only: bool = False, limit: int = 50) -> list[dict]:
    sql, params = "SELECT * FROM jobs WHERE 1=1", []
    if project_id is not None:
        sql += " AND project_id=?"
        params.append(project_id)
    if active_only:
        sql += " AND status IN ('na fila','executando')"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    with get_conn() as conn:
        return [dict(r) for r in conn.execute(sql, params)]


def cancel(job_id: int) -> dict | None:
    with get_conn() as conn:
        conn.execute("UPDATE jobs SET cancel_requested=1 WHERE id=? AND status IN ('na fila','executando')", (job_id,))
        conn.execute("""UPDATE jobs SET status='cancelado', finished_at=datetime('now'), message='Cancelado antes de iniciar'
                        WHERE id=? AND status='na fila'""", (job_id,))
    return get(job_id)


def recover() -> int:
    """Ao iniciar: tarefas interrompidas voltam para a fila (ou viram erro após muitas tentativas)."""
    with get_conn() as conn:
        conn.execute("""UPDATE jobs SET status='erro', finished_at=datetime('now'),
                        error='Interrompida várias vezes (servidor reiniciado durante o processamento).'
                        WHERE status='executando' AND attempts>=?""", (config.JOB_MAX_ATTEMPTS,))
        n = conn.execute("""UPDATE jobs SET status='na fila', message='Retomada após reinício do servidor'
                            WHERE status='executando'""").rowcount
    return n


def _claim() -> dict | None:
    with get_conn() as conn:
        r = conn.execute("SELECT * FROM jobs WHERE status='na fila' ORDER BY id LIMIT 1").fetchone()
        if not r:
            return None
        n = conn.execute("""UPDATE jobs SET status='executando', started_at=datetime('now'),
                            attempts=attempts+1, progress=0 WHERE id=? AND status='na fila'""", (r["id"],)).rowcount
    return dict(r) if n else None


def run_one() -> bool:
    """Executa a próxima tarefa da fila. Retorna False se a fila estava vazia."""
    job = _claim()
    if not job:
        return False
    ctx = JobContext(job["id"])
    fn = HANDLERS.get(job["kind"])
    try:
        if fn is None:
            raise RuntimeError(f"Tipo de tarefa desconhecido: {job['kind']}")
        fn(job, ctx)
        status, err, msg = "concluído", None, "Concluído"
    except JobCancelled:
        status, err, msg = "cancelado", None, "Cancelado pelo usuário"
    except Exception as e:
        log.error("Tarefa %s falhou: %s\n%s", job["id"], e, traceback.format_exc())
        status, err, msg = "erro", str(e), "Falhou"
    with get_conn() as conn:
        conn.execute("""UPDATE jobs SET status=?, error=?, message=?, finished_at=datetime('now'),
                        progress=CASE WHEN ?='concluído' THEN 1 ELSE progress END WHERE id=?""",
                     (status, err, msg, status, job["id"]))
    return True


def run_pending() -> int:
    """Executa toda a fila no fluxo atual (usado em testes e scripts)."""
    n = 0
    while run_one():
        n += 1
    return n


def _loop():
    while not _stop.is_set():
        try:
            while run_one() and not _stop.is_set():
                pass
        except Exception:
            log.exception("Erro no trabalhador de tarefas")
        _wake.wait(timeout=2.0)
        _wake.clear()


def start_worker() -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    recovered = recover()
    if recovered:
        log.info("%s tarefa(s) retomada(s) após reinício", recovered)
    _thread = threading.Thread(target=_loop, name="bimoffice-jobs", daemon=True)
    _thread.start()


def stop_worker() -> None:
    _stop.set()
    _wake.set()
    if _thread:
        _thread.join(timeout=10)
