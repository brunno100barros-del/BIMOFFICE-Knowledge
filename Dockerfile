# BIMOFFICE Knowledge — imagem única para a API e para o worker.
#   docker build -t bimoffice .                     (com pesquisa semântica: PyTorch CPU + sentence-transformers)
#   docker build --build-arg WITH_ML=0 -t bimoffice .   (sem pesquisa semântica: imagem bem menor)
FROM python:3.13-slim

ARG WITH_ML=1
# Baixa o modelo de IA (E5, ~1 GB) DENTRO da imagem: início rápido e sem depender da internet depois
ARG PRELOAD_MODEL=1
# Cliente PostgreSQL (pg_dump/pg_restore para backup a partir do container). 0 = não instalar.
ARG WITH_PG_CLIENT=1
# Redes que só permitem HTTPS (proxy corporativo): --build-arg APT_HTTPS=1 (usa o certificado de docker/certs/)
ARG APT_HTTPS=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    BIMOFFICE_DATA_DIR=/data \
    SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt \
    PIP_CERT=/etc/ssl/certs/ca-certificates.crt

# Certificados extras de rede corporativa (opcional): coloque arquivos .crt em docker/certs/ (fora do Git)
COPY docker/certs/ /usr/local/share/ca-certificates/extra/
RUN update-ca-certificates \
    && if [ "$WITH_PG_CLIENT" = "1" ]; then \
         if [ "$APT_HTTPS" = "1" ]; then sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources; fi; \
         apt-get update && apt-get install -y --no-install-recommends postgresql-client && rm -rf /var/lib/apt/lists/*; \
       fi

WORKDIR /app
COPY requirements.txt requirements-ml.txt ./
RUN pip install -r requirements.txt \
    && if [ "$WITH_ML" = "1" ]; then \
         pip install torch --index-url https://download.pytorch.org/whl/cpu && pip install -r requirements-ml.txt; \
       fi

ENV BIMOFFICE_MODELS_DIR=/opt/bimoffice-modelos
RUN if [ "$WITH_ML" = "1" ] && [ "$PRELOAD_MODEL" = "1" ]; then \
      HF_HUB_DISABLE_XET=1 python -c "from huggingface_hub import snapshot_download; snapshot_download('intfloat/multilingual-e5-base', cache_dir='/opt/bimoffice-modelos', allow_patterns=['*.json','*.txt','*.model','model.safetensors','1_Pooling/*'])"; \
    fi
COPY backend ./backend
COPY frontend ./frontend
COPY scripts ./scripts

RUN useradd --create-home --uid 1000 app && mkdir -p /data && chown app /data
USER app
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health/ready', timeout=4).status == 200 else 1)"
# API (o worker usa a mesma imagem com: python -m backend.worker)
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
