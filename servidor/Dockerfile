# Servidor central · imagen multi-etapa (CS-003 §S)
#   servidor: lo que corre en la VM y en el portátil de respaldo
#   pruebas:  lo mismo más pytest; se usa con `docker compose run --rm pruebas`

FROM python:3.13.18-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin central \
 && mkdir /datos && chown central:central /datos
COPY central/ central/

FROM base AS pruebas
COPY requirements-pruebas.txt pyproject.toml ./
RUN pip install -r requirements-pruebas.txt
COPY pruebas/ pruebas/
USER 10001
# La especificación se monta en /especificacion (ver docker-compose.yml).
ENV RUTA_ESPECIFICACION=/especificacion
CMD ["python", "-m", "pytest"]

FROM base AS servidor
USER 10001
VOLUME ["/datos"]
EXPOSE 9000
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"PUERTO\") or 9000}/health', timeout=2)"
CMD ["python", "-m", "central"]
