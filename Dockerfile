FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install .

# The data pack (SCHEMA.TABLE.parquet files + manifest.json) is baked into the image.
# The pipeline downloads it from S3 into ./data/ and verifies it before docker build.
# For a local build, copy the pack into ./data/ first (e.g. from data_pack_02/).
# Files stay owned by root, so the app user can read them but not change them.
COPY data/ /data/

RUN useradd --create-home app
USER app

ENV INFOPAVE_DATA_DIR=/data \
    INFOPAVE_BACKEND=duckdb \
    INFOPAVE_TRANSPORT=http \
    INFOPAVE_HOST=0.0.0.0 \
    INFOPAVE_PORT=8000
EXPOSE 8000

# Needs the /health route in server.py (HTTP mode only)
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3)"

CMD ["infopave-mcp"]
