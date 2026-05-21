FROM python:3.11-slim

WORKDIR /app

# Install colectica-mcp-server and agent dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy agent source
COPY agent.py .

# Optional: copy .env for local container testing
# COPY .env .

# The agent runs a single query then exits.
# For a long-running service, wrap agent.py in a web server (FastAPI, Flask)
# or call run_agent() in a loop consuming a queue.
ENTRYPOINT ["python", "agent.py"]
CMD ["How many Colectica QuestionItems are missing from my Purview catalog?"]
