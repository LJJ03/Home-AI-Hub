# syntax=docker/dockerfile:1

ARG PYTHON_VERSION=3.13.15

FROM python:${PYTHON_VERSION}-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

COPY pyproject.toml ./
COPY app ./app

RUN python -m pip wheel --wheel-dir /wheels .


FROM python:${PYTHON_VERSION}-slim AS runtime

ARG APP_UID=10001
ARG APP_GID=10001

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN addgroup --system --gid "${APP_GID}" app \
    && adduser --system --uid "${APP_UID}" --ingroup app \
        --home /app --no-create-home app

WORKDIR /app

COPY --from=builder /wheels /wheels
RUN python -m pip install --no-index --find-links=/wheels home-ai-hub-backend \
    && rm -rf /wheels

COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app alembic ./alembic

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; port = os.getenv('APP_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=2).close()"]

CMD ["python", "-m", "app"]
