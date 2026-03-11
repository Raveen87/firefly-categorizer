from firefly_categorizer.core.log_levels import normalize_log_level


def test_normalize_log_level_handles_aliases_case_and_whitespace() -> None:
    assert normalize_log_level(" warn ") == "WARNING"
    assert normalize_log_level("fatal") == "CRITICAL"
    assert normalize_log_level("Err") == "ERROR"


def test_normalize_log_level_handles_valid_casing() -> None:
    assert normalize_log_level("debug") == "DEBUG"
    assert normalize_log_level(" INFO ") == "INFO"


def test_normalize_log_level_uses_default_for_unknown_or_empty_values() -> None:
    assert normalize_log_level("warnish", default="ERROR") == "ERROR"
    assert normalize_log_level("   ", default="WARNING") == "WARNING"
    assert normalize_log_level(None, default="CRITICAL") == "CRITICAL"
