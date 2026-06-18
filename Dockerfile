# syntax=docker/dockerfile:1
ARG PYTHON_VERSION=3.12

############################
# Imagen de runtime (FastAPI + uvicorn)
############################
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Dependencias primero (mejor cache de capas)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Código de la app
COPY app ./app

# Usuario no-root
RUN useradd --create-home --uid 1001 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# 1 worker a propósito: el scheduler interno (APScheduler) debe ejecutarse UNA
# sola vez. Con varios workers correría el barrido N veces.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
