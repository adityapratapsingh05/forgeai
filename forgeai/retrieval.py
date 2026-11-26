"""Hybrid BM25 + embedding retriever with configurable weighting and min_score."""

from __future__ import annotations

import logging
import math
import re
from typing import Iterable

import numpy as np
from rank_bm25 import BM25Okapi

from forgeai.llm import LLMClient
from forgeai.schemas import DocumentChunk, RetrievalConfig, RetrievedChunkHit

logger = logging.getLogger(__name__)


def tokenize_text(text: str) -> list[str]:
    """Unicode-aware word tokenizer for BM25 and deterministic keyword overlap."""
    return re.findall(r"\w+", text.lower(), flags=re.UNICODE)


class HybridRetriever:
    """Combines BM25 lexical search and dense cosine similarity over DocumentChunks."""

    def __init__(
        self,
        chunks: list[DocumentChunk],
        config: RetrievalConfig,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.chunks = chunks
        self.config = config
        self.llm_client = llm_client
        self._tokenized = [tokenize_text(f"{c.source_file} {c.page_or_section} {c.text}") for c in chunks]
        self._bm25 = BM25Okapi(self._tokenized) if chunks and any(self._tokenized) else None
        self._embeddings: np.ndarray | None = None

        if chunks and self.config.hybrid_alpha > 0.0 and self.llm_client is not None:
            texts = [c.text for c in chunks]
            vecs = self.llm_client.embed(texts)
            if vecs and vecs[0]:
                arr = np.asarray(vecs, dtype=np.float32)
                norms = np.linalg.norm(arr, axis=1, keepdims=True)
                norms = np.where(norms == 0.0, 1.0, norms)
                self._embeddings = arr / norms

    def search(
        self,
        query: str,
        top_k: int | None = None,
        min_score: float | None = None,
        apply_min_score: bool = True,
    ) -> list[RetrievedChunkHit]:
        """Return top-k retrieved chunks, optionally filtered by min_score."""
        if not self.chunks or not query.strip():
            return []

        k = top_k if top_k is not None else self.config.top_k
        threshold = min_score if min_score is not None else self.config.min_score
        q_tokens = tokenize_text(query)

        # Saturating BM25 normalization: 0 when no match, ~0.5..0.95 for strong lexical hits.
        if self._bm25 is not None and q_tokens:
            raw_bm25 = np.asarray(self._bm25.get_scores(q_tokens), dtype=np.float32)
            raw_bm25 = np.maximum(0.0, raw_bm25)
            bm25_scores = raw_bm25 / (raw_bm25 + 4.0)
        else:
            bm25_scores = np.zeros(len(self.chunks), dtype=np.float32)

        alpha = self.config.hybrid_alpha
        if self._embeddings is not None and alpha > 0.0 and self.llm_client is not None:
            q_vec_list = self.llm_client.embed([query])
            q_vec = np.asarray(q_vec_list[0], dtype=np.float32)
            q_norm = float(np.linalg.norm(q_vec))
            if q_norm > 0.0:
                q_vec = q_vec / q_norm
                embed_scores = np.maximum(
                    0.0, np.sum(self._embeddings * q_vec, axis=1)
                )
            else:
                embed_scores = np.zeros(len(self.chunks), dtype=np.float32)
            combined = alpha * embed_scores + (1.0 - alpha) * bm25_scores
        else:
            embed_scores = np.zeros(len(self.chunks), dtype=np.float32)
            combined = bm25_scores

        order = np.argsort(-combined)[:k]
        hits: list[RetrievedChunkHit] = []
        for idx in order:
            score = float(combined[idx])
            if math.isnan(score):
                score = 0.0
            if apply_min_score and score < threshold:
                continue
            chunk = self.chunks[int(idx)]
            hits.append(
                RetrievedChunkHit(
                    chunk_id=chunk.chunk_id,
                    source_file=chunk.source_file,
                    page_or_section=chunk.page_or_section,
                    text=chunk.text,
                    score=round(score, 4),
                    bm25_score=round(float(bm25_scores[idx]), 4),
                    embed_score=round(float(embed_scores[idx]), 4),
                )
            )
        return hits

    def max_raw_score(self, query: str) -> float:
        """Return the highest hybrid score for query without applying min_score cutoff."""
        hits = self.search(query, top_k=1, apply_min_score=False)
        return hits[0].score if hits else 0.0


def token_overlap_ratio(query: str, texts: Iterable[str]) -> float:
    """Compute fraction of non-trivial query tokens appearing in combined texts."""
    q_toks = {t for t in tokenize_text(query) if len(t) >= 3}
    if not q_toks:
        return 0.0
    doc_toks: set[str] = set()
    for t in texts:
        doc_toks.update(tokenize_text(t))
    return len(q_toks & doc_toks) / len(q_toks)
