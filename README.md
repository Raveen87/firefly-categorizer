# Firefly Categorizer

Firefly Categorizer is a FastAPI service that learns how you categorize transactions in Firefly III and applies that knowledge to future transactions.

It combines three approaches in a single pipeline:

- `Memory matcher` for exact and fuzzy matches on previously seen descriptions
- `TF-IDF classifier` for learned text-based predictions from your training history
- `OpenAI fallback` for optional last-resort categorization when local models cannot decide

## What It Does

- Trains on your existing categorized transactions in Firefly III
- Suggests categories for uncategorized transactions in the web UI
- Learns immediately from manual corrections and confirmations
- Auto-approves high-confidence predictions when enabled
- Accepts Firefly III webhooks to categorize new transactions as they are created
- Persists learned state to disk so the service improves over time

## How It Works

The categorization order is fixed:

1. `Memory matcher` checks for an exact or fuzzy match against transactions you have already confirmed.
2. `TF-IDF classifier` predicts a category from previously learned training examples.
3. `OpenAI fallback` is used only if `OPENAI_API_KEY` is configured and the local models do not produce a result.

Accepted results are written back into the local memory and TF-IDF models, so every confirmed categorization improves future suggestions.

## Quick Start

### Recommended: Docker Compose

The repository includes a production-oriented [`docker-compose.yml`](docker-compose.yml).

1. Create or update a `.env` file with your environment values:

   ```env
   FIREFLY_URL=http://your-firefly-instance:8080
   FIREFLY_TOKEN=ey...
   OPENAI_API_KEY=sk-...
   ```

2. Start the service:

   ```bash
   docker compose up -d
   ```

3. Open `http://localhost:8000`.

Mounted directories:

- `./config` for `config.yaml`
- `./data` for `memory.json` and `tfidf.pkl`
- `./logs` for `app.log`

### Local Development

This project uses `uv` for dependency management and execution.

1. Install the pinned tooling version if you use `mise`:

   ```bash
   mise install
   ```

2. Install dependencies:

   ```bash
   uv sync
   ```

3. Create `.env` from [`.env.example`](.env.example) or configure environment variables directly.

4. Start the app:

   ```bash
   uv run python -m firefly_categorizer.main
   ```

5. Open `http://localhost:8000`.

For a containerized local-code workflow that mounts your local `src/` tree into the container, use [`docker-compose_dev.yml`](docker-compose_dev.yml):

```bash
docker compose -f docker-compose_dev.yml up --build -d
```

## Configuration

Configuration is loaded in this order:

1. Environment variables
2. `.env`
3. `config.yaml`

Environment variables always win. If a value is supplied through the environment or `.env`, the corresponding field is shown as locked in the UI to avoid conflicting edits.

When `CONFIG_DIR` is set, the app loads:

- `CONFIG_DIR/.env`
- `CONFIG_DIR/config.yaml`

Otherwise it looks for:

- `.env` in the project root
- `config/config.yaml`, falling back to `./config.yaml` if needed

### Required for Firefly III integration

These are the minimum settings for useful operation:

- `FIREFLY_URL`
- `FIREFLY_TOKEN`

Without them, the UI can still load, but Firefly III fetch/train/categorize actions are effectively disabled.

### Optional OpenAI fallback

OpenAI is optional.

If `OPENAI_API_KEY` is not set, the service still works with the local memory and TF-IDF classifiers. The OpenAI classifier is only used as a fallback when local models do not produce a result.

### Configuration Reference

