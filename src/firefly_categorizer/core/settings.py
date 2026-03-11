import os
import re
from math import isfinite
from typing import overload
from urllib.parse import urlparse

from dotenv import find_dotenv, load_dotenv

from firefly_categorizer.core.log_levels import (
    ALLOWED_LOG_LEVELS,
    LOG_LEVEL_ALIASES,
    normalize_log_level,
)
from firefly_categorizer.domain.tags import parse_tag_list
from firefly_categorizer.logger import get_logger

logger = get_logger(__name__)


CONFIG_FILENAME = "config.yaml"

_CONFIG_FILE_PATH: str | None = None
_CONFIG_FILE_VALUES: dict[str, str] = {}
_EXTERNAL_ENV_KEYS: set[str] = set()

_CONFIG_KEYS = (
    "FIREFLY_URL",
    "FIREFLY_TOKEN",
    "FIREFLY_HTTP_TIMEOUT",
    "FIREFLY_CATEGORIES_TTL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "AUTO_APPROVE_THRESHOLD",
    "TRAINING_PAGE_SIZE",
    "MANUAL_TAGS",
    "AUTO_APPROVE_TAGS",
    "DATA_DIR",
    "LOG_DIR",
    "LOG_LEVEL",
)

_CONFIG_KEY_PATHS: dict[str, tuple[str, str]] = {
    "FIREFLY_URL": ("firefly", "url"),
    "FIREFLY_TOKEN": ("firefly", "token"),
    "FIREFLY_HTTP_TIMEOUT": ("firefly", "httpTimeout"),
    "FIREFLY_CATEGORIES_TTL": ("firefly", "categoriesTtl"),
    "OPENAI_API_KEY": ("openai", "apiKey"),
    "OPENAI_MODEL": ("openai", "model"),
    "OPENAI_BASE_URL": ("openai", "baseUrl"),
    "AUTO_APPROVE_THRESHOLD": ("automation", "autoApproveThreshold"),
    "TRAINING_PAGE_SIZE": ("automation", "trainingPageSize"),
    "MANUAL_TAGS": ("automation", "manualTags"),
    "AUTO_APPROVE_TAGS": ("automation", "autoApproveTags"),
    "DATA_DIR": ("storage", "dataDir"),
    "LOG_DIR": ("storage", "logDir"),
    "LOG_LEVEL": ("logging", "level"),
}
_CONFIG_PATH_TO_KEY = {path: key for key, path in _CONFIG_KEY_PATHS.items()}
_CONFIG_ROOT_KEYS = {path[0] for path in _CONFIG_KEY_PATHS.values()}


def _resolve_dotenv_path() -> str | None:
    config_dir = os.getenv("CONFIG_DIR")
    if config_dir:
        candidate = os.path.join(config_dir, ".env")
        if os.path.exists(candidate):
            return candidate
    resolved = find_dotenv(usecwd=True)
    return resolved or None


def _resolve_config_path() -> str:
    config_dir = os.getenv("CONFIG_DIR")
    if config_dir:
        return os.path.join(config_dir, CONFIG_FILENAME)
    cwd = os.getcwd()
    candidate = os.path.join(cwd, "config", CONFIG_FILENAME)
    if os.path.exists(candidate):
        return candidate
    return os.path.join(cwd, CONFIG_FILENAME)


def _strip_inline_comment(raw_value: str) -> str:
    in_single = False
    in_double = False
    escaped = False
    for index, char in enumerate(raw_value):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"' and not in_single:
            in_double = not in_double
            continue
        if char == "'" and not in_double:
            in_single = not in_single
            continue
        if char == "#" and not in_single and not in_double:
            return raw_value[:index].rstrip()
    return raw_value


def _unquote_value(raw_value: str) -> str:
    if len(raw_value) < 2:
        return raw_value
    if raw_value[0] == raw_value[-1] == '"':
        value = raw_value[1:-1]
        return value.replace('\\"', '"').replace("\\\\", "\\")
    if raw_value[0] == raw_value[-1] == "'":
        value = raw_value[1:-1]
        return value.replace("\\'", "'").replace("\\\\", "\\")
    return raw_value


def read_config_file(path: str | None) -> dict[str, str]:
    if not path or not os.path.exists(path):
        return {}

    values: dict[str, str] = {}
    current_section: str | None = None
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            indent = len(line) - len(line.lstrip(" "))
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if indent == 0:
                current_section = None
            if ":" not in stripped:
                continue
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            if not key:
                continue
            cleaned = _strip_inline_comment(raw_value).strip()
            if not cleaned:
                if indent == 0 and key in _CONFIG_ROOT_KEYS:
                    current_section = key
                continue
            value = _unquote_value(cleaned)
            if value:
                if current_section is None:
                    continue
                mapped_key = _CONFIG_PATH_TO_KEY.get((current_section, key))
                if mapped_key:
                    values[mapped_key] = value
    return values


