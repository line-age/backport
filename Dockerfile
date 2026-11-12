# Imports run as jobs: one container per run, data mounted read-only at /data.
#   docker run --rm -v /path/to/data:/data:ro -e LINEAGE_STORE_URL -e LINEAGE_TOKEN \
#       lineage-backport backport-natural-gas /data/natural_gas.gpkg "/data/Natural Gas Traces" \
#       /data/natural_gas_tracers.yaml --stitch-version <sha>
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH"
CMD ["backport-natural-gas", "--help"]
