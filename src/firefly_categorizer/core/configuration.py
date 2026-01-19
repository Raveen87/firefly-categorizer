import os
from dataclasses import dataclass
from typing import Any, Literal

from firefly_categorizer.core import settings
from firefly_categorizer.logger import get_logger

ValueType = Literal["string", "int", "float"]

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConfigField:
    key: str
    label: str
    description: str
    placeholder: str
    input_type: str
    category: str
    value_type: ValueType = "string"
    sensitive: bool = False
    options: tuple[str, ...] | None = None
    min_value: float | int | None = None
    max_value: float | int | None = None
    step: float | int | None = None
    restart_required: bool = False


CONFIG_FIELDS: tuple[ConfigField, ...] = (
    ConfigField(
        key="FIREFLY_URL",
        label="Firefly URL",
        description="Base URL for your Firefly III instance (no trailing slash).",
        placeholder="http://localhost:8080",
        input_type="url",
        category="Firefly III",
    ),
    ConfigField(
        key="FIREFLY_TOKEN",
        label="Firefly Token",
        description="Personal Access Token from Firefly III (Profile -> OAuth).",
        placeholder="ey...",
        input_type="password",
        category="Firefly III",
        sensitive=True,
    ),
    ConfigField(
        key="FIREFLY_CATEGORIES_TTL",
        label="Categories Cache TTL",
        description="Seconds to cache category list from Firefly III. 0 disables caching.",
        placeholder="60",
        input_type="number",
        category="Firefly III",
        value_type="float",
        min_value=0,
        step=0.01,
    ),
    ConfigField(
        key="OPENAI_API_KEY",
        label="OpenAI API Key",
        description="API key used for optional LLM fallback.",
        placeholder="sk-...",
        input_type="password",
        category="OpenAI",
        sensitive=True,
    ),
    ConfigField(
        key="OPENAI_MODEL",
        label="OpenAI Model",
        description="Model name for the OpenAI-compatible client.",
        placeholder="gpt-3.5-turbo",
        input_type="text",
        category="OpenAI",
    ),
    ConfigField(
        key="OPENAI_BASE_URL",
        label="OpenAI Base URL",
        description="Override OpenAI base URL for compatible providers.",
        placeholder="http://localhost:11434/v1",
        input_type="url",
        category="OpenAI",
    ),
    ConfigField(
        key="AUTO_APPROVE_THRESHOLD",
        label="Auto-approve Threshold",
        description="Confidence threshold (0-1). 0 disables auto-approve.",
        placeholder="1",
        input_type="number",
        category="Automation",
        value_type="float",
        min_value=0.0,
        max_value=1.0,
        step=0.01,
    ),
    ConfigField(
        key="TRAINING_PAGE_SIZE",
        label="Training Page Size",
        description="Number of transactions fetched per training page.",
        placeholder="50",
        input_type="number",
        category="Automation",
        value_type="int",
        min_value=1,
        step=1,
    ),
    ConfigField(
        key="MANUAL_TAGS",
        label="Manual Tags",
        description="Comma-separated tags applied on manual save.",
        placeholder="firefly-categorizer",
        input_type="text",
        category="Automation",
    ),
    ConfigField(
        key="AUTO_APPROVE_TAGS",
        label="Auto-approve Tags",
        description="Comma-separated tags applied on auto-approve.",
        placeholder="firefly-categorizer,auto-approved",
        input_type="text",
        category="Automation",
    ),
    ConfigField(
        key="DATA_DIR",
        label="Data Directory",
        description="Directory for memory and model artifacts.",
        placeholder="/app/data",
        input_type="text",
        category="Storage",
        restart_required=True,
    ),
    ConfigField(
        key="LOG_DIR",
        label="Log Directory",
        description="Directory for application logs (app.log).",
        placeholder="/app/logs",
        input_type="text",
        category="Storage",
        restart_required=True,
    ),
    ConfigField(
        key="LOG_LEVEL",
        label="Log Level",
        description="Logging verbosity for the application.",
        placeholder="INFO",
        input_type="select",
        category="Storage",
        options=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        restart_required=True,
    ),
)

