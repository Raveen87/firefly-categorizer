# AGENTS

This file explains the repository layout, technical choices, and working conventions.

## Non-negotiable command policy

- Always use `uv` for anything Python-related. Do not run `python`, `pytest`, `ruff`, or `ty` directly.
- Examples:
  - `uv sync`
  - `uv run python src/firefly_categorizer/main.py`
  - `uv run pytest`
  - `uv run ty check`
  - `uv run ruff check`

- Before any task is considered completed, these commands must be executed and pass without violations:
  - `uv run pytest`
  - `uv run ty check`
  - `uv run ruff check`

## Project structure

- `src/firefly_categorizer/app.py` builds the FastAPI app, wires lifespan services, mounts static assets, and registers routers.
- `src/firefly_categorizer/main.py` is the Uvicorn entrypoint.
- `src/firefly_categorizer/api/` contains API dependencies/schemas; `routes/` defines categorize, transactions, training, webhook, and pages endpoints.
- `src/firefly_categorizer/services/` orchestrates categorization, training, and Firefly data access.
- `src/firefly_categorizer/classifiers/` holds the Memory matcher, TF-IDF classifier, and optional LLM classifier.
- `src/firefly_categorizer/integration/` implements the Firefly III HTTP client.
- `src/firefly_categorizer/domain/` stores domain helpers for transactions, tags, and time formatting.
- `src/firefly_categorizer/web/` holds Jinja2 templates and static assets for the UI.
- `tests/` is the pytest suite.
- `data/` is an optional data directory (defaults to repo root via `DATA_DIR`).
- `memory.json` and `tfidf.pkl` are persisted model artifacts when using the default `DATA_DIR`.
- `config/config.yaml` and `.env.example` are the runtime configuration templates. `.env` is loaded at startup if present.

## Technical choices

- Python 3.12+ with FastAPI + Uvicorn (`pyproject.toml`).
- Hybrid categorization pipeline: Memory matcher -> TF-IDF -> optional LLM (OpenAI) fallback.
- File-based persistence for learned memory and TF-IDF models.
- Firefly III integration over HTTP using `httpx`.
- Jinja2 templates for server-rendered UI pages.
- Tooling: `uv` for dependency/runtime management, `ruff` for linting, `ty` for type checking, `pytest` for tests.
- Container support via `Dockerfile` and `docker-compose.yml`.

## Environment configuration

- `config.yaml` is loaded by `src/firefly_categorizer/core/settings.py` (via `CONFIG_DIR` when set). `.env` is loaded first and treated as explicit environment variables.
- Common variables: `FIREFLY_URL`, `FIREFLY_TOKEN`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`,
  `AUTO_APPROVE_THRESHOLD`, `TRAINING_PAGE_SIZE`, `MANUAL_TAGS`, `AUTO_APPROVE_TAGS`, `DATA_DIR`, `LOG_DIR`.
