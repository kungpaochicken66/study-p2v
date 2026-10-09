FROM python:3.12.13-slim-bookworm AS builder
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential pkg-config libcairo2-dev libpango1.0-dev \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.11.6 /uv /usr/local/bin/uv
WORKDIR /opt/p2v
COPY pyproject.toml uv.lock README.md LICENSE ./
COPY src ./src
RUN uv sync --locked --no-dev --no-editable --python /usr/local/bin/python

FROM python:3.12.13-slim-bookworm
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg fontconfig fonts-dejavu-core libcairo2 libpango-1.0-0 libpangocairo-1.0-0 \
    libgl1 libegl1 tini \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home renderer \
    && mkdir -p /data && chown renderer:renderer /data
COPY --from=builder /opt/p2v/.venv /opt/p2v/.venv
ENV PATH="/opt/p2v/.venv/bin:$PATH" \
    P2V_DATA_DIR=/data P2V_FONT="DejaVu Sans" PYTHONUNBUFFERED=1
WORKDIR /data
USER renderer
VOLUME ["/data"]
EXPOSE 8090
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8090/health/ready', timeout=3)"
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["study-p2v", "serve", "--host", "0.0.0.0", "--port", "8090"]
