import os
from pathlib import Path

from firefly_categorizer.core import configuration, settings


def _env_example_keys() -> set[str]:
    env_example_path = Path(__file__).resolve().parents[1] / ".env.example"
    env_example = env_example_path.read_text(encoding="utf-8").splitlines()
    keys: set[str] = set()
    for line in env_example:
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# "):
            stripped = stripped[2:]
        if "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if key.isupper():
            keys.add(key)
    return keys


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
                "  httpTimeout: 12.5",
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
        "FIREFLY_HTTP_TIMEOUT": "12.5",
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


def test_load_environment_treats_blank_env_values_as_missing_for_config_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    for key in settings._CONFIG_KEYS:  # noqa: SLF001
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        settings,
        "_CONFIG_FILE_PATH",
        settings._CONFIG_FILE_PATH,  # noqa: SLF001
    )
    monkeypatch.setattr(
        settings,
        "_CONFIG_FILE_VALUES",
        settings._CONFIG_FILE_VALUES.copy(),  # noqa: SLF001
    )
    monkeypatch.setattr(
        settings,
        "_EXTERNAL_ENV_KEYS",
        settings._EXTERNAL_ENV_KEYS.copy(),  # noqa: SLF001
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "config.yaml").write_text(
        "\n".join(
            [
                "firefly:",
                "  url: http://firefly.local",
                "  token: config-token",
                "openai:",
                "  apiKey: config-openai-key",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("FIREFLY_URL", "")
    monkeypatch.setenv("FIREFLY_TOKEN", "   ")
    monkeypatch.setenv("OPENAI_API_KEY", "")

    settings.load_environment()

    assert os.getenv("FIREFLY_URL") == "http://firefly.local"
    assert os.getenv("FIREFLY_TOKEN") == "config-token"
    assert os.getenv("OPENAI_API_KEY") == "config-openai-key"
    assert not settings.is_env_override("FIREFLY_URL")
    assert not settings.is_env_override("FIREFLY_TOKEN")
    assert not settings.is_env_override("OPENAI_API_KEY")

    context = configuration.build_config_context()
    fields = {
        field["key"]: field
        for section in context["sections"]
        for field in section["fields"]
    }
    assert fields["FIREFLY_URL"]["disabled"] is False
    assert fields["FIREFLY_URL"]["value"] == "http://firefly.local"
    assert fields["FIREFLY_TOKEN"]["disabled"] is False


def test_load_environment_treats_blank_env_values_as_missing_for_dotenv(
    monkeypatch,
    tmp_path: Path,
) -> None:
    for key in settings._CONFIG_KEYS:  # noqa: SLF001
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(
        settings,
        "_CONFIG_FILE_PATH",
        settings._CONFIG_FILE_PATH,  # noqa: SLF001
    )
    monkeypatch.setattr(
        settings,
        "_CONFIG_FILE_VALUES",
        settings._CONFIG_FILE_VALUES.copy(),  # noqa: SLF001
    )
    monkeypatch.setattr(
        settings,
        "_EXTERNAL_ENV_KEYS",
        settings._EXTERNAL_ENV_KEYS.copy(),  # noqa: SLF001
    )

    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / ".env").write_text(
        "\n".join(
            [
                "FIREFLY_URL=http://dotenv-firefly.local",
                "FIREFLY_TOKEN=dotenv-token",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "config.yaml").write_text(
        "\n".join(
            [
                "firefly:",
                "  url: http://config-firefly.local",
                "  token: config-token",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("FIREFLY_URL", "")
    monkeypatch.setenv("FIREFLY_TOKEN", "   ")

    settings.load_environment()

    assert os.getenv("FIREFLY_URL") == "http://dotenv-firefly.local"
    assert os.getenv("FIREFLY_TOKEN") == "dotenv-token"
    assert settings.is_env_override("FIREFLY_URL")
    assert settings.is_env_override("FIREFLY_TOKEN")


def test_write_config_file_emits_nested_lower_camel_yaml(
    monkeypatch,
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yaml"
    monkeypatch.setattr(configuration, "get_config_path", lambda: str(config_path))

    configuration._write_config_file(  # noqa: SLF001
        {
            "FIREFLY_URL": "http://localhost:8080",
            "FIREFLY_HTTP_TIMEOUT": "12.5",
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
        "  # Seconds before Firefly III API requests time out. Minimum: 0. Step: 0.01.\n"
        "  httpTimeout: 12.5" in rendered
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


def test_config_registry_matches_settings_keys() -> None:
    assert configuration.get_config_keys() == settings._CONFIG_KEYS  # noqa: SLF001


def test_config_registry_matches_yaml_paths() -> None:
    field_paths = {field.key: field.yaml_path for field in configuration.CONFIG_FIELDS}

    assert field_paths == settings._CONFIG_KEY_PATHS  # noqa: SLF001


def test_env_example_lists_all_config_keys() -> None:
    documented_keys = _env_example_keys()

    assert set(configuration.get_config_keys()).issubset(documented_keys)
