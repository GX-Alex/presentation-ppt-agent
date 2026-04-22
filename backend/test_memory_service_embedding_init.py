import os
import sys
import types

from app.services import memory_service


def test_find_cached_embed_model_path_prefers_latest_snapshot(tmp_path, monkeypatch) -> None:
    older = tmp_path / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / "older"
    newer = tmp_path / "hub" / "models--sentence-transformers--all-MiniLM-L6-v2" / "snapshots" / "newer"
    older.mkdir(parents=True)
    newer.mkdir(parents=True)
    os.utime(older, (1, 1))
    os.utime(newer, (2, 2))

    monkeypatch.setenv("HF_HOME", str(tmp_path))

    assert memory_service._find_cached_embed_model_path() == str(newer)


def test_get_embed_model_uses_local_cache_only_and_stops_retrying(monkeypatch) -> None:
    calls: list[tuple[str, dict]] = []

    class DummySentenceTransformer:
        def __init__(self, model_name_or_path: str, **kwargs):
            calls.append((model_name_or_path, kwargs))
            raise RuntimeError("cache miss")

    monkeypatch.setitem(
        sys.modules,
        "sentence_transformers",
        types.SimpleNamespace(SentenceTransformer=DummySentenceTransformer),
    )
    monkeypatch.setattr(memory_service, "_embed_model", None)
    monkeypatch.setattr(memory_service, "_embed_model_load_attempted", False)
    monkeypatch.setattr(memory_service, "_find_cached_embed_model_path", lambda: None)
    monkeypatch.delenv("GENERALAGENT_EMBEDDING_ALLOW_REMOTE", raising=False)

    assert memory_service._get_embed_model() is None
    assert memory_service._get_embed_model() is None

    assert len(calls) == 1
    model_name_or_path, kwargs = calls[0]
    assert model_name_or_path == memory_service._EMBED_MODEL_NAME
    assert kwargs["local_files_only"] is True
    assert kwargs["trust_remote_code"] is False