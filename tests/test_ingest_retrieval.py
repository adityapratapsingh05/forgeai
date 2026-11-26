"""Tests for document ingestion, chunking strategies, and hybrid retrieval."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from forgeai.ingest import ingest_corpus
from forgeai.retrieval import HybridRetriever, token_overlap_ratio
from forgeai.schemas import RetrievalConfig


def test_chunking_strategies_and_metadata(tmp_path: Path) -> None:
    md_text = (
        "# Leave Policy\n\n"
        "Full-time shore staff receive 24 days of paid annual leave per year.\n\n"
        "Sick leave is 12 days per calendar year with a medical certificate after 3 days.\n\n"
        "# Travel Allowance\n\n"
        "Daily meal per diem is USD 65 for domestic travel and USD 95 for international travel."
    )
    (tmp_path / "policy.md").write_text(md_text, encoding="utf-8")
    (tmp_path / "empty.txt").write_text("", encoding="utf-8")
    # Non-English UTF-8 doc
    (tmp_path / "notes_intl.txt").write_text("Política de viajes: reembolso máximo 150 EUR.", encoding="utf-8")

    df = pd.DataFrame([{"part_no": "A1", "desc": "Valve", "price": 50}])
    df.to_csv(tmp_path / "parts.csv", index=False)

    for strategy in ("fixed", "paragraph", "heading-aware"):
        cfg = RetrievalConfig(chunk_size=150, overlap=25, strategy=strategy, hybrid_alpha=0.0)
        corpus = ingest_corpus(tmp_path, cfg)
        assert corpus.profile.has_tabular_data is True
        assert "parts.csv" in corpus.tables
        assert len(corpus.chunks) >= 4
        assert all(c.source_file and c.chunk_id and c.page_or_section for c in corpus.chunks)
        assert any("Empty file" in w for w in corpus.profile.warnings)

        retriever = HybridRetriever(corpus.chunks, cfg, llm_client=None)
        hits = retriever.search("annual leave days")
        assert hits
        assert hits[0].source_file == "policy.md"

        oos_hits = retriever.search("quantum entanglement cryptocurrency derivatives", min_score=0.25)
        assert oos_hits == []


def test_token_overlap_ratio() -> None:
    ratio = token_overlap_ratio("annual leave carryover days", ["Staff may carry over 5 annual leave days."])
    assert ratio >= 0.75


def test_hybrid_retrieval_dense_scores_avoid_blas_matmul_errors() -> None:
    from forgeai.schemas import DocumentChunk

    chunks = [
        DocumentChunk(
            chunk_id="leave",
            source_file="leave.md",
            page_or_section="Leave",
            text="Annual leave entitlement is twenty days.",
            doc_type="md",
        ),
        DocumentChunk(
            chunk_id="travel",
            source_file="travel.md",
            page_or_section="Travel",
            text="Travel expenses require receipts.",
            doc_type="md",
        ),
    ]

    class FakeEmbeddingClient:
        def embed(self, texts: list[str]) -> list[list[float]]:
            return [[1.0, 0.0] if "leave" in text.lower() else [0.0, 1.0] for text in texts]

    config = RetrievalConfig(hybrid_alpha=0.5, min_score=0.0)
    with np.errstate(divide="raise", over="raise", invalid="raise"):
        retriever = HybridRetriever(chunks, config, FakeEmbeddingClient())
        hits = retriever.search("annual leave")

    assert hits[0].source_file == "leave.md"
    assert hits[0].embed_score == 1.0
