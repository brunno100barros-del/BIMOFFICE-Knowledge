"""Worker de processamento (serviço separado na nuvem).

    python -m backend.worker          # roda continuamente (processa a fila do banco)
    python -m backend.worker --once   # processa o que estiver na fila e termina

Na nuvem, a API roda com BIMOFFICE_JOB_WORKER=0 e um ou mais workers rodam este módulo, compartilhando
o mesmo banco PostgreSQL (cada tarefa é pega por um só worker) e o mesmo armazenamento S3.
Limites de memória/CPU são definidos no container (docker-compose / serviço de nuvem).
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys

from backend import jobs
from backend.database.db import init_db
from backend.projects import service as _projects  # noqa: F401  (registra a tarefa ifc_parse)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Worker do BIMOFFICE Knowledge")
    ap.add_argument("--once", action="store_true", help="processa a fila atual e termina")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    log = logging.getLogger("bimoffice.worker")
    init_db()
    if args.once:
        jobs.recover()
        n = jobs.run_pending()
        log.info("Fila processada: %s tarefa(s)", n)
        return 0
    stop = []
    signal.signal(signal.SIGTERM, lambda *_: (stop.append(1), jobs.stop_worker()))
    log.info("Worker %s iniciado", jobs.WORKER_ID)
    jobs.start_worker()
    try:
        signal.pause() if hasattr(signal, "pause") else jobs._thread.join()
    except KeyboardInterrupt:
        pass
    jobs.stop_worker()
    return 0


if __name__ == "__main__":
    sys.exit(main())
