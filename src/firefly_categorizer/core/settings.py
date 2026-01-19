import os

from dotenv import find_dotenv, load_dotenv

from firefly_categorizer.domain.tags import parse_tag_list
from firefly_categorizer.logger import get_logger

logger = get_logger(__name__)


CONFIG_FILENAME = "config.yaml"

_CONFIG_FILE_PATH: str | None = None
_CONFIG_FILE_VALUES: dict[str, str] = {}
_EXTERNAL_ENV_KEYS: set[str] = set()

_CONFIG_KEYS = (
    "LOG_LEVEL",
    "FIREFLY_URL",
    "FIREFLY_TOKEN",
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
    with open(path, encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            key, raw_value = stripped.split(":", 1)
            key = key.strip()
            if not key:
                continue
            cleaned = _strip_inline_comment(raw_value).strip()
            if not cleaned:
                continue
            value = _unquote_value(cleaned)
            if value:
                values[key] = value
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


def get_env_float(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    return float(raw)


def get_env_tags(name: str) -> list[str]:
    return parse_tag_list(os.getenv(name))


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
    "FIREFLY_CATEGORIES_TTL",
    "OPENAI_API_KEY",
    "OPENAI_MODEL",
    "OPENAI_BASE_URL",
    "AUTO_APPROVE_THRESHOLD",
    "TRAINING_PAGE_SIZE",
    "MANUAL_TAGS",
    "AUTO_APPROVE_TAGS",
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

DATA_DIR = os.getenv("DATA_DIR", ".")
LOG_DIR = os.getenv("LOG_DIR")
CONFIG_DIR = os.getenv("CONFIG_DIR")

ensure_dirs(DATA_DIR, LOG_DIR, CONFIG_DIR)

TRAINING_PAGE_SIZE = get_env_int(
    "TRAINING_PAGE_SIZE",
    DEFAULT_TRAINING_PAGE_SIZE,
    min_value=1,
)
