from firefly_categorizer.core import configuration


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
