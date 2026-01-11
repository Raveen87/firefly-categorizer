# Firefly Categorizer

A hybrid transaction categorization service for Firefly III.

## Features
*   **Three-way Classification**: Uses Memory (exact/fuzzy), TF-IDF (ML), and LLM (OpenAI) to categorize transactions.
*   **Continuous Learning**: Memorizes manual corrections and retrains the ML model on the fly.
*   **Web UI**: View recent transactions, see predictions, and manually confirm/correct categories.
*   **Webhook Support**: Ready to receive `TRIGGERED` events from Firefly III.

## Configuration

1.  Copy `.env.example` to `.env`:
    ```bash
    cp .env.example .env
    ```
2.  Edit `.env` and set your credentials:
    *   `FIREFLY_URL`: The full URL to your Firefly III instance (e.g., `http://192.168.1.100:8080`).
    *   `FIREFLY_TOKEN`: Your Personal Access Token. Generate this in Firefly III under **Profile > OAuth / Personal Access Tokens > Create New Token**.
    *   `OPENAI_API_KEY`: (Optional) Your OpenAI API key if you want LLM fallback.
    *   `AUTO_APPROVE_THRESHOLD`: (Optional) Confidence threshold for auto-approval (0-1, 0 disables).
    *   `MANUAL_TAGS`: (Optional) Comma-separated tags to apply when you click Save.
    *   `AUTO_APPROVE_TAGS`: (Optional) Comma-separated tags to apply when auto-approval kicks in.

## Running

1.  Install dependencies:
    ```bash
    uv sync
    ```
2.  Run the server:
    ```bash
    uv run python src/firefly_categorizer/main.py
    ```
3.  Open `http://localhost:8000` in your browser.

## Docker

1.  Build and run with Docker Compose:
    ```bash
    docker-compose up --build -d
    ```
2.  Open `http://localhost:8000`.

The `/app/data` volume is used to persist learned categories/models.

## Integration
*   **Webhooks**: Configure Firefly III to send webhooks to `http://<your-ip>:8000/webhook/firefly` (JSON format).

## Development

This project uses **Ruff** for linting and **ty** for type checking.

### Linting
To check for linting issues:
```bash
uv run ruff check .
```
To automatically fix issues:
```bash
uv run ruff check . --fix
```

### Type Checking
To run type checking:
```bash
uv run ty check
```

### Testing
To run the test suite:
```bash
uv run pytest
```
