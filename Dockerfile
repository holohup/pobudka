FROM python:3.13-slim-bookworm

# Install Node.js 22 (required by both CLIs)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl git ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Install Claude Code CLI (pinned to v2.1.38)
RUN npm install -g @anthropic-ai/claude-code@2.1.38

# Install OpenAI Codex CLI (pinned to v0.87.0)
RUN npm install -g @openai/codex@0.87.0

# Verify CLIs are installed
RUN claude --version && codex --version

# Create app directory
WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY src/ ./src/

# Create directories for CLI auth persistence (will be volume-mounted)
RUN mkdir -p /root/.claude /root/.codex

CMD ["python", "-m", "src.main"]
