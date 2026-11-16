"""Armazenamento dos arquivos ORIGINAIS (DOCX, PDF, IFC, imagens): disco local ou objeto S3.

- Chave = "<área>/<sha256>.<ext>" (ex.: "documents/ab12….docx", "projects/cd34….ifc").
- Local (padrão): data/documents/ e data/projects/ — exatamente as pastas das versões anteriores.
- S3 (nuvem): BIMOFFICE_STORAGE=s3 + BIMOFFICE_S3_BUCKET (+ endpoint/região). Compatível com AWS S3,
  Google Cloud Storage (interoperabilidade S3), Cloudflare R2, MinIO, Backblaze B2...
  Credenciais SOMENTE por variáveis de ambiente padrão (AWS_ACCESS_KEY_ID/AWS_SECRET_ACCESS_KEY) ou
  identidade do serviço — nunca no código.
- Originais nunca são sobrescritos: gravar uma chave que já existe não faz nada (conteúdo = hash).
"""
from __future__ import annotations

import os
import shutil
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from backend import config


class StorageError(RuntimeError):
    pass


def _local_dir(area: str) -> Path:
    dirs = {"documents": config.DOCUMENTS_DIR, "projects": config.PROJECT_FILES_DIR}
    return dirs.get(area) or (config.DATA_DIR / area)


class LocalStorage:
    kind = "local"

    def path(self, key: str) -> Path:
        area, _, name = key.partition("/")
        if not name or "/" in name or ".." in key:
            raise StorageError(f"Chave inválida: {key}")
        return _local_dir(area) / name

    def exists(self, key: str) -> bool:
        return self.path(key).exists()

    def put_file(self, key: str, src: Path) -> bool:
        """Move o arquivo temporário para o destino. Retorna False se já existia (nada é sobrescrito)."""
        dest = self.path(key)
        if dest.exists():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), dest)
        os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)  # somente leitura
        return True

    def put_bytes(self, key: str, data: bytes) -> bool:
        dest = self.path(key)
        if dest.exists():
            return False
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        os.chmod(dest, stat.S_IRUSR | stat.S_IRGRP | stat.S_IROTH)
        return True

    def delete(self, key: str) -> None:
        """Só para desfazer uma importação que falhou (nunca apaga originais já registrados)."""
        p = self.path(key)
        if p.exists():
            os.chmod(p, stat.S_IRUSR | stat.S_IWUSR)
            p.unlink()

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        p = self.path(key)
        if not p.exists():
            raise StorageError("Arquivo original não encontrado no armazenamento.")
        yield p

    def iter_bytes(self, key: str, chunk: int = 1024 * 1024) -> Iterator[bytes]:
        with open(self.path(key), "rb") as fh:
            while True:
                b = fh.read(chunk)
                if not b:
                    return
                yield b

    def size(self, key: str) -> int:
        return self.path(key).stat().st_size

    def check(self) -> dict:
        for area in ("documents", "projects"):
            d = _local_dir(area)
            d.mkdir(parents=True, exist_ok=True)
            if not os.access(d, os.W_OK):
                raise StorageError(f"Sem permissão de escrita em {d}")
        return {"kind": "local", "path": str(config.DATA_DIR)}


class S3Storage:
    kind = "s3"

    def __init__(self):
        import boto3
        if not config.S3_BUCKET:
            raise StorageError("BIMOFFICE_S3_BUCKET não configurado.")
        self.bucket = config.S3_BUCKET
        self.prefix = config.S3_PREFIX
        self.client = boto3.client("s3", endpoint_url=config.S3_ENDPOINT_URL or None,
                                   region_name=config.S3_REGION or None)

    def _k(self, key: str) -> str:
        if ".." in key or key.startswith("/"):
            raise StorageError(f"Chave inválida: {key}")
        return f"{self.prefix}{key}"

    def exists(self, key: str) -> bool:
        from botocore.exceptions import ClientError
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._k(key))
            return True
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def put_file(self, key: str, src: Path) -> bool:
        if self.exists(key):
            Path(src).unlink(missing_ok=True)
            return False
        self.client.upload_file(str(src), self.bucket, self._k(key))
        Path(src).unlink(missing_ok=True)
        return True

    def put_bytes(self, key: str, data: bytes) -> bool:
        if self.exists(key):
            return False
        self.client.put_object(Bucket=self.bucket, Key=self._k(key), Body=data)
        return True

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._k(key))

    @contextmanager
    def local_path(self, key: str) -> Iterator[Path]:
        """Baixa para um arquivo temporário (os leitores DOCX/PDF/IFC precisam de arquivo) e apaga depois."""
        suffix = Path(key).suffix
        fd, tmp = tempfile.mkstemp(prefix="bimoffice_", suffix=suffix)
        os.close(fd)
        try:
            try:
                self.client.download_file(self.bucket, self._k(key), tmp)
            except Exception as e:
                raise StorageError(f"Arquivo original não encontrado no armazenamento: {e}") from e
            yield Path(tmp)
        finally:
            Path(tmp).unlink(missing_ok=True)

    def iter_bytes(self, key: str, chunk: int = 1024 * 1024) -> Iterator[bytes]:
        body = self.client.get_object(Bucket=self.bucket, Key=self._k(key))["Body"]
        yield from body.iter_chunks(chunk)

    def size(self, key: str) -> int:
        return self.client.head_object(Bucket=self.bucket, Key=self._k(key))["ContentLength"]

    def check(self) -> dict:
        self.client.head_bucket(Bucket=self.bucket)
        return {"kind": "s3", "bucket": self.bucket, "prefix": self.prefix}


_cache: dict = {}


def get_storage():
    if config.STORAGE == "s3":
        k = ("s3", config.S3_BUCKET, config.S3_PREFIX, config.S3_ENDPOINT_URL, config.S3_REGION)
        if k not in _cache:
            _cache.clear()
            _cache[k] = S3Storage()
        return _cache[k]
    return LocalStorage()


def file_response(key: str, filename: str, media_type: str | None, inline: bool):
    """Resposta HTTP com o arquivo original (disco: FileResponse; S3: envio em partes)."""
    from urllib.parse import quote

    from fastapi.responses import FileResponse, StreamingResponse
    st = get_storage()
    disp = "inline" if inline else "attachment"
    if isinstance(st, LocalStorage):
        return FileResponse(st.path(key), filename=filename, media_type=media_type, content_disposition_type=disp)
    return StreamingResponse(st.iter_bytes(key), media_type=media_type or "application/octet-stream",
                             headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(filename)}",
                                      "Content-Length": str(st.size(key))})
