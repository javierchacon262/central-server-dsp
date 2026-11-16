# Script de conformidad, parte automática (CS-004).
#
#   docker build -t conformidad-dsp "https://github.com/javierchacon262/central-server-dsp.git#main:conformidad"
#   docker run --rm --network host conformidad-dsp http://localhost:8000 > conformidad.txt
#
# Etapas: base -> pruebas | script. La última, script, es la que se construye por defecto.

FROM python:3.13-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin conformidad
COPY conformidad/ conformidad/

FROM base AS pruebas
COPY requirements-pruebas.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements-pruebas.txt
COPY pruebas/ pruebas/
USER 10001
CMD ["python", "-m", "pytest", "-p", "no:cacheprovider"]

FROM base AS script
USER 10001
ENTRYPOINT ["python", "-m", "conformidad"]
