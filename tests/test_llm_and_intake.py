"""Tests for LLMClient JSON repair, caching, loud failure, and intake question cap."""

from __future__ import annotations

import json
import sys
import types
from dataclasses import replace
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from forgeai.budget import BudgetTracker
from forgeai.config import Settings
from forgeai.intake import MAX_CLARIFYING_QUESTIONS, cap_questions, _QuestionItem
from forgeai.llm import LLMClient, LLMJSONError, LLMUnavailableError, strip_code_fences


class _SampleOut(BaseModel):
    topic: str
    count: int


def _make_settings(tmp_path: Path) -> Settings:
    return Settings(
        llm_base_url="http://mock.local/v1",
        llm_model="test-model",
        llm_api_key="test",
        embed_model="test-embed",
        judge_model="test-model",
        timeout_seconds=5.0,
        max_retries=2,
        cache_dir=tmp_path / "cache",
    )


def test_strip_code_fences() -> None:
    raw = "Here is the JSON:\n```json\n{\"topic\": \"leave\", \"count\": 3}\n```\nDone."
    assert strip_code_fences(raw) == '{"topic": "leave", "count": 3}'


def test_json_call_repairs_and_caches(tmp_path: Path) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            content = "not valid json at all"
        elif calls["n"] == 2:
            content = '```json\n{"topic": "leave", "count": "not_an_int"}\n```'
        else:
            content = '{"topic": "leave", "count": 5}'
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": content}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )

    transport = httpx.MockTransport(handler)
    client = httpx.Client(transport=transport)
    budget = BudgetTracker()
    llm = LLMClient(settings=_make_settings(tmp_path), budget=budget, http_client=client)

    res = llm.json_call("Extract topic and count", _SampleOut, max_repairs=3)
    assert res.topic == "leave" and res.count == 5
    assert calls["n"] == 3
    assert budget.stats.cache_misses == 3

    # Second identical call hits disk cache (0 additional HTTP requests)
    res2 = llm.json_call("Extract topic and count", _SampleOut, max_repairs=3)
    assert res2 == res
    assert calls["n"] == 3
    assert budget.stats.cache_hits >= 1


def test_json_call_raises_after_max_repairs(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "always broken"}}]},
        )

    llm = LLMClient(
        settings=_make_settings(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMJSONError):
        llm.json_call("Give json", _SampleOut, max_repairs=3)


def test_llm_unavailable_fails_loudly(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    llm = LLMClient(
        settings=_make_settings(tmp_path),
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(LLMUnavailableError):
        llm.chat([{"role": "user", "content": "hi"}], use_cache=False)


@pytest.mark.parametrize(
    ("headers", "error_message", "expected_delay"),
    [
        ({"Retry-After": "0.25"}, "Please try again in 2s.", 0.25),
        ({}, "Rate limit reached. Please try again in 17.1525s.", 17.1525),
        ({"x-ratelimit-reset-tokens": "3.5s"}, "Rate limit reached.", 3.5),
    ],
)
def test_chat_rate_limit_retry_honors_provider_delay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    headers: dict[str, str],
    error_message: str,
    expected_delay: float,
) -> None:
    calls = {"count": 0}
    delays: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        if calls["count"] == 1:
            return httpx.Response(
                429,
                headers=headers,
                json={"error": {"message": error_message}},
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": "ready"}}]},
        )

    monkeypatch.setattr("forgeai.llm.time.sleep", delays.append)
    settings = replace(_make_settings(tmp_path), max_retries=2)
    llm = LLMClient(
        settings=settings,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )

    assert llm.chat([{"role": "user", "content": "hi"}], use_cache=False) == "ready"
    assert calls["count"] == 2
    assert delays == [expected_delay]


def test_local_embeddings_use_fastembed_and_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    model_names: list[str] = []
    embedded_batches: list[list[str]] = []

    class FakeTextEmbedding:
        def __init__(self, model_name: str) -> None:
            model_names.append(model_name)

        def embed(self, texts: list[str]) -> list[list[float]]:
            embedded_batches.append(texts)
            return [[float(len(text)), 1.0] for text in texts]

    fastembed_module = types.ModuleType("fastembed")
    fastembed_module.TextEmbedding = FakeTextEmbedding
    monkeypatch.setitem(sys.modules, "fastembed", fastembed_module)

    def unexpected_request(request: httpx.Request) -> httpx.Response:
        pytest.fail(f"Local embeddings unexpectedly called {request.url}")

    settings = replace(
        _make_settings(tmp_path),
        embed_model="local:sentence-transformers/all-MiniLM-L6-v2",
    )
    budget = BudgetTracker()
    llm = LLMClient(
        settings=settings,
        budget=budget,
        http_client=httpx.Client(transport=httpx.MockTransport(unexpected_request)),
    )

    first = llm.embed(["leave policy", "travel policy"])
    second = llm.embed(["leave policy"])

    assert first == [[12.0, 1.0], [13.0, 1.0]]
    assert second == [[12.0, 1.0]]
    assert model_names == ["sentence-transformers/all-MiniLM-L6-v2"]
    assert embedded_batches == [["leave policy", "travel policy"]]
    assert budget.stats.embed_calls == 3
    assert budget.stats.embed_cache_hits == 1


def test_intake_question_cap_enforced() -> None:
    items = [_QuestionItem(question=f"Q{i}?", target_dimension="scope") for i in range(10)]
    capped = cap_questions(items, max_questions=20)
    assert len(capped) == MAX_CLARIFYING_QUESTIONS == 5
    assert len(cap_questions(items, max_questions=3)) == 3
