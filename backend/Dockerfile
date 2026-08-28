FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY pyproject.toml ./
COPY app ./app

RUN python -m pip install .

COPY alembic.ini ./alembic.ini
COPY alembic ./alembic

USER app

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import os, urllib.request; port = os.getenv('APP_PORT', '8000'); urllib.request.urlopen(f'http://127.0.0.1:{port}/ready', timeout=2)"]

CMD ["python", "-m", "app"]
