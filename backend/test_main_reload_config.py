import main as backend_main


def test_uvicorn_reload_config_excludes_runtime_data(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "development")

    kwargs = backend_main._get_uvicorn_run_kwargs()

    assert kwargs["reload"] is True
    assert "data/**" in kwargs["reload_excludes"]
    assert "*.db" in kwargs["reload_excludes"]
    assert ".venv/**" in kwargs["reload_excludes"]
    assert kwargs["reload_includes"] == ["*.py"]
    # reload_dirs must be scoped to app/ only — not the whole backend root with .venv
    assert any("app" in str(d) for d in kwargs["reload_dirs"])
    assert not any(str(d).endswith("/backend") for d in kwargs["reload_dirs"])


def test_uvicorn_reload_config_disabled_outside_development(monkeypatch) -> None:
    monkeypatch.setenv("ENV", "production")

    kwargs = backend_main._get_uvicorn_run_kwargs()

    assert kwargs["reload"] is False
    assert "reload_excludes" not in kwargs