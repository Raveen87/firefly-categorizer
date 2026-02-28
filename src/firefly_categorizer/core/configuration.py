import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from firefly_categorizer.core import settings
from firefly_categorizer.logger import get_logger

ValueType = Literal["string", "int", "float"]

logger = get_logger(__name__)


@dataclass(frozen=True)
class ConfigField:
    key: str
    yaml_path: tuple[str, str]
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
        yaml_path=("firefly", "url"),
        label="Firefly URL",
        description="Base URL for your Firefly III instance (no trailing slash).",
        placeholder="http://localhost:8080",
        input_type="url",
        category="Firefly III",
    ),
    ConfigField(
        key="FIREFLY_TOKEN",
        yaml_path=("firefly", "token"),
        label="Firefly Token",
        description="Personal Access Token from Firefly III (Profile -> OAuth).",
        placeholder="ey...",
        input_type="password",
        category="Firefly III",
        sensitive=True,
    ),
    ConfigField(
        key="FIREFLY_CATEGORIES_TTL",
        yaml_path=("firefly", "categoriesTtl"),
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
        yaml_path=("openai", "apiKey"),
        label="OpenAI API Key",
        description="API key used for optional LLM fallback.",
        placeholder="sk-...",
        input_type="password",
        category="OpenAI",
        sensitive=True,
    ),
    ConfigField(
        key="OPENAI_MODEL",
        yaml_path=("openai", "model"),
        label="OpenAI Model",
        description="Model name for the OpenAI-compatible client.",
        placeholder="gpt-3.5-turbo",
        input_type="text",
        category="OpenAI",
    ),
    ConfigField(
        key="OPENAI_BASE_URL",
        yaml_path=("openai", "baseUrl"),
        label="OpenAI Base URL",
        description="Override OpenAI base URL for compatible providers.",
        placeholder="http://localhost:11434/v1",
        input_type="url",
        category="OpenAI",
    ),
    ConfigField(
        key="AUTO_APPROVE_THRESHOLD",
        yaml_path=("automation", "autoApproveThreshold"),
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
        yaml_path=("automation", "trainingPageSize"),
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
        yaml_path=("automation", "manualTags"),
        label="Manual Tags",
        description="Comma-separated tags applied on manual save.",
        placeholder="firefly-categorizer",
        input_type="text",
        category="Automation",
    ),
    ConfigField(
        key="AUTO_APPROVE_TAGS",
        yaml_path=("automation", "autoApproveTags"),
        label="Auto-approve Tags",
        description="Comma-separated tags applied on auto-approve.",
        placeholder="firefly-categorizer,auto-approved",
        input_type="text",
        category="Automation",
    ),
    ConfigField(
        key="DATA_DIR",
        yaml_path=("storage", "dataDir"),
        label="Data Directory",
        description="Directory for memory and model artifacts.",
        placeholder="/app/data",
        input_type="text",
        category="Storage",
        restart_required=True,
    ),
    ConfigField(
        key="LOG_DIR",
        yaml_path=("storage", "logDir"),
        label="Log Directory",
        description="Directory for application logs (app.log).",
        placeholder="/app/logs",
        input_type="text",
        category="Storage",
        restart_required=True,
    ),
    ConfigField(
        key="LOG_LEVEL",
        yaml_path=("logging", "level"),
        label="Log Level",
        description="Logging verbosity for the application.",
        placeholder="INFO",
        input_type="select",
        category="Storage",
        options=("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"),
        restart_required=True,
    ),
)

DOCKER_UI_LOCKED_KEYS: tuple[str, ...] = ("DATA_DIR", "LOG_DIR", "LOG_LEVEL")


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


def _group_yaml_fields() -> list[tuple[str, list[ConfigField]]]:
    sections: list[str] = []
    grouped: dict[str, list[ConfigField]] = {}
    for field in CONFIG_FIELDS:
        section = field.yaml_path[0]
        if section not in grouped:
            grouped[section] = []
            sections.append(section)
        grouped[section].append(field)
    return [(section, grouped[section]) for section in sections]


def _yaml_comment(field: ConfigField) -> str:
    details: list[str] = []
    if field.options:
        details.append(f"Allowed values: {', '.join(field.options)}.")
    elif field.min_value is not None and field.max_value is not None:
        details.append(f"Allowed range: {field.min_value:g} to {field.max_value:g}.")
    elif field.min_value is not None:
        details.append(f"Minimum: {field.min_value:g}.")

    if field.step is not None and field.value_type == "float":
        details.append(f"Step: {field.step:g}.")

    if not details:
        return field.description
    return f"{field.description} {' '.join(details)}"


def _render_config_lines(values: Mapping[str, str]) -> list[str]:
    lines = [
        "# Firefly Categorizer configuration",
        "# These settings only take effect when the same environment variable is not set.",
        "# Environment variables and .env entries still override config.yaml values.",
        "",
    ]

    for section, fields in _group_yaml_fields():
        lines.append(f"{section}:")
        for field in fields:
            lines.append(f"  # {_yaml_comment(field)}")
            value = values.get(field.key, "")
            yaml_key = field.yaml_path[1]
            formatted = _format_yaml_value(value)
            lines.append(f"  {yaml_key}: {formatted}" if value else f"  {yaml_key}:")
            lines.append("")

        if lines[-1] == "":
            lines.pop()
        lines.append("")

    if lines[-1] == "":
        lines.pop()
    return lines


def build_config_context(
    *,
    field_errors: dict[str, str] | None = None,
) -> dict[str, object]:
    config_path = get_config_path()
    config_values = _load_config_values(config_path)
    sections: list[dict[str, object]] = []
    env_override_count = 0
    docker_ui_locked_fields: list[str] = []

    for category, fields in _group_fields():
        section_fields: list[dict[str, object]] = []
        for field in fields:
            env_override = settings.is_env_override(field.key)
            if env_override:
                env_override_count += 1
                if field.key in DOCKER_UI_LOCKED_KEYS:
                    docker_ui_locked_fields.append(field.key)
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
        "docker_ui_locked_fields": docker_ui_locked_fields,
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
    values = settings.read_config_file(config_path)
    values.update(updates)
    lines = _render_config_lines(values)

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


CONFIG_TEMPLATE = "\n".join(_render_config_lines({})) + "\n"
