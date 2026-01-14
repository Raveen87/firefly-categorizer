import os

from dotenv import load_dotenv

from firefly_categorizer.domain.tags import parse_tag_list
from firefly_categorizer.logger import get_logger

logger = get_logger(__name__)


def load_environment() -> None:
    config_dir = os.getenv("CONFIG_DIR")
    if config_dir:
        dotenv_path = os.path.join(config_dir, ".env")
        loaded = load_dotenv(dotenv_path=dotenv_path)
        if not loaded:
            load_dotenv()
    else:
        load_dotenv()


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
