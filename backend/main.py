"""Ponto de entrada da API: uvicorn backend.main:app

Também serve a interface web (pasta frontend/) em http://127.0.0.1:8000/
"""
from __future__ import annotations

import importlib.util
import logging
import secrets
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware

from backend import config
from backend.database.db import init_db
from backend.routes import library, search
from backend.semantic_search.providers import get_provider

PUBLIC_PATHS = {"/api/health", "/api/config"}


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


app = FastAPI(title="BIMOFFICE Knowledge", version="0.3.0", lifespan=lifespan)


class TokenAuthMiddleware(BaseHTTPMiddleware):
    """Exige a senha da API (se configurada) em /api/*; nunca em pré-verificações CORS."""

    async def dispatch(self, request: Request, call_next):
        token = config.API_TOKEN
        path = request.url.path
        if (token and path.startswith("/api/") and path not in PUBLIC_PATHS
                and request.method != "OPTIONS"):
            sent = request.headers.get("authorization", "")
            if not secrets.compare_digest(sent, f"Bearer {token}"):
                return JSONResponse({"detail": "Acesso não autorizado: informe a senha da API."},
                                    status_code=401)
        return await call_next(request)


# ordem: o último adicionado é o mais externo
app.add_middleware(TokenAuthMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    # permite a página do GitHub Pages (internet) chamar o backend no próprio PC (Chrome)
    allow_private_network=True,
)

app.include_router(library.router)
app.include_router(search.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/api/config")
def public_config():
    """O que este backend oferece (a interface usa para mostrar só o que funciona)."""
    model_dir = config.MODELS_DIR / ("models--" + get_provider().name.replace("/", "--"))
    return {
        "version": app.version,
        "auth_required": bool(config.API_TOKEN),
        "allowed_extensions": sorted(config.ALLOWED_EXTENSIONS),
        "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
        "semantic": {
            "model": get_provider().name,
            "package_installed": importlib.util.find_spec("sentence_transformers") is not None,
            "model_downloaded": model_dir.exists(),
        },
        "gdrive": {
            "available": False,
            "reason": "Integração com o Google Drive ainda não implementada: depende de "
                      "credenciais OAuth criadas no Google Cloud (Etapa 5).",
        },
    }


# Interface web (deve ser o último: atende tudo que não é /api nem /docs)
if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
