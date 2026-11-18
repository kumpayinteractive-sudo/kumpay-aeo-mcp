# Base image pinned by digest (matches the Django app's pinning practice).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app ./app
# Run as a non-root user. The app's only runtime write is the SQLite DB
# at /app/data/mcp.db (store.py creates the parent dir on start); the
# data dir is owned by the app user so a fresh volume inherits it.
# NOTE: if /app/data is an existing volume created while the container
# ran as root, it stays root-owned and the app cannot write to it —
# recreate the volume on deploy (no buyer keys exist yet, nothing to lose).
RUN mkdir -p /app/data \
 && useradd -m app \
 && chown -R app:app /app /app/data
VOLUME /app/data
ENV DB_PATH=/app/data/mcp.db PYTHONUNBUFFERED=1
EXPOSE 8080
USER app
CMD ["uvicorn", "app.server:app", "--host", "0.0.0.0", "--port", "8080", "--proxy-headers", "--forwarded-allow-ips", "*"]
