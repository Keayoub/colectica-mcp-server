# syntax=docker/dockerfile:1
# Colectica MCP Server — streamable-http container image
FROM python:3.11-slim

WORKDIR /app

# Install the published package (or replace with local build below)
COPY pyproject.toml .
COPY src/ src/
RUN pip install --no-cache-dir -e .

# ── Runtime env vars (all overridable at container start) ──────────────────
# Required
ENV COLECTICA_BASE_URL=""
# Optional auth (choose one)
ENV COLECTICA_USERNAME=""
ENV COLECTICA_PASSWORD=""
ENV COLECTICA_BEARER_TOKEN=""
# Transport config
ENV COLECTICA_MCP_TRANSPORT="streamable-http"
ENV COLECTICA_MCP_HOST="0.0.0.0"
ENV COLECTICA_MCP_PORT="8000"
ENV COLECTICA_MCP_MOUNT_PATH=""
ENV COLECTICA_TIMEOUT_SECONDS="30"
ENV COLECTICA_VERIFY_SSL="true"

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/mcp')" || exit 1

ENTRYPOINT ["colectica-mcp"]
CMD ["--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