CONFIG_TEMPLATE = """# Firefly Categorizer configuration
# These settings only take effect when the same environment variable is not set.
# Remove the leading "#" to enable a setting here.

# Firefly III URL (no trailing slash)
# FIREFLY_URL:

# Firefly III Personal Access Token (Profile -> OAuth -> Personal Access Tokens)
# FIREFLY_TOKEN:

# Cache TTL for category list (seconds, 0 disables caching)
# FIREFLY_CATEGORIES_TTL:

# OpenAI API Key (Optional, for LLM fallback)
# OPENAI_API_KEY:

# OpenAI Model (Optional, defaults to gpt-3.5-turbo)
# OPENAI_MODEL:

# OpenAI Base URL (Optional, for OpenAI-compatible APIs)
# OPENAI_BASE_URL:

# Auto-approve threshold (0-1, 0 disables)
# AUTO_APPROVE_THRESHOLD:

# Training page size (minimum 1)
# TRAINING_PAGE_SIZE:

# Tags to apply when saving manually (comma-separated)
# MANUAL_TAGS:

# Tags to apply when auto-approving (comma-separated)
# AUTO_APPROVE_TAGS:

# Data directory (memory.json, tfidf.pkl)
# DATA_DIR:

# Log directory (app.log)
# LOG_DIR:

# Log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
# LOG_LEVEL:
"""


def get_config_keys() -> tuple[str, ...]:
    return tuple(field.key for field in CONFIG_FIELDS)


def get_config_path() -> str | None:
    config_path = settings.get_config_path()
    if config_path:
        return config_path
    return os.path.join(os.getcwd(), "config", settings.CONFIG_FILENAME)


def _load_config_values(config_path: str | None) -> dict[str, str]:
    return settings.read_config_file(config_path)


def _group_fields() -> list[tuple[str, list[ConfigField]]]:
    categories: list[str] = []
    grouped: dict[str, list[ConfigField]] = {}
    for field in CONFIG_FIELDS:
        if field.category not in grouped:
            grouped[field.category] = []
            categories.append(field.category)
        grouped[field.category].append(field)
    return [(category, grouped[category]) for category in categories]


def build_config_context(
    *,
    field_errors: dict[str, str] | None = None,
) -> dict[str, object]:
    config_path = get_config_path()
    config_values = _load_config_values(config_path)
    sections: list[dict[str, object]] = []
    env_override_count = 0

    for category, fields in _group_fields():
        section_fields: list[dict[str, object]] = []
        for field in fields:
            env_override = settings.is_env_override(field.key)
            if env_override:
                env_override_count += 1
            raw_value = config_values.get(field.key, "")
            display_value = raw_value
            if env_override:
                env_value = os.getenv(field.key, "")
                if field.options:
                    display_value = env_value.upper()
                else:
                    display_value = "" if field.sensitive else env_value

            placeholder = (
                "Set via environment variable"
                if env_override
                else field.placeholder
            )
            section_fields.append(
                {
                    "key": field.key,
                    "label": field.label,
                    "description": field.description,
                    "placeholder": placeholder,
                    "input_type": field.input_type,
                    "value": display_value,
                    "options": field.options,
                    "disabled": env_override,
                    "env_override": env_override,
                    "sensitive": field.sensitive,
                    "restart_required": field.restart_required,
                    "step": field.step,
                    "error": (field_errors or {}).get(field.key),
                }
            )
        sections.append({"name": category, "fields": section_fields})

    return {
        "config_path": config_path or "Not configured",
        "sections": sections,
        "env_override_count": env_override_count,
    }


def _validate_value(field: ConfigField, raw_value: str) -> tuple[str, str | None]:
    value = raw_value.strip()
    if not value:
        return "", None

    if "\n" in value or "\r" in value:
        return value, "Value must be a single line."

    if field.options:
        normalized = value.upper()
        if normalized not in field.options:
            return value, f"Must be one of: {', '.join(field.options)}."
        return normalized, None

    if field.value_type == "int":
        try:
            parsed = int(value)
        except ValueError:
            return value, "Must be a whole number."
        if field.min_value is not None and parsed < field.min_value:
            return value, f"Must be at least {field.min_value}."
        if field.max_value is not None and parsed > field.max_value:
            return value, f"Must be at most {field.max_value}."
        return str(parsed), None

    if field.value_type == "float":
        try:
            parsed = float(value)
        except ValueError:
            return value, "Must be a number."
        if field.min_value is not None and parsed < field.min_value:
            return value, f"Must be at least {field.min_value}."
        if field.max_value is not None and parsed > field.max_value:
            return value, f"Must be at most {field.max_value}."
        return str(parsed), None

    return value, None


