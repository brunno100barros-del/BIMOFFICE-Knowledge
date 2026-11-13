"""Provedores de embeddings (texto -> vetor numérico que representa o significado).

A interface `EmbeddingProvider` permite trocar o modelo no futuro sem mexer no resto.
O provedor padrão roda LOCALMENTE (sentence-transformers); nenhum texto é enviado
a serviços externos. A internet só é usada uma vez, para baixar o modelo.
"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod

import numpy as np

from backend import config

log = logging.getLogger("bimoffice.embeddings")


class EmbeddingUnavailable(RuntimeError):
    """O modelo de embeddings não pôde ser carregado (não instalado / não baixado)."""


class EmbeddingProvider(ABC):
    """Contrato: vetores float32 normalizados (norma 1), para usar produto escalar = cosseno."""

    name: str

    @abstractmethod
    def embed_passages(self, texts: list[str]) -> np.ndarray: ...

    @abstractmethod
    def embed_query(self, text: str) -> np.ndarray: ...


class SentenceTransformerProvider(EmbeddingProvider):
    """Modelos da família E5 exigem os prefixos "query: " e "passage: "."""

    def __init__(self, model_name: str | None = None, device: str = "cpu"):
        self.name = model_name or config.EMBEDDING_MODEL
        self.device = device
        self._model = None
        self._lock = threading.Lock()
        self._is_e5 = "e5" in self.name.lower()

    def _load(self):
        with self._lock:
            if self._model is None:
                try:
                    from sentence_transformers import SentenceTransformer
                except ImportError as e:
                    raise EmbeddingUnavailable(
                        "Pacote sentence-transformers não instalado "
                        "(pip install -r requirements-ml.txt)."
                    ) from e
                config.MODELS_DIR.mkdir(parents=True, exist_ok=True)
                kw = dict(device=self.device, cache_folder=str(config.MODELS_DIR))
                try:  # 1º: só a cópia local (funciona offline, sem contatar a internet)
                    self._model = SentenceTransformer(self.name, local_files_only=True, **kw)
                    log.info("Modelo de embeddings %s carregado da pasta local", self.name)
                except Exception:
                    try:  # 2º: baixa uma única vez (~1 GB) para data/embeddings/modelos
                        log.info("Baixando modelo de embeddings %s (apenas na 1ª vez)", self.name)
                        self._model = SentenceTransformer(self.name, **kw)
                    except Exception as e:
                        raise EmbeddingUnavailable(
                            f"Não foi possível carregar o modelo {self.name}: {e}"
                        ) from e
        return self._model

    def _encode(self, texts: list[str]) -> np.ndarray:
        model = self._load()
        vecs = model.encode(
            texts, batch_size=config.EMBEDDING_BATCH_SIZE,
            normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
        )
        return np.asarray(vecs, dtype=np.float32)

    def embed_passages(self, texts: list[str]) -> np.ndarray:
        prefix = "passage: " if self._is_e5 else ""
        return self._encode([prefix + t for t in texts])

    def embed_query(self, text: str) -> np.ndarray:
        prefix = "query: " if self._is_e5 else ""
        return self._encode([prefix + text])[0]


_provider: EmbeddingProvider | None = None


def get_provider() -> EmbeddingProvider:
    global _provider
    if _provider is None:
        _provider = SentenceTransformerProvider()
    return _provider


def set_provider(provider: EmbeddingProvider | None) -> None:
    """Troca o provedor (usado em testes ou para outro modelo)."""
    global _provider
    _provider = provider
