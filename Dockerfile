# syntax=docker/dockerfile:1

# --- build stage: install dependencies into an isolated virtualenv ----------
FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install -r requirements.txt


# --- runtime stage: only the virtualenv and application code ----------------
FROM python:3.12-slim AS runtime

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/app.db \
    # One process keeps the in-memory active-users list consistent;
    # threads serve concurrent requests and are guarded by threading.Lock.
    GUNICORN_CMD_ARGS="--workers 1 --threads 8 --timeout 30 --access-logfile -"

RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --create-home --home-dir /home/app app

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY --chown=app:app app/ ./app/
COPY --chown=app:app run.py .

# Created before VOLUME so a fresh named volume inherits the ownership.
RUN mkdir -p /app/data && chown app:app /app/data
VOLUME ["/app/data"]

USER app

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=3).status == 200 else 1)"]

CMD ["gunicorn", "-b", "0.0.0.0:8080", "run:app"]
