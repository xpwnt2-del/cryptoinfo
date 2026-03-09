# ── CryptoInfo – Docker image for Cloudflare Container hosting ───────────────
# Cloudflare Containers require:
#   • Port 8080 (internal)
#   • linux/amd64 architecture
#   • A non-root user for security
#
# Build:   docker build -t cryptoinfo .
# Run:     docker run -p 8080:8080 --env-file .env cryptoinfo
# ─────────────────────────────────────────────────────────────────────────────

# ── Build stage: compile any C-extension wheels ───────────────────────────────
FROM python:3.11-slim AS builder

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# Create a dedicated non-root user (Cloudflare Container security best practice)
RUN addgroup --system appgroup && \
    adduser --system --ingroup appgroup --no-create-home appuser

WORKDIR /app

# Copy pre-built packages from the builder stage (keeps the final image lean)
COPY --from=builder /install /usr/local

# Copy application source
COPY . .

# Give the non-root user write access for the SQLite database and any
# runtime artefacts.  Cloudflare Containers mount an ephemeral writable
# layer at /app, so this is sufficient for development & demo use.
RUN chown -R appuser:appgroup /app

USER appuser

# Cloudflare Containers expect traffic on port 8080
EXPOSE 8080

# Container health check – hits the /health endpoint added in app.py.
# urlopen raises an exception (exit code ≠ 0) on failure; succeeds silently
# (exit code 0) when the app is ready.
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c \
        "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"

# Gunicorn: 2 workers with preload (app loaded once before fork to avoid
# SQLite lock contention); long timeout for slow crypto-API calls
CMD ["python", "-m", "gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--preload", \
     "--timeout", "120", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "app:app"]
