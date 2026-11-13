"""Ponto de entrada da API: uvicorn backend.main:app"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI

from backend import config
from backend.database.db import init_db
from backend.routes import library, search


def _setup_logging() -> None:
    config.ensure_dirs()
    handler = RotatingFileHandler(
        config.LOGS_DIR / "bimoffice.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger("bimoffice")
    root.setLevel(logging.INFO)
    if not root.handlers:
        root.addHandler(handler)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _setup_logging()
    init_db()
    yield


app = FastAPI(title="BIMOFFICE Knowledge", version="0.2.0", lifespan=lifespan)
app.include_router(library.router)
app.include_router(search.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}
