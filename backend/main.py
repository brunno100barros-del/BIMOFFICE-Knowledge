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
from starlette.concurrency import run_in_threadpool
from starlette.middleware.base import BaseHTTPMiddleware

from backend import auth, config, jobs
from backend.database.db import init_db
from backend.routes import auth as auth_routes, library, memorials, projects, search
from backend.semantic_search.providers import get_provider

PUBLIC_PATHS = {"/api/health", "/api/health/ready", "/api/config", "/api/auth/login"}


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
    auth.ensure_admin_from_env()
    if config.START_JOB_WORKER:
        jobs.start_worker()  # processamento pesado (IFC) em segundo plano
    yield
    jobs.stop_worker()


app = FastAPI(title="BIMOFFICE Knowledge", version="0.6.0", lifespan=lifespan)


class AccessMiddleware(BaseHTTPMiddleware):
    """Identifica o usuário, aplica as permissões (backend/auth.py) e registra a auditoria das alterações.

    - Senha da API (BIMOFFICE_API_TOKEN), se definida: vale como acesso de serviço (administrador).
    - BIMOFFICE_AUTH=on: exige sessão de login; BIMOFFICE_AUTH=off: uso local liberado.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if not path.startswith("/api/") or path in PUBLIC_PATHS or request.method == "OPTIONS":
            return await call_next(request)
        sent = request.headers.get("authorization", "")
        tok = sent.removeprefix("Bearer ").strip()
        user = None
        if config.API_TOKEN and secrets.compare_digest(sent, f"Bearer {config.API_TOKEN}"):
            user = {**auth.LOCAL_USER, "email": "servico", "name": "Acesso de serviço"}
        elif auth.enabled():
            user = await run_in_threadpool(auth.user_from_token, tok)
            if user is None:
                return JSONResponse({"detail": "Faça login para continuar."}, status_code=401)
        elif config.API_TOKEN:
            return JSONResponse({"detail": "Acesso não autorizado: informe a senha da API."}, status_code=401)
        else:
            user = auth.LOCAL_USER
        try:
            await run_in_threadpool(auth.authorize, user, request.method, path, dict(request.query_params))
        except auth.Forbidden as e:
            return JSONResponse({"detail": str(e)}, status_code=403)
        token = auth.current_user.set(user)
        try:
            response = await call_next(request)
        finally:
            auth.current_user.reset(token)
        if request.method not in ("GET", "HEAD") and auth.enabled():
            await run_in_threadpool(auth.audit, user.get("id"), user.get("email"), f"{request.method} {path}",
                                    response.status_code, request.client.host if request.client else "")
        return response


# ordem: o último adicionado é o mais externo
app.add_middleware(AccessMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.CORS_ORIGINS,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Content-Disposition"],  # nome do arquivo DOCX exportado
    # permite a página do GitHub Pages (internet) chamar o backend no próprio PC (Chrome)
    allow_private_network=True,
)

app.include_router(auth_routes.router)
app.include_router(library.router)
app.include_router(search.router)
app.include_router(projects.router)
app.include_router(memorials.router)


@app.get("/api/health")
def health():
    return {"status": "ok", "version": app.version}


def _ifc_status() -> dict:
    try:
        import ifcopenshell
        return {"available": True, "library": f"IfcOpenShell {ifcopenshell.version}",
                "schemas": ["IFC2X3", "IFC4", "IFC4X3"], "max_mb": config.MAX_IFC_BYTES // (1024 * 1024)}
    except Exception as e:  # biblioteca ausente: o resto do sistema continua funcionando
        return {"available": False, "reason": f"IfcOpenShell não instalado ({type(e).__name__})."}


@app.get("/api/health/ready")
def ready():
    """Pronto para atender? Confere banco e armazenamento (usado por Docker e pelo serviço de nuvem)."""
    from backend.database.db import dialect, get_conn
    from backend.storage import get_storage
    checks, ok = {}, True
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1").fetchone()
        checks["database"] = {"ok": True, "dialect": dialect()}
    except Exception as e:
        ok, checks["database"] = False, {"ok": False, "error": type(e).__name__}
    try:
        checks["storage"] = {"ok": True, **get_storage().check()}
    except Exception as e:
        ok, checks["storage"] = False, {"ok": False, "error": type(e).__name__}
    return JSONResponse({"status": "ok" if ok else "indisponível", "version": app.version, "checks": checks},
                        status_code=200 if ok else 503)


@app.get("/api/config")
def public_config():
    """O que este backend oferece (a interface usa para mostrar só o que funciona)."""
    model_dir = config.MODELS_DIR / ("models--" + get_provider().name.replace("/", "--"))
    return {
        "version": app.version,
        "auth_required": bool(config.API_TOKEN) and not auth.enabled(),
        "auth_mode": config.AUTH,
        "allowed_extensions": sorted(config.ALLOWED_EXTENSIONS),
        "max_upload_mb": config.MAX_UPLOAD_BYTES // (1024 * 1024),
        "semantic": {
            "model": get_provider().name,
            "package_installed": importlib.util.find_spec("sentence_transformers") is not None,
            "model_downloaded": model_dir.exists(),
        },
        "ifc": _ifc_status(),
        "gdrive": {
            "available": False,
            "reason": "Integração com o Google Drive ainda não implementada: depende de "
                      "credenciais OAuth criadas no Google Cloud (Etapa 5).",
        },
    }


# Interface web (deve ser o último: atende tudo que não é /api nem /docs)
if config.FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=config.FRONTEND_DIR, html=True), name="frontend")
