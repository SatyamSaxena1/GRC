# Multi-stage: build the SPA, then run the API that serves it.
# One image, one origin — the frontend does same-origin fetches (see
# frontend/src/api/client.ts), so no CORS config is needed in this mode.

# --- stage 1: frontend -------------------------------------------------------
FROM node:20-slim AS frontend
WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build            # -> /frontend/dist

# --- stage 2: api ----------------------------------------------------------
FROM python:3.11-slim AS api
WORKDIR /app

# System deps kept minimal; pymupdf (ocr extra) ships manylinux wheels.
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1

COPY pyproject.toml ./
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY evaluation/ ./evaluation/
COPY demo/ ./demo/
RUN pip install -e ".[ocr]"

# Built SPA — app/main.py mounts it if this directory exists.
COPY --from=frontend /frontend/dist ./frontend/dist

COPY docker/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
