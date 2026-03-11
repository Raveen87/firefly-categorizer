from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

_LOG_LEVEL_ALIASES: dict[str, str] = {
    "WARN": "WARNING",
    "FATAL": "CRITICAL",
    "ERR": "ERROR",
}

LOG_LEVEL_ALIASES: Final[Mapping[str, str]] = MappingProxyType(_LOG_LEVEL_ALIASES)

ALLOWED_LOG_LEVELS: Final[frozenset[str]] = frozenset(
    {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
)


def normalize_log_level(raw_value: str | None, default: str = "INFO") -> str:
    if raw_value is None:
        return default
    normalized = raw_value.strip().upper()
    normalized = LOG_LEVEL_ALIASES.get(normalized, normalized)
    if normalized in ALLOWED_LOG_LEVELS:
        return normalized
    return default
