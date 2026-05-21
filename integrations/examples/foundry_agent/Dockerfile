# syntax=docker/dockerfile:1
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent code
COPY agent.py .

# Environment variables (override at runtime)
ENV AZURE_AI_PROJECT_ENDPOINT=""
ENV COLECTICA_MCP_URL=""
ENV PURVIEW_MCP_URL=""
ENV AZURE_AI_MODEL="gpt-4o"

# Default scenario: interactive query
ENTRYPOINT ["python", "agent.py"]
CMD ["query"]
