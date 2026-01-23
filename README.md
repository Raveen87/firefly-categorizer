# Firefly Categorizer

A hybrid transaction categorization service for Firefly III.

## Features

* **Three-way Classification**: Uses Memory (exact/fuzzy), TF-IDF (ML), and LLM (OpenAI) to categorize transactions.
* **Continuous Learning**: Memorizes manual corrections and retrains the ML model on the fly.
* **Web UI**: View recent transactions, see predictions, and manually confirm/correct categories.
* **Webhook Support**: Ready to receive `TRIGGERED` events from Firefly III.

## Configuration

You can configure settings via environment variables or the UI-backed `config/config.yaml` file.
Environment variables take precedence and lock the corresponding field in the UI.

### Option A: Environment variables

1. Copy `.env.example` to `.env`. The application automatically loads `.env` on startup:

    ```bash
    cp .env.example .env
    ```

2. Set the following variables:
    * `FIREFLY_URL`: The full URL to your Firefly III instance (e.g., `http://192.168.1.100:8080`).
    * `FIREFLY_TOKEN`: Your Personal Access Token. Generate this in Firefly III under **Profile > OAuth / Personal Access Tokens > Create New Token**.
    * `OPENAI_API_KEY`: (Optional) Your OpenAI API key if you want LLM fallback.
    * `AUTO_APPROVE_THRESHOLD`: (Optional) Confidence threshold for auto-approval (0-1, 0 disables).
    * `MANUAL_TAGS`: (Optional) Comma-separated tags to apply when you click Save.
    * `AUTO_APPROVE_TAGS`: (Optional) Comma-separated tags to apply when auto-approval kicks in.

### Option B: config.yaml

1. Open `config/config.yaml` and uncomment the settings you want to use.
2. Values in `config.yaml` only apply when the same environment variable (or `.env` entry) is not set.

## Running

To assure the same verison of `uv` is used locally as in production, `mise` is recommended.

Initialize the project by running:

```bash
mise install
```

Without `mise`, `uv` must be installed manually before proceeding.

1. Install dependencies:

    ```bash
    uv sync
    ```

2. Run the server:

    ```bash
    uv run python src/firefly_categorizer/main.py
    ```

3. Open `http://localhost:8000` in your browser.

## Docker

1. Build and run with Docker Compose:

    ```bash
    docker-compose up --build -d
    ```

2. Open `http://localhost:8000`.

The `/app/data` volume persists learned categories/models. `/app/logs` stores log files and
`/app/config` is where the container-local `config.yaml` lives.

## Integration

* **Webhooks**: Configure Firefly III to send webhooks to `http://<your-ip>:8000/webhook/firefly` (JSON format).

## Development

This project uses **pytest** for tests, **ty** for type checking and **Ruff** for linting.

### Testing

To run the test suite:

```bash
uv run pytest
```

### Type Checking

To run type checking:

```bash
uv run ty check
```

### Linting

To check for linting issues:

```bash
uv run ruff check
```

To automatically fix issues:

```bash
uv run ruff check --fix
```

## Release

Releases are created via the GitHub Actions **Release** workflow. It bumps the version, generates
the changelog, builds and pushes the Docker image, tags the release, and creates a **draft** GitHub
Release for manual editing.

Note: if a draft release is deleted manually, the Git tag remains in the repository. If you need
to undo a release after deleting the draft, delete the tag separately in Git.
