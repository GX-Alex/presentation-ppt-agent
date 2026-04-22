import asyncio
from types import SimpleNamespace

import pytest

import app.core.llm_client as llm_client_module
from app.core.error_handling import LLMError


def _make_response(content: str = "ok") -> SimpleNamespace:
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
            )
        ],
        usage=SimpleNamespace(prompt_tokens=12, completion_tokens=8, total_tokens=20),
    )


def test_chat_falls_back_to_minimax_m25_when_primary_returns_invalid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL", "minimax/MiniMax-M2.7")
    monkeypatch.delenv("LLM_FALLBACK_MODELS", raising=False)
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    called_models: list[str] = []

    async def fake_completion(**kwargs):
        called_models.append(kwargs["model"])
        if kwargs["model"] == "minimax/MiniMax-M2.7":
            return SimpleNamespace(choices=[], usage=SimpleNamespace())
        return _make_response(content="fallback ok")

    monkeypatch.setattr(llm_client_module.litellm, "acompletion", fake_completion)

    response = asyncio.run(
        llm_client_module.chat(
            system="system",
            messages=[{"role": "user", "content": "你好"}],
            task_id="task-fallback",
        )
    )

    assert response.content == "fallback ok"
    assert response.model == "minimax/MiniMax-M2.5"
    assert called_models == ["minimax/MiniMax-M2.7", "minimax/MiniMax-M2.5"]


def test_chat_raises_llm_error_after_all_models_fail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_MODEL", "minimax/MiniMax-M2.7")
    monkeypatch.setenv("LLM_FALLBACK_MODELS", "minimax/MiniMax-M2.5")
    monkeypatch.setenv("LLM_MAX_RETRIES", "0")

    async def fake_completion(**_kwargs):
        raise RuntimeError("Minimax overloaded_error http_code 529")

    monkeypatch.setattr(llm_client_module.litellm, "acompletion", fake_completion)

    with pytest.raises(LLMError) as exc_info:
        asyncio.run(
            llm_client_module.chat(
                system="system",
                messages=[{"role": "user", "content": "继续"}],
                task_id="task-error",
            )
        )

    assert exc_info.value.message == "AI 模型调用失败"
    assert exc_info.value.detail is not None
    assert "529" in exc_info.value.detail


def test_llm_call_timeout_s_constant() -> None:
    """LLM_CALL_TIMEOUT_S should be exported and default to 120 seconds."""
    assert llm_client_module.LLM_CALL_TIMEOUT_S == 120


def test_chat_passes_request_timeout_to_litellm(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """chat() must forward request_timeout=LLM_CALL_TIMEOUT_S to litellm."""
    captured: list[dict] = []

    async def fake_completion(**kwargs):
        captured.append(dict(kwargs))
        return _make_response(content="timeout ok")

    monkeypatch.setattr(llm_client_module.litellm, "acompletion", fake_completion)

    asyncio.run(
        llm_client_module.chat(
            system="system",
            messages=[{"role": "user", "content": "test timeout"}],
        )
    )

    assert captured, "acompletion was never called"
    assert captured[0].get("request_timeout") == llm_client_module.LLM_CALL_TIMEOUT_S