"""OpenAI-compatible LLM and embeddings client with retries, disk cache, and JSON repair."""

from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

from forgeai.budget import BudgetTracker
from forgeai.config import Settings, load_settings

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)
MAX_RETRY_DELAY_SECONDS = 60.0


class LLMError(RuntimeError):
    """Base error for LLM client failures."""


class LLMUnavailableError(LLMError):
    """Raised loudly when the configured LLM or embedding endpoint is unreachable."""


class LLMJSONError(LLMError):
    """Raised when the model fails to produce valid schema-compliant JSON after repairs."""


def strip_code_fences(raw: str) -> str:
    """Remove markdown code fences and isolate the outermost JSON object or array."""
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, flags=re.IGNORECASE)
    if fence_match:
        text = fence_match.group(1).strip()

    # If the model wrapped JSON in prose, extract from first { or [ to matching close.
    start_obj = text.find("{")
    start_arr = text.find("[")
    starts = [i for i in (start_obj, start_arr) if i != -1]
    if not starts:
        return text

    start = min(starts)
    open_ch = text[start]
    close_ch = "}" if open_ch == "{" else "]"
    end = text.rfind(close_ch)
    if end > start:
        return text[start : end + 1].strip()
    return text[start:].strip()


class LLMClient:
    """Single abstraction for chat completions and embeddings over OpenAI-compatible APIs."""

    def __init__(
        self,
        settings: Settings | None = None,
        budget: BudgetTracker | None = None,
        http_client: httpx.Client | None = None,
        cache_dir: Path | None = None,
    ) -> None:
        self.settings = settings or load_settings()
        self.budget = budget or BudgetTracker()
        self.cache_dir = Path(cache_dir or self.settings.cache_dir)
        self.chat_cache_dir = self.cache_dir / "chat"
        self.embed_cache_dir = self.cache_dir / "embed"
        self.chat_cache_dir.mkdir(parents=True, exist_ok=True)
        self.embed_cache_dir.mkdir(parents=True, exist_ok=True)
        self._owns_client = http_client is None
        self._client = http_client or httpx.Client(timeout=self.settings.timeout_seconds)
        self._local_embedding_model: Any | None = None
        self._local_embedding_model_name: str | None = None

    def close(self) -> None:
        """Close the underlying HTTP client if owned."""
        if self._owns_client:
            self._client.close()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.settings.llm_api_key:
            headers["Authorization"] = f"Bearer {self.settings.llm_api_key}"
        return headers

    @staticmethod
    def _cache_key(payload: dict[str, Any]) -> str:
        serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    @staticmethod
    def _retry_delay(response: httpx.Response, attempt: int) -> float:
        """Prefer provider rate-limit reset hints; otherwise use bounded backoff."""
        for header in (
            "retry-after",
            "x-ratelimit-reset-tokens",
            "x-ratelimit-reset-requests",
        ):
            value = response.headers.get(header, "").strip()
            if not value:
                continue
            match = re.fullmatch(
                r"(\d+(?:\.\d+)?)\s*(?:s|sec(?:ond)?s?)?",
                value,
                flags=re.IGNORECASE,
            )
            if match:
                delay = float(match.group(1))
                return min(max(0.0, delay), MAX_RETRY_DELAY_SECONDS)
            if header == "retry-after":
                try:
                    retry_at = parsedate_to_datetime(value)
                except (TypeError, ValueError, OverflowError):
                    continue
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
                return min(max(0.0, delay), MAX_RETRY_DELAY_SECONDS)

        match = re.search(
            r"(?:try again|retry) in\s+(\d+(?:\.\d+)?)\s*(?:seconds?|secs?|s)\b",
            response.text,
            flags=re.IGNORECASE,
        )
        if match:
            delay = float(match.group(1))
            return min(max(0.0, delay), MAX_RETRY_DELAY_SECONDS)
        return min(2.0 ** (attempt - 1), 4.0)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.2,
        max_tokens: int = 1024,
        model: str | None = None,
        use_cache: bool = True,
    ) -> str:
        """Execute a chat completion with disk caching, retries, timeout, and accounting."""
        target_model = (model or self.settings.llm_model).strip()
        cache_payload = {
            "model": target_model,
            "messages": messages,
            "temperature": round(float(temperature), 4),
            "max_tokens": int(max_tokens),
        }
        key = self._cache_key(cache_payload)
        cache_path = self.chat_cache_dir / f"{key}.json"

        if use_cache and cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            self.budget.record_chat(
                prompt_tokens=cached.get("prompt_tokens", 0),
                completion_tokens=cached.get("completion_tokens", 0),
                latency_s=0.0,
                cached=True,
            )
            return str(cached["content"])

        self.budget.ensure_within_budget()
        url = f"{self.settings.llm_base_url}/chat/completions"
        body = {
            "model": target_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            t0 = time.perf_counter()
            try:
                resp = self._client.post(url, headers=self._headers(), json=body)
                latency_s = time.perf_counter() - t0
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}: {resp.text[:300]}",
                        request=resp.request,
                        response=resp,
                    )
                if resp.status_code >= 400:
                    raise LLMUnavailableError(
                        f"LLM endpoint returned HTTP {resp.status_code} at {url}: {resp.text[:400]}"
                    )
                data = resp.json()
                choices = data.get("choices") or []
                if not choices:
                    raise LLMError(f"Empty choices in LLM response: {data}")
                content = (choices[0].get("message") or {}).get("content", "")
                usage = data.get("usage") or {}
                prompt_tokens = int(usage.get("prompt_tokens") or self._approx_tokens(messages))
                completion_tokens = int(
                    usage.get("completion_tokens") or max(1, len(content) // 4)
                )

                self.budget.record_chat(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_s=latency_s,
                    cached=False,
                )
                if use_cache:
                    cache_path.write_text(
                        json.dumps(
                            {
                                "model": target_model,
                                "content": content,
                                "prompt_tokens": prompt_tokens,
                                "completion_tokens": completion_tokens,
                                "latency_s": latency_s,
                            },
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                return str(content)
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "LLM chat attempt %d/%d failed (%s): %s",
                    attempt,
                    self.settings.max_retries,
                    target_model,
                    exc,
                )
                if attempt < self.settings.max_retries:
                    delay = (
                        self._retry_delay(exc.response, attempt)
                        if isinstance(exc, httpx.HTTPStatusError)
                        else min(2.0 ** (attempt - 1), 4.0)
                    )
                    logger.info("Retrying chat request in %.2f seconds.", delay)
                    time.sleep(delay)

        raise LLMUnavailableError(
            f"LLM endpoint unreachable or failed after {self.settings.max_retries} attempts "
            f"({url}, model={target_model}). Check the configured endpoint, model, and API key. "
            f"Last error: {last_error}"
        )

    def json_call(
        self,
        prompt: str | list[dict[str, str]],
        pydantic_schema: type[T],
        temperature: float = 0.0,
        max_tokens: int = 1500,
        model: str | None = None,
        max_repairs: int = 3,
        system_prompt: str | None = None,
    ) -> T:
        """Call the LLM expecting JSON matching pydantic_schema, repairing up to 3 times."""
        schema_json = json.dumps(pydantic_schema.model_json_schema(), indent=2)
        sys_msg = (
            system_prompt
            or "You are a precise JSON generator. Return ONLY valid JSON with no markdown or commentary."
        )
        if isinstance(prompt, str):
            messages: list[dict[str, str]] = [
                {"role": "system", "content": sys_msg},
                {
                    "role": "user",
                    "content": (
                        f"{prompt}\n\n"
                        "Return ONLY a single valid JSON object matching this JSON Schema "
                        "(no markdown fences, no extra prose):\n"
                        f"{schema_json}"
                    ),
                },
            ]
        else:
            messages = list(prompt)
            if not any(m.get("role") == "system" for m in messages):
                messages.insert(0, {"role": "system", "content": sys_msg})

        last_err = ""
        last_raw = ""
        for repair_idx in range(max_repairs + 1):
            raw = self.chat(
                messages=messages,
                temperature=temperature,
                max_tokens=max_tokens,
                model=model,
                use_cache=True,
            )
            last_raw = raw
            cleaned = strip_code_fences(raw)
            try:
                parsed = json.loads(cleaned)
                return pydantic_schema.model_validate(parsed)
            except (json.JSONDecodeError, ValidationError, ValueError) as exc:
                last_err = str(exc)
                logger.warning(
                    "JSON validation failed (attempt %d/%d) for %s: %s",
                    repair_idx + 1,
                    max_repairs + 1,
                    pydantic_schema.__name__,
                    last_err[:240],
                )
                if repair_idx >= max_repairs:
                    break
                messages = messages + [
                    {"role": "assistant", "content": raw},
                    {
                        "role": "user",
                        "content": (
                            f"Your previous output failed JSON parsing/validation with error:\n"
                            f"{last_err}\n\n"
                            "Fix the JSON and return ONLY valid JSON matching the schema. "
                            "Do NOT include markdown fences or explanations."
                        ),
                    },
                ]

        raise LLMJSONError(
            f"Failed to obtain valid {pydantic_schema.__name__} JSON after "
            f"{max_repairs} repair attempts. Last error: {last_err}\n"
            f"Last raw output: {last_raw[:500]}"
        )

    def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Compute embeddings for texts with disk caching and loud failure on errors."""
        if not texts:
            return []
        target_model = (model or self.settings.embed_model).strip()
        results: list[list[float] | None] = [None] * len(texts)
        missing_indices: list[int] = []
        missing_texts: list[str] = []
        cached_count = 0

        for idx, text in enumerate(texts):
            key = self._cache_key({"model": target_model, "text": text})
            path = self.embed_cache_dir / f"{key}.json"
            if path.exists():
                results[idx] = json.loads(path.read_text(encoding="utf-8"))
                cached_count += 1
            else:
                missing_indices.append(idx)
                missing_texts.append(text)

        if missing_texts:
            self.budget.ensure_within_budget()
            t_start = time.perf_counter()
            if target_model.startswith("local:"):
                model_name = target_model.removeprefix("local:").strip()
                if not model_name:
                    raise ValueError("A model name is required after the 'local:' prefix.")
                if self._local_embedding_model_name != model_name:
                    from fastembed import TextEmbedding

                    self._local_embedding_model = TextEmbedding(model_name=model_name)
                    self._local_embedding_model_name = model_name
                if self._local_embedding_model is None:
                    raise RuntimeError("Local embedding model initialization did not complete.")
                vectors = [
                    list(map(float, vector))
                    for vector in self._local_embedding_model.embed(missing_texts)
                ]
                if len(vectors) != len(missing_texts):
                    raise LLMError(
                        f"Local embedding count mismatch: expected {len(missing_texts)}, "
                        f"got {len(vectors)}"
                    )
                for idx, text, vec in zip(missing_indices, missing_texts, vectors):
                    results[idx] = vec
                    key = self._cache_key({"model": target_model, "text": text})
                    (self.embed_cache_dir / f"{key}.json").write_text(
                        json.dumps(vec), encoding="utf-8"
                    )
            else:
                url = f"{self.settings.llm_base_url}/embeddings"
                batch_size = 32
                for start in range(0, len(missing_texts), batch_size):
                    batch_texts = missing_texts[start : start + batch_size]
                    batch_indices = missing_indices[start : start + batch_size]
                    vectors = self._post_embeddings(url, target_model, batch_texts)
                    for idx, text, vec in zip(batch_indices, batch_texts, vectors):
                        results[idx] = vec
                        key = self._cache_key({"model": target_model, "text": text})
                        (self.embed_cache_dir / f"{key}.json").write_text(
                            json.dumps(vec), encoding="utf-8"
                        )
            total_latency = time.perf_counter() - t_start
            self.budget.record_embed(
                count=len(texts), cached_count=cached_count, latency_s=total_latency
            )
        else:
            self.budget.record_embed(count=len(texts), cached_count=cached_count, latency_s=0.0)

        return [vec if vec is not None else [] for vec in results]

    def _post_embeddings(
        self, url: str, target_model: str, batch_texts: list[str]
    ) -> list[list[float]]:
        body = {"model": target_model, "input": batch_texts}
        last_error: Exception | None = None
        for attempt in range(1, self.settings.max_retries + 1):
            t0 = time.perf_counter()
            try:
                resp = self._client.post(url, headers=self._headers(), json=body)
                _ = time.perf_counter() - t0
                if resp.status_code >= 500 or resp.status_code == 429:
                    raise httpx.HTTPStatusError(
                        f"HTTP {resp.status_code}: {resp.text[:300]}",
                        request=resp.request,
                        response=resp,
                    )
                if resp.status_code >= 400:
                    raise LLMUnavailableError(
                        f"Embedding endpoint returned HTTP {resp.status_code} at {url}: "
                        f"{resp.text[:400]}"
                    )
                data = resp.json()
                items = sorted(data.get("data") or [], key=lambda x: x.get("index", 0))
                if len(items) != len(batch_texts):
                    raise LLMError(
                        f"Embedding count mismatch: expected {len(batch_texts)}, got {len(items)}"
                    )
                return [list(map(float, item["embedding"])) for item in items]
            except (httpx.RequestError, httpx.HTTPStatusError, ValueError) as exc:
                last_error = exc
                logger.warning(
                    "Embedding attempt %d/%d failed (%s): %s",
                    attempt,
                    self.settings.max_retries,
                    target_model,
                    exc,
                )
                if attempt < self.settings.max_retries:
                    delay = (
                        self._retry_delay(exc.response, attempt)
                        if isinstance(exc, httpx.HTTPStatusError)
                        else min(2.0 ** (attempt - 1), 4.0)
                    )
                    logger.info("Retrying embedding request in %.2f seconds.", delay)
                    time.sleep(delay)

        raise LLMUnavailableError(
            f"Embedding endpoint unreachable or failed after {self.settings.max_retries} attempts "
            f"({url}, model={target_model}). Last error: {last_error}"
        )

    @staticmethod
    def _approx_tokens(messages: list[dict[str, str]]) -> int:
        total_chars = sum(len(m.get("content", "")) for m in messages)
        return max(1, total_chars // 4)
