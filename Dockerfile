# Batu City portal: the public site, the staff studio (/admin) and the assistant API in one container.
#   docker build -t batu-portal .
#   docker run -p 8000:8000 -e DATABASE_URL=postgresql://... -e SECRET_KEY=... batu-portal
# Configuration comes from the environment (see DEPLOY.md). Database migrations run at start-up.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000

WORKDIR /app
RUN useradd --create-home --uid 10001 batu

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
# var/ holds the local SQLite file when no DATABASE_URL is set; data/ holds the assistant's vector cache.
RUN mkdir -p var && chown -R batu:batu var data
USER batu

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
  CMD python -c "import os,urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)" || exit 1

# One process: rate limits and background jobs (translation runs) live in memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
