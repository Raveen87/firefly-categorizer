import logging

from firefly_categorizer.core import settings


def test_get_env_float_invalid_value_coerces_to_default(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "not-a-number")

    with caplog.at_level(logging.WARNING):
        value = settings.get_env_float("AUTO_APPROVE_THRESHOLD", 0.0, min_value=0.0, max_value=1.0)

    assert value == 0.0
    assert "coerced to 0.0" in caplog.text


def test_get_env_float_out_of_range_clamps(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_THRESHOLD", "2.5")

    with caplog.at_level(logging.WARNING):
        value = settings.get_env_float("AUTO_APPROVE_THRESHOLD", 0.0, min_value=0.0, max_value=1.0)

    assert value == 1.0
    assert "above maximum 1.0" in caplog.text
    assert "coerced to 1.0" in caplog.text


def test_get_env_log_level_alias_is_coerced(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "warn")

    with caplog.at_level(logging.WARNING):
        value = settings.get_env_log_level()

    assert value == "WARNING"
    assert "LOG_LEVEL='warn'" in caplog.text
    assert "coerced to 'WARNING'" in caplog.text


def test_get_env_url_infers_scheme_and_normalizes(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("FIREFLY_URL", " localhost:8080/ ")

    with caplog.at_level(logging.WARNING):
        value = settings.get_env_url("FIREFLY_URL")

    assert value == "http://localhost:8080"
    assert "coerced to 'http://localhost:8080'" in caplog.text


def test_get_env_tags_normalizes_separators_and_duplicates(
    monkeypatch,
    caplog,
) -> None:
    monkeypatch.setenv("AUTO_APPROVE_TAGS", "alpha; beta|beta,alpha,gamma")

    with caplog.at_level(logging.WARNING):
        tags = settings.get_env_tags("AUTO_APPROVE_TAGS")

    assert tags == ["alpha", "beta", "gamma"]
    assert "coerced to 'alpha,beta,gamma'" in caplog.text
