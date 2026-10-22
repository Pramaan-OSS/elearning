# The pinned runtime for one installation: the framework at a fixed commit,
# the dependency set at a fixed lock, this app from the working tree, and
# nothing fetched from upstream at start.
FROM ghcr.io/astral-sh/uv:0.11.26 AS installer
FROM node:24-bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates mariadb-client build-essential pkg-config \
      libmariadb-dev libffi-dev libcairo2 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=installer /uv /uvx /usr/local/bin/
WORKDIR /app
COPY . .
RUN ./scripts/prepare-local
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin" FRAPPE_PRELOAD_DATABASE_DRIVERS=none
CMD ["./docker/serve"]