def load_environment() -> None:
    global _CONFIG_FILE_PATH
    global _CONFIG_FILE_VALUES
    global _EXTERNAL_ENV_KEYS

    dotenv_path = _resolve_dotenv_path()
    if dotenv_path:
        load_dotenv(dotenv_path=dotenv_path, override=False)

    _EXTERNAL_ENV_KEYS = set(os.environ.keys())

    _CONFIG_FILE_PATH = _resolve_config_path()
    _CONFIG_FILE_VALUES = read_config_file(_CONFIG_FILE_PATH)

    for key in _CONFIG_KEYS:
        if key not in os.environ and key in _CONFIG_FILE_VALUES:
            os.environ[key] = _CONFIG_FILE_VALUES[key]


def get_config_path() -> str | None:
    return _CONFIG_FILE_PATH


def get_config_file_values() -> dict[str, str]:
    return dict(_CONFIG_FILE_VALUES)


def is_env_override(name: str) -> bool:
    return name in _EXTERNAL_ENV_KEYS


def ensure_dir(path: str | None) -> None:
    if path and path not in {".", "./"}:
        os.makedirs(path, exist_ok=True)


def ensure_dirs(*paths: str | None) -> None:
    for path in paths:
        ensure_dir(path)


def get_env_int(name: str, default: int, min_value: int | None = None) -> int:
    raw = os.getenv(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("[ENV] Invalid %s='%s', using default %s.", name, raw, default)
        return default
    if min_value is not None and value < min_value:
        logger.warning(
            "[ENV] %s='%s' below minimum %s, using default %s.",
            name,
            raw,
            min_value,
            default,
        )
        return default
    return value


def get_env_float(
    name: str,
    default: float = 0.0,
    min_value: float | None = None,
    max_value: float | None = None,
) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError:
        _log_env_coercion(name, raw, str(default), "is not a valid number")
        return default
    if not isfinite(value):
        _log_env_coercion(name, raw, str(default), "is not a finite number")
        return default
    if min_value is not None and value < min_value:
        _log_env_coercion(name, raw, str(min_value), f"is below minimum {min_value}")
        value = min_value
    if max_value is not None and value > max_value:
        _log_env_coercion(name, raw, str(max_value), f"is above maximum {max_value}")
        value = max_value
    return value


def get_env_tags(name: str) -> list[str]:
    raw = os.getenv(name)
    if raw is None:
        return []
    normalized = _normalize_tag_value(raw)
    if normalized != raw:
        logger.warning(
            "[ENV] Invalid %s='%s', coerced to '%s'.",
            name,
            _mask_env_value(name, raw),
            _mask_env_value(name, normalized),
        )
    return parse_tag_list(normalized)


_SENSITIVE_ENV_KEYS = (
    "KEY",
    "TOKEN",
    "SECRET",
    "PASSWORD",
    "PASS",
    "AUTH",
    "BEARER",
    "PRIVATE",
)

_ENV_KEYS_TO_LOG = (
    "LOG_LEVEL",
    "FIREFLY_URL",
    "FIREFLY_TOKEN",
    "FIREFLY_HTTP_TIMEOUT",
    "FIREFLY_CATEGORIES_TTL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "AUTO_APPROVE_THRESHOLD",
    "TRAINING_PAGE_SIZE",
    "MANUAL_TAGS",
    "AUTO_APPROVE_TAGS",
    "DATA_DIR",
    "LOG_DIR",
)


def _should_mask_env_value(name: str, value: str) -> bool:
    upper_name = name.upper()
    if any(marker in upper_name for marker in _SENSITIVE_ENV_KEYS):
        return True
    if value.startswith("sk-") or value.startswith("rk-"):
        return True
    if value.startswith("Bearer ") or value.startswith("bearer "):
        return True
    if value.startswith("eyJ") and value.count(".") == 2:
        return True
    return False


def _mask_env_value(name: str, value: str) -> str:
    sanitized = value.replace("\r", "\\r").replace("\n", "\\n")
    if not _should_mask_env_value(name, sanitized):
        return sanitized
    if len(sanitized) <= 4:
        return "****"
    return f"{sanitized[:2]}...{sanitized[-2:]}"


def _log_env_coercion(name: str, raw: str, coerced: str | None, reason: str) -> None:
    raw_safe = _mask_env_value(name, raw)
    if coerced is None:
        coerced_safe = "<unset>"
    else:
        coerced_safe = _mask_env_value(name, coerced)
    logger.warning(
        "[ENV] %s='%s' %s, coerced to '%s'.",
        name,
        raw_safe,
        reason,
        coerced_safe,
    )


def _normalize_log_level(raw_value: str, default: str = "INFO") -> str:
    return normalize_log_level(raw_value, default=default)


def get_env_log_level(name: str = "LOG_LEVEL", default: str = "INFO") -> str:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    raw_normalized = raw.strip().upper()
    normalized = _normalize_log_level(raw, default=default)
    if normalized != raw:
        if raw_normalized in LOG_LEVEL_ALIASES:
            _log_env_coercion(name, raw, normalized, "uses an alias")
        elif raw_normalized in ALLOWED_LOG_LEVELS:
            _log_env_coercion(name, raw, normalized, "is not normalized")
        else:
            _log_env_coercion(name, raw, normalized, "is not a valid logging level")
    return normalized


def _normalize_tag_value(raw_value: str) -> str:
    candidate = re.sub(r"[;|]+", ",", raw_value)
    tags = parse_tag_list(candidate)
    return ",".join(tags)


def _is_valid_url(value: str) -> bool:
    parsed = urlparse(value)
    return bool(parsed.scheme and parsed.netloc)


def _normalize_url_value(raw_value: str) -> str | None:
    normalized = raw_value.strip()
    if not normalized:
        return None
    if "://" not in normalized and not normalized.startswith("/"):
        normalized = f"http://{normalized}"
    normalized = normalized.rstrip("/")
    if not _is_valid_url(normalized):
        return None
    return normalized


def _normalize_path_value(raw_value: str | None, default: str | None = None) -> str | None:
    if raw_value is None:
        return default
    normalized = raw_value.strip()
    if not normalized:
        return default
    return normalized


def get_env_url(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = _normalize_url_value(raw)
    if normalized is None:
        _log_env_coercion(name, raw, default, "is not a valid URL")
        return default
    if normalized != raw:
        _log_env_coercion(name, raw, normalized, "is not normalized")
    return normalized


def get_env_path(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = _normalize_path_value(raw, default=None)
    if not normalized:
        _log_env_coercion(name, raw, default, "is empty")
        return default
    return normalized


@overload
def get_env_text(name: str, default: None = None) -> str | None: ...


@overload
def get_env_text(name: str, default: str) -> str: ...


def get_env_text(name: str, default: str | None = None) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return default
    normalized = raw.strip()
    if not normalized:
        if default is not None:
            _log_env_coercion(name, raw, default, "is empty")
        return default
    if normalized != raw:
        _log_env_coercion(name, raw, normalized, "contains leading or trailing whitespace")
    return normalized


def coerce_runtime_environment() -> None:
    for key in _CONFIG_KEYS:
        raw = os.getenv(key)
        if raw is None:
            continue
        coerced: str | None = raw
        if key == "LOG_LEVEL":
            coerced = get_env_log_level(name=key, default="INFO")
        elif key == "FIREFLY_HTTP_TIMEOUT":
            coerced = str(
                get_env_float(
                    key,
                    60.0,
                    min_value=0.0,
                )
            )
        elif key == "FIREFLY_CATEGORIES_TTL":
            coerced = str(
                get_env_float(
                    key,
                    60.0,
                    min_value=0.0,
                )
            )
        elif key == "AUTO_APPROVE_THRESHOLD":
            coerced = str(
                get_env_float(
                    key,
                    0.0,
                    min_value=0.0,
                    max_value=1.0,
                )
            )
        elif key == "TRAINING_PAGE_SIZE":
            coerced = str(
                get_env_int(
                    key,
                    DEFAULT_TRAINING_PAGE_SIZE,
                    min_value=1,
                )
            )
        elif key in {"FIREFLY_URL", "OPENAI_BASE_URL"}:
            coerced = get_env_url(key)
        elif key in {"MANUAL_TAGS", "AUTO_APPROVE_TAGS"}:
            coerced = _normalize_tag_value(raw)
            if coerced != raw:
                _log_env_coercion(key, raw, coerced, "contains malformed separators or duplicate tags")
        elif key == "DATA_DIR":
            coerced = get_env_path(key, default=".")
        elif key == "LOG_DIR":
            coerced = get_env_path(key, default=None)
        elif key in {"FIREFLY_TOKEN", "OPENAI_API_KEY", "OPENAI_MODEL"}:
            coerced = get_env_text(key)

        if coerced is None:
            os.environ.pop(key, None)
            continue
        os.environ[key] = coerced


def log_environment() -> None:
    logger.info("[ENV] Logging configured environment variables (masked where needed).")
    for key in _ENV_KEYS_TO_LOG:
        raw_value = os.getenv(key)
        value = "<unset>" if raw_value is None else _mask_env_value(key, raw_value)
        logger.info("[ENV] %s=%s", key, value)


DEFAULT_TRAINING_PAGE_SIZE = 50

# SSE headers to reduce proxy buffering and keep connections alive.
SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

STREAM_YIELD_EVERY = 50


load_environment()

DATA_DIR = _normalize_path_value(os.getenv("DATA_DIR"), ".") or "."
LOG_DIR = _normalize_path_value(os.getenv("LOG_DIR"))
CONFIG_DIR = os.getenv("CONFIG_DIR")

ensure_dirs(DATA_DIR, LOG_DIR, CONFIG_DIR)

TRAINING_PAGE_SIZE = get_env_int(
    "TRAINING_PAGE_SIZE",
    DEFAULT_TRAINING_PAGE_SIZE,
    min_value=1,
)
