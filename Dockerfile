# syntax=docker/dockerfile:1
ARG UV_VERSION=0.13.4
ARG LITESTREAM_VERSION=0.5.17
ARG DEBIAN_TAG=trixie-20260918-slim

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv_layer
FROM docker.io/litestream/litestream:${LITESTREAM_VERSION}-scratch AS litestream_layer

# PENDING: a node stage building web/ into /web/dist, copied below into LINGUINI_STATIC_DIR.

FROM docker.io/library/debian:${DEBIAN_TAG} AS builder
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/tmp/python \
    UV_PYTHON_INSTALL_BIN=0 \
    UV_PYTHON_CACHE_DIR=/root/.cache/uv/python
RUN --mount=type=bind,source=.,target=/app \
    --mount=from=uv_layer,source=/uv,target=/usr/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    bash /app/docker/build.sh

FROM gcr.io/distroless/cc-debian13:nonroot
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LINGUINI_DATA_DIR=/data \
    LINGUINI_STATIC_DIR=/usr/local/share/linguini/web \
    LITESTREAM_CONFIG=/etc/litestream.yml
COPY --from=builder /usr/local /usr/local
COPY --from=builder --chown=65532:65532 /data /data
COPY --from=litestream_layer /usr/local/bin/litestream /usr/local/bin/litestream
COPY litestream.yml /etc/litestream.yml
# COPY --from=web /web/dist /usr/local/share/linguini/web   (PENDING)
USER 65532:65532
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["/usr/local/bin/python3", "-c", "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/health',timeout=3)"]
ENTRYPOINT ["/usr/local/bin/fastapi", "run", "--entrypoint", "linguini.main:app"]
CMD ["--host", "0.0.0.0", "--port", "8000"]
