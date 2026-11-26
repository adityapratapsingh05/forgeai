"""Token, latency, and cache accounting with budget enforcement."""

from __future__ import annotations

import json
from pathlib import Path

from forgeai.schemas import BudgetStats


class BudgetExceededError(RuntimeError):
    """Raised when a run exceeds its configured token or latency budget."""


class BudgetTracker:
    """Tracks cumulative LLM calls, token usage, latency, and cache hits."""

    def __init__(
        self,
        max_tokens: int | None = None,
        max_latency_s: float | None = None,
    ) -> None:
        self.stats = BudgetStats(
            max_tokens_budget=max_tokens,
            max_latency_budget_s=max_latency_s,
        )

    def record_chat(
        self,
        prompt_tokens: int,
        completion_tokens: int,
        latency_s: float,
        cached: bool,
    ) -> None:
        """Record one chat completion call (or cache hit)."""
        self.stats.total_calls += 1
        if cached:
            self.stats.cache_hits += 1
        else:
            self.stats.cache_misses += 1
            self.stats.prompt_tokens += max(0, prompt_tokens)
            self.stats.completion_tokens += max(0, completion_tokens)
            self.stats.total_tokens = (
                self.stats.prompt_tokens + self.stats.completion_tokens
            )
            self.stats.total_latency_s += max(0.0, latency_s)

        self._check_limits()

    def record_embed(self, count: int, cached_count: int, latency_s: float) -> None:
        """Record embedding requests and cache hits."""
        self.stats.embed_calls += count
        self.stats.embed_cache_hits += cached_count
        self.stats.total_latency_s += max(0.0, latency_s)
        self._check_limits()

    def _check_limits(self) -> None:
        if (
            self.stats.max_tokens_budget is not None
            and self.stats.total_tokens > self.stats.max_tokens_budget
        ):
            self.stats.budget_exceeded = True
            self.stats.exceeded_reason = (
                f"Token budget exceeded: {self.stats.total_tokens} > "
                f"{self.stats.max_tokens_budget}"
            )
        elif (
            self.stats.max_latency_budget_s is not None
            and self.stats.total_latency_s > self.stats.max_latency_budget_s
        ):
            self.stats.budget_exceeded = True
            self.stats.exceeded_reason = (
                f"Latency budget exceeded: {self.stats.total_latency_s:.1f}s > "
                f"{self.stats.max_latency_budget_s:.1f}s"
            )

    def ensure_within_budget(self) -> None:
        """Raise BudgetExceededError if the budget has been exhausted."""
        self._check_limits()
        if self.stats.budget_exceeded:
            raise BudgetExceededError(self.stats.exceeded_reason)

    def save(self, path: Path) -> None:
        """Write budget and cache statistics to JSON."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.stats.model_dump(), indent=2),
            encoding="utf-8",
        )