def apply_config_updates(form_values: dict[str, str]) -> tuple[dict[str, str], dict[str, str]]:
    errors: dict[str, str] = {}
    updates: dict[str, str] = {}

    for field in CONFIG_FIELDS:
        if settings.is_env_override(field.key):
            continue

        raw_value = form_values.get(field.key)
        if raw_value is None:
            continue

        cleaned, error = _validate_value(field, raw_value)
        if error:
            errors[field.key] = error
            continue
        updates[field.key] = cleaned

    if errors:
        return errors, {}

    _write_config_file(updates)
    _apply_runtime_overrides(updates)
    return {}, updates


def _write_config_file(updates: dict[str, str]) -> None:
    config_path = get_config_path()
    if not config_path:
        raise RuntimeError("No configuration path available.")

    config_dir = os.path.dirname(config_path)
    if config_dir:
        os.makedirs(config_dir, exist_ok=True)
    lines: list[str]
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as handle:
            lines = handle.read().splitlines()
    else:
        lines = [str(line) for line in CONFIG_TEMPLATE.splitlines()]

    key_indexes: dict[str, int] = {}
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or ":" not in stripped:
            continue
        candidate = stripped
        if candidate.startswith("#"):
            candidate = candidate[1:].lstrip()
        key = candidate.split(":", 1)[0].strip()
        if key in updates and key not in key_indexes:
            key_indexes[key] = index

    for key, value in updates.items():
        formatted = _format_yaml_value(value)
        new_line = f"{key}: {formatted}" if value else f"# {key}:"
        if key in key_indexes:
            lines[key_indexes[key]] = new_line
        else:
            lines.append(new_line)

    with open(config_path, "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines).rstrip("\n") + "\n")


def _apply_runtime_overrides(updates: dict[str, str]) -> None:
    for key, value in updates.items():
        if settings.is_env_override(key):
            continue
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def apply_runtime_updates(app: Any, updates: dict[str, str]) -> None:
    if not updates:
        return
    state = getattr(app, "state", None)
    if state is None:
        return

    if {"FIREFLY_URL", "FIREFLY_TOKEN"} & updates.keys():
        _refresh_firefly(getattr(state, "firefly", None))

    if {"OPENAI_API_KEY", "OPENAI_MODEL", "OPENAI_BASE_URL"} & updates.keys():
        _refresh_llm(getattr(state, "service", None))

    if "TRAINING_PAGE_SIZE" in updates:
        _refresh_training_page_size(getattr(state, "training_manager", None))


def _refresh_firefly(client: Any) -> None:
    from firefly_categorizer.integration.firefly import FireflyClient

    if not isinstance(client, FireflyClient):
        return
    client.refresh()
    logger.info("[CONFIG] Firefly client refreshed.")


def _refresh_llm(service: Any) -> None:
    from firefly_categorizer.manager import CategorizerService

    if not isinstance(service, CategorizerService):
        return
    service.refresh_llm()


def _refresh_training_page_size(manager: Any) -> None:
    from firefly_categorizer.services.training import TrainingManager

    if not isinstance(manager, TrainingManager):
        return
    page_size = settings.get_env_int(
        "TRAINING_PAGE_SIZE",
        settings.DEFAULT_TRAINING_PAGE_SIZE,
        min_value=1,
    )
    manager.page_size = page_size
    logger.info("[CONFIG] Training page size set to %s.", page_size)


def _format_yaml_value(value: str) -> str:
    if not value:
        return ""
    needs_quotes = value[:1].isspace() or value[-1:].isspace()
    for marker in (":", "#", '"', "'"):
        if marker in value:
            needs_quotes = True
            break
    if not needs_quotes:
        return value
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f"\"{escaped}\""