| Environment variable | `config.yaml` key | Description |
| --- | --- | --- |
| `FIREFLY_URL` | `firefly.url` | Base URL for your Firefly III instance, without a trailing slash. |
| `FIREFLY_TOKEN` | `firefly.token` | Personal Access Token from Firefly III. |
| `FIREFLY_HTTP_TIMEOUT` | `firefly.httpTimeout` | Timeout for Firefly III API requests in seconds. |
| `FIREFLY_CATEGORIES_TTL` | `firefly.categoriesTtl` | Category cache lifetime in seconds. `0` disables caching. |
| `OPENAI_API_KEY` | `openai.apiKey` | API key for optional OpenAI fallback. |
| `OPENAI_MODEL` | `openai.model` | Model name for the OpenAI-compatible client. |
| `OPENAI_BASE_URL` | `openai.baseUrl` | Base URL override for OpenAI-compatible providers. |
| `TRAINING_PAGE_SIZE` | `automation.trainingPageSize` | Number of Firefly III transactions fetched per training page. |
| `AUTO_APPROVE_THRESHOLD` | `automation.autoApproveThreshold` | Confidence threshold from `0` to `1`. `0` disables auto-approve. |
| `MANUAL_TAGS` | `automation.manualTags` | Comma-separated tags added on manual save. |
| `AUTO_APPROVE_TAGS` | `automation.autoApproveTags` | Comma-separated tags added on auto-approve. |
| `DATA_DIR` | `storage.dataDir` | Directory for persisted model artifacts such as `memory.json` and `tfidf.pkl`. |
| `LOG_DIR` | `storage.logDir` | Directory for application logs. |
| `LOG_LEVEL` | `logging.level` | Logging level: `DEBUG`, `INFO`, `WARNING`, `ERROR`, or `CRITICAL`. |
| `CONFIG_DIR` | - | Directory containing `.env` and `config.yaml`. |

### Example `config.yaml`

The repository includes a starter file at [`config/config.yaml`](config/config.yaml).

```yaml
firefly:
  url: http://192.168.1.100:8080
  token: ey...
  categoriesTtl: 60

openai:
  apiKey:
  model: gpt-3.5-turbo
  baseUrl:

automation:
  autoApproveThreshold: 0.9
  trainingPageSize: 50
  manualTags: firefly-categorizer
  autoApproveTags: firefly-categorizer,auto-approved

storage:
  dataDir: ./data
  logDir: ./logs

logging:
  level: INFO
```

## Typical Workflow

### 1. Train the models

Start by training on your existing categorized transactions in Firefly III. This gives the memory and TF-IDF models useful historical examples.

Notes:

- Only transactions with a category in Firefly III are used for training.
- Training can be paused and resumed.
- Previously seen transaction IDs are skipped when resuming within the same retained training state.
- Retraining is recommended after you categorize a meaningful number of transactions outside this app.

### 2. Fetch transactions to review

Use the main page to fetch a date range, or work through available transactions in order.

By default, already categorized transactions may still be fetched from Firefly III, but they are hidden in the UI unless you enable `Show categorized`.

### 3. Run categorization

The service evaluates visible transactions and streams results back to the frontend as they are processed.

For each suggested category, the UI shows:

- the suggested category
- the classifier that produced it
- the confidence score

The OpenAI fallback currently reports a fixed confidence of `0.9`.

### 4. Confirm or correct

When you press `Save`, the accepted category is written back into the local memory and TF-IDF models immediately.

If `AUTO_APPROVE_THRESHOLD` is greater than `0`, predictions at or above that threshold are approved automatically for both manual runs and webhook-triggered categorization.

## Firefly III Webhook Setup

To categorize transactions automatically as they are created, configure Firefly III to send webhooks to:

```text
http://<your-server>:8000/webhook/firefly
```

In Firefly III, create a webhook with:

| Setting | Value |
| --- | --- |
| Trigger | `After transaction created` |
| Response | `Transaction details` |
| Delivery | `JSON` |

If the app is running in Docker or on another machine, replace `localhost` with a host or IP that Firefly III can reach.

## Development

All Python-related commands should be run with `uv`.

Required checks:

```bash
uv run pytest
uv run ty check
uv run ruff check
```

Useful commands:

```bash
uv sync
uv run python -m firefly_categorizer.main
uv run pytest
uv run ty check
uv run ruff check
```

## Project Layout

- [`src/firefly_categorizer/app.py`](src/firefly_categorizer/app.py) builds the FastAPI app and wires services and routes.
- `src/firefly_categorizer/api/routes/` contains UI pages, transaction APIs, training endpoints, and the Firefly webhook route.
- `src/firefly_categorizer/services/` orchestrates categorization, training, and Firefly III data access.
- `src/firefly_categorizer/classifiers/` contains the memory, TF-IDF, and optional OpenAI classifiers.
- `src/firefly_categorizer/integration/` contains the Firefly III HTTP client.
- `src/firefly_categorizer/web/` contains Jinja2 templates and static assets.
- [`tests/`](tests/) contains the pytest suite.

## Release

Releases are produced through the GitHub Actions `Release` workflow. It updates the version, generates the changelog, builds and publishes the Docker image, creates the Git tag, and opens a draft GitHub release for final editing.
