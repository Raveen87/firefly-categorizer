# Use an official lightweight Python image.
# We use the uv image as a builder to leverage its speed and caching.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

WORKDIR /app

# Install dependencies
# We use mount caches to speed up subsequent builds
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Copy the rest of the application
ADD . /app

# Sync the project execution environment
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Final stage: minimal runtime image
FROM python:3.12-slim-bookworm

# Create a non-root user
RUN useradd -m -u 1000 appuser

WORKDIR /app

# Copy the environment and application from builder
COPY --from=builder --chown=appuser:appuser /app /app

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/src"
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV DATA_DIR="/app/data"
ENV LOG_DIR="/app/logs"
ENV CONFIG_DIR="/app/config"

# Create volume mount points for persistence and ensure ownership
RUN mkdir -p /app/data /app/logs /app/config \
    && chown appuser:appuser /app/data /app/logs /app/config

# Switch to non-root user
USER appuser

# Expose the application port
EXPOSE 8000

# Command to run the application
# Using -m to run as a module so imports work correctly
CMD ["python", "-m", "firefly_categorizer.main"]
