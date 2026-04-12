FROM python:3.12-slim

# System deps + Node.js (required by claude-agent-sdk CLI)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_22.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Claude CLI globally (needed by claude-agent-sdk)
RUN npm install -g @anthropic-ai/claude-code@latest

# Copy application code
COPY . .

# Create non-root user (fixes: --dangerously-skip-permissions cannot be used with root)
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app
USER appuser

# Claude CLI needs a writable home for config
ENV HOME=/home/appuser
ENV PYTHONPATH=/app

EXPOSE 8080

CMD ["sh", "-c", "alembic upgrade head 2>&1 || true; uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080} --timeout-keep-alive 30"]
