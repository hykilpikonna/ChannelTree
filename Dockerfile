FROM python:3.13-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Enable bytecode compilation
ENV UV_COMPILE_BYTECODE=1

# Install system dependencies required for psycopg2
RUN apt-get update && apt-get install -y libpq-dev gcc && rm -rf /var/lib/apt/lists/*

# Copy project requirements
COPY pyproject.toml uv.lock ./

# Install dependencies (but not the project yet)
RUN uv sync --frozen --no-install-project

# Copy the application code
COPY . .

# Install the project
RUN uv sync --frozen

# Start using uv run
CMD ["uv", "run", "python", "src/bot.py"]
