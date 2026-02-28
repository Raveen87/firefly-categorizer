from pathlib import Path

from firefly_categorizer.core import configuration, settings


def test_build_config_context_includes_docker_locked_storage_fields(
    monkeypatch,
) -> None:
    locked = {"DATA_DIR", "LOG_DIR", "LOG_LEVEL"}
    monkeypatch.setattr(configuration, "get_config_path", lambda: None)
    monkeypatch.setattr(configuration, "_load_config_values", lambda _path: {})
    monkeypatch.setattr(
        configuration.settings,
        "is_env_override",
        lambda key: key in locked,
    )

    context = configuration.build_config_context()

    assert context["docker_ui_locked_fields"] == ["DATA_DIR", "LOG_DIR", "LOG_LEVEL"]


def test_build_config_context_omits_docker_locked_fields_when_unlocked(
    monkeypatch,
) -> None:
    monkeypatch.setattr(configuration, "get_config_path", lambda: None)
    monkeypatch.setattr(configuration, "_load_config_values", lambda _path: {})
    monkeypatch.setattr(
        configuration.settings,
        "is_env_override",
        lambda _key: False,
    )

    context = configuration.build_config_context()

    assert context["docker_ui_locked_fields"] == []


def test_read_config_file_supports_nested_lower_camel_yaml(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "firefly:",
                "  url: http://localhost:8080",
                "  token: secret-token",
                "automation:",
                "  autoApproveThreshold: 0.9",
                "  manualTags: firefly-categorizer,reviewed",
                "logging:",
                "  level: DEBUG",
                "",
            ]
        ),
        encoding="utf-8",
    )

    values = settings.read_config_file(str(config_path))

    assert values == {
        "FIREFLY_URL": "http://localhost:8080",
        "FIREFLY_TOKEN": "secret-token",
        "AUTO_APPROVE_THRESHOLD": "0.9",
        "MANUAL_TAGS": "firefly-categorizer,reviewed",
        "LOG_LEVEL": "DEBUG",
    }


def test_read_config_file_ignores_legacy_env_style_keys(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "\n".join(
            [
                "FIREFLY_URL: http://localhost:8080",
                "OPENAI_MODEL: gpt-4o-mini",
                "AUTO_APPROVE_THRESHOLD: 0.9",
                "",
            ]
        ),
        encoding="utf-8",
    )

    values = settings.read_config_file(str(config_path))

    assert values == {}


def test_write_config_file_emits_nested_lower_camel_yaml(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(configuration, "get_config_path", lambda: str(config_path))

    configuration._write_config_file(  # noqa: SLF001
        {
            "FIREFLY_URL": "http://localhost:8080",
            "OPENAI_MODEL": "gpt-4o-mini",
            "AUTO_APPROVE_THRESHOLD": "0.9",
            "LOG_LEVEL": "INFO",
        }
    )

    rendered = config_path.read_text(encoding="utf-8")

    assert (
        'firefly:\n  # Base URL for your Firefly III instance (no trailing slash).\n  url: "http://localhost:8080"'
        in rendered
    )
    assert (
        "openai:\n  # API key used for optional LLM fallback.\n  apiKey:\n\n"
        "  # Model name for the OpenAI-compatible client.\n  model: gpt-4o-mini" in rendered
    )
    assert (
        "automation:\n  # Confidence threshold (0-1). 0 disables auto-approve. Allowed range: 0 to 1. Step: 0.01.\n"
        "  autoApproveThreshold: 0.9" in rendered
    )
    assert (
        "logging:\n  # Logging verbosity for the application. Allowed values: DEBUG, INFO, WARNING, ERROR, CRITICAL.\n"
        "  level: INFO" in rendered
    )
