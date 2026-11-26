"""Document ingestion, multi-strategy chunking, and folder profiling."""

from __future__ import annotations

import hashlib
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import pandas as pd
from pypdf import PdfReader

from forgeai.schemas import (
    CSVTableProfile,
    DocProfile,
    DocumentChunk,
    FileSummary,
    RetrievalConfig,
)

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".docx"}

_STOPWORDS = frozenset(
    {
        "the", "and", "for", "that", "with", "this", "from", "are", "was", "were",
        "will", "have", "has", "had", "not", "but", "can", "all", "any", "per",
        "use", "used", "using", "into", "such", "than", "then", "when", "where",
        "which", "who", "what", "how", "why", "may", "must", "shall", "should",
        "their", "they", "them", "its", "our", "your", "you", "one", "two", "also",
        "each", "other", "more", "most", "only", "over", "under", "within", "between",
        "been", "being", "about", "after", "before", "during", "above", "below",
    }
)


@dataclass
class LoadedDocument:
    """Intermediate representation of a loaded file before chunking."""

    filename: str
    doc_type: str
    size_bytes: int
    pages: list[tuple[str, str]]  # (page_or_section_label, text)
    title: str = ""
    headings: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    dataframe: pd.DataFrame | None = None


@dataclass
class IngestedCorpus:
    """Loaded and chunked corpus plus structured CSV tables and profile."""

    chunks: list[DocumentChunk]
    tables: dict[str, pd.DataFrame]
    profile: DocProfile


def _read_text_safe(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return path.read_text(encoding="utf-8", errors="replace")


def _extract_docx_text(path: Path) -> str:
    """Extract plain text from a .docx archive without extra dependencies."""
    with zipfile.ZipFile(path, "r") as zf:
        if "word/document.xml" not in zf.namelist():
            return ""
        xml_bytes = zf.read("word/document.xml")
    root = ET.fromstring(xml_bytes)
    paragraphs: list[str] = []
    for elem in root.iter():
        if elem.tag.endswith("}p"):
            texts = [t.text for t in elem.iter() if t.tag.endswith("}t") and t.text]
            line = "".join(texts).strip()
            if line:
                paragraphs.append(line)
    return "\n\n".join(paragraphs)


def _extract_headings_and_title(text: str, filename: str) -> tuple[str, list[str]]:
    headings: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            h = stripped.lstrip("#").strip()
            if h:
                headings.append(h)
        elif (
            len(stripped) <= 90
            and (
                re.match(r"^(?:SECTION|CHAPTER|ARTICLE)\s+\w+", stripped, re.I)
                or re.match(r"^\d+(?:\.\d+)*[.)]\s+[A-Z]", stripped)
                or (stripped.isupper() and len(stripped.split()) >= 2)
            )
        ):
            headings.append(stripped)
    title = headings[0] if headings else Path(filename).stem.replace("_", " ").title()
    return title, headings[:25]


def _load_single_file(path: Path) -> LoadedDocument | None:
    ext = path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        return None
    size_bytes = path.stat().st_size
    filename = path.name
    warnings: list[str] = []

    if size_bytes == 0:
        warnings.append(f"Empty file (0 bytes): {filename}")
        return LoadedDocument(
            filename=filename,
            doc_type=ext.lstrip("."),
            size_bytes=0,
            pages=[],
            title=Path(filename).stem,
            warnings=warnings,
        )

    if ext == ".pdf":
        pages: list[tuple[str, str]] = []
        all_text_parts: list[str] = []
        try:
            reader = PdfReader(str(path))
            empty_pages = 0
            for idx, page in enumerate(reader.pages, start=1):
                txt = (page.extract_text() or "").strip()
                if not txt:
                    empty_pages += 1
                else:
                    pages.append((f"page-{idx}", txt))
                    all_text_parts.append(txt)
            if not pages:
                warnings.append(
                    f"Scanned or empty PDF (0 extractable text pages out of {len(reader.pages)}): {filename}"
                )
            elif empty_pages > 0:
                warnings.append(
                    f"PDF {filename} has {empty_pages}/{len(reader.pages)} pages with no extractable text."
                )
        except Exception as exc:
            warnings.append(f"Failed to parse PDF {filename}: {exc}")
            pages = []
        joined = "\n".join(all_text_parts)
        title, headings = _extract_headings_and_title(joined, filename)
        return LoadedDocument(
            filename=filename,
            doc_type="pdf",
            size_bytes=size_bytes,
            pages=pages,
            title=title,
            headings=headings,
            warnings=warnings,
        )

    if ext in {".txt", ".md"}:
        text = _read_text_safe(path).strip()
        if not text:
            warnings.append(f"Whitespace-only file: {filename}")
            return LoadedDocument(
                filename=filename,
                doc_type=ext.lstrip("."),
                size_bytes=size_bytes,
                pages=[],
                title=Path(filename).stem,
                warnings=warnings,
            )
        title, headings = _extract_headings_and_title(text, filename)
        return LoadedDocument(
            filename=filename,
            doc_type=ext.lstrip("."),
            size_bytes=size_bytes,
            pages=[("section-1", text)],
            title=title,
            headings=headings,
            warnings=warnings,
        )

    if ext == ".docx":
        try:
            text = _extract_docx_text(path).strip()
        except Exception as exc:
            warnings.append(f"Failed to parse DOCX {filename}: {exc}")
            text = ""
        if not text:
            warnings.append(f"DOCX has no extractable text: {filename}")
            return LoadedDocument(
                filename=filename,
                doc_type="docx",
                size_bytes=size_bytes,
                pages=[],
                title=Path(filename).stem,
                warnings=warnings,
            )
        title, headings = _extract_headings_and_title(text, filename)
        return LoadedDocument(
            filename=filename,
            doc_type="docx",
            size_bytes=size_bytes,
            pages=[("section-1", text)],
            title=title,
            headings=headings,
            warnings=warnings,
        )

    if ext == ".csv":
        try:
            df = pd.read_csv(path)
        except Exception as exc:
            warnings.append(f"Failed to parse CSV {filename}: {exc}")
            return LoadedDocument(
                filename=filename,
                doc_type="csv",
                size_bytes=size_bytes,
                pages=[],
                title=Path(filename).stem,
                warnings=warnings,
            )
        if df.empty:
            warnings.append(f"CSV {filename} has 0 rows.")
        cols = [str(c) for c in df.columns]
        row_lines: list[str] = []
        for idx, row in df.iterrows():
            pairs = ", ".join(f"{c}: {row[c]}" for c in df.columns)
            row_lines.append(f"Row {int(idx) + 1} | {pairs}")
        text = f"Table {filename} (columns: {', '.join(cols)})\n" + "\n".join(row_lines)
        return LoadedDocument(
            filename=filename,
            doc_type="csv",
            size_bytes=size_bytes,
            pages=[("table", text)],
            title=f"CSV Table: {filename}",
            headings=cols,
            warnings=warnings,
            dataframe=df,
        )

    return None


def _chunk_fixed(text: str, chunk_size: int, overlap: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= chunk_size:
        return [text]
    chunks: list[str] = []
    start = 0
    step = max(1, chunk_size - overlap)
    while start < len(text):
        end = min(len(text), start + chunk_size)
        if end < len(text):
            # Snap backward to whitespace to avoid splitting words mid-token.
            ws = text.rfind(" ", start + max(1, chunk_size // 2), end)
            if ws > start:
                end = ws
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
        # Align next start to word boundary if inside a word.
        if start > 0 and start < len(text) and not text[start - 1].isspace():
            next_ws = text.find(" ", start)
            if next_ws != -1 and next_ws < start + 40:
                start = next_ws + 1
    return chunks


def _chunk_paragraph(text: str, chunk_size: int, overlap: int) -> list[str]:
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return []
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(para) > chunk_size:
            if current:
                chunks.append(current.strip())
                current = ""
            chunks.extend(_chunk_fixed(para, chunk_size, overlap))
            continue
        candidate = f"{current}\n\n{para}".strip() if current else para
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current.strip())
                tail = current[-overlap:].strip() if overlap > 0 else ""
                current = f"{tail}\n\n{para}".strip() if tail and len(tail) + len(para) + 2 <= chunk_size else para
            else:
                current = para
    if current.strip():
        chunks.append(current.strip())
    return chunks


def _split_by_headings(text: str, default_section: str) -> list[tuple[str, str]]:
    lines = text.splitlines()
    sections: list[tuple[str, str]] = []
    cur_heading = default_section
    buf: list[str] = []

    heading_re = re.compile(
        r"^(?:#{1,6}\s+.+|(?:SECTION|CHAPTER|ARTICLE)\s+\w+.*|\d+(?:\.\d+)*[.)]\s+[A-Z].+)$",
        re.IGNORECASE,
    )

    for line in lines:
        stripped = line.strip()
        if stripped and (stripped.startswith("#") or heading_re.match(stripped)) and len(stripped) <= 100:
            if buf:
                body = "\n".join(buf).strip()
                if body:
                    sections.append((cur_heading, body))
                buf = []
            cur_heading = stripped.lstrip("#").strip()
            buf.append(stripped)
        else:
            buf.append(line)

    if buf:
        body = "\n".join(buf).strip()
        if body:
            sections.append((cur_heading, body))
    return sections or [(default_section, text.strip())]


def chunk_loaded_document(
    doc: LoadedDocument,
    chunk_size: int = 600,
    overlap: int = 80,
    strategy: Literal["fixed", "paragraph", "heading-aware"] = "heading-aware",
) -> list[DocumentChunk]:
    """Split a LoadedDocument into DocumentChunks with full provenance metadata."""
    chunks: list[DocumentChunk] = []
    counter = 0

    if doc.doc_type == "csv" and doc.dataframe is not None:
        df = doc.dataframe
        cols = ", ".join(str(c) for c in df.columns)
        header = f"Table {doc.filename} (columns: {cols})"
        cur_lines: list[str] = [header]
        cur_len = len(header)
        row_start = 1
        for idx, row in df.iterrows():
            row_num = int(idx) + 1
            row_str = f"Row {row_num} | " + ", ".join(f"{c}: {row[c]}" for c in df.columns)
            if len(cur_lines) > 1 and cur_len + len(row_str) + 1 > chunk_size:
                counter += 1
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{doc.filename}::c{counter}",
                        source_file=doc.filename,
                        page_or_section=f"rows-{row_start}-{row_num - 1}",
                        text="\n".join(cur_lines),
                        doc_type="csv",
                        metadata={"row_start": row_start, "row_end": row_num - 1},
                    )
                )
                cur_lines = [header, row_str]
                cur_len = len(header) + len(row_str) + 1
                row_start = row_num
            else:
                cur_lines.append(row_str)
                cur_len += len(row_str) + 1
        if len(cur_lines) > 1:
            counter += 1
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{doc.filename}::c{counter}",
                    source_file=doc.filename,
                    page_or_section=f"rows-{row_start}-{len(df)}",
                    text="\n".join(cur_lines),
                    doc_type="csv",
                    metadata={"row_start": row_start, "row_end": len(df)},
                )
            )
        return chunks

    for page_label, page_text in doc.pages:
        if strategy == "heading-aware":
            sub_sections = _split_by_headings(page_text, page_label)
            for sec_label, sec_text in sub_sections:
                pieces = _chunk_paragraph(sec_text, chunk_size, overlap)
                for piece in pieces:
                    counter += 1
                    label = f"{page_label} | {sec_label}" if page_label != sec_label else sec_label
                    chunks.append(
                        DocumentChunk(
                            chunk_id=f"{doc.filename}::c{counter}",
                            source_file=doc.filename,
                            page_or_section=label[:120],
                            text=piece,
                            doc_type=doc.doc_type,
                        )
                    )
        elif strategy == "paragraph":
            for piece in _chunk_paragraph(page_text, chunk_size, overlap):
                counter += 1
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{doc.filename}::c{counter}",
                        source_file=doc.filename,
                        page_or_section=page_label,
                        text=piece,
                        doc_type=doc.doc_type,
                    )
                )
        else:
            for piece in _chunk_fixed(page_text, chunk_size, overlap):
                counter += 1
                chunks.append(
                    DocumentChunk(
                        chunk_id=f"{doc.filename}::c{counter}",
                        source_file=doc.filename,
                        page_or_section=page_label,
                        text=piece,
                        doc_type=doc.doc_type,
                    )
                )
    return chunks


def _compute_doc_hash(files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(p.name.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest()[:16]


def load_documents(docs_dir: Path) -> tuple[list[LoadedDocument], DocProfile]:
    """Load all supported files in docs_dir recursively and build a DocProfile."""
    docs_path = Path(docs_dir)
    if not docs_path.exists() or not docs_path.is_dir():
        raise FileNotFoundError(f"Documents folder does not exist: {docs_path}")

    candidate_files = sorted(
        p
        for p in docs_path.rglob("*")
        if p.is_file() and not p.name.startswith(".") and p.suffix.lower() in SUPPORTED_EXTENSIONS
    )

    loaded: list[LoadedDocument] = []
    file_summaries: list[FileSummary] = []
    csv_tables: list[CSVTableProfile] = []
    all_warnings: list[str] = []
    word_counts: Counter[str] = Counter()

    if not candidate_files:
        all_warnings.append(
            f"No supported documents ({', '.join(sorted(SUPPORTED_EXTENSIONS))}) found in {docs_path}."
        )

    for file_path in candidate_files:
        doc = _load_single_file(file_path)
        if doc is None:
            continue
        loaded.append(doc)
        all_warnings.extend(doc.warnings)
        joined = "\n".join(txt for _, txt in doc.pages)
        tokens = re.findall(r"[A-Za-z0-9\u00C0-\u024F]{3,}", joined.lower())
        for tok in tokens:
            if tok not in _STOPWORDS and not tok.isdigit():
                word_counts[tok] += 1

        file_summaries.append(
            FileSummary(
                filename=doc.filename,
                size_bytes=doc.size_bytes,
                doc_type=doc.doc_type,
                title=doc.title,
                headings=doc.headings,
                word_count=len(tokens),
                warnings=doc.warnings,
            )
        )
        if doc.dataframe is not None:
            sample = doc.dataframe.head(3).fillna("").to_dict(orient="records")
            csv_tables.append(
                CSVTableProfile(
                    filename=doc.filename,
                    row_count=int(len(doc.dataframe)),
                    columns=[str(c) for c in doc.dataframe.columns],
                    sample_rows=sample,
                )
            )

    doc_types = sorted({fs.doc_type for fs in file_summaries})
    profile = DocProfile(
        docs_dir=str(docs_path),
        file_count=len(file_summaries),
        files=file_summaries,
        total_bytes=sum(fs.size_bytes for fs in file_summaries),
        doc_types=doc_types,
        topic_keywords=[w for w, _ in word_counts.most_common(25)],
        has_tabular_data=len(csv_tables) > 0,
        csv_tables=csv_tables,
        warnings=all_warnings,
        doc_hash=_compute_doc_hash(candidate_files),
    )
    return loaded, profile


def ingest_corpus(
    docs_dir: Path,
    retrieval_config: RetrievalConfig | None = None,
) -> IngestedCorpus:
    """Load documents, build profile, extract CSV tables, and chunk according to config."""
    cfg = retrieval_config or RetrievalConfig()
    loaded, profile = load_documents(docs_dir)
    all_chunks: list[DocumentChunk] = []
    tables: dict[str, pd.DataFrame] = {}

    for doc in loaded:
        if doc.dataframe is not None:
            tables[doc.filename] = doc.dataframe
        doc_chunks = chunk_loaded_document(
            doc,
            chunk_size=cfg.chunk_size,
            overlap=cfg.overlap,
            strategy=cfg.strategy,
        )
        all_chunks.extend(doc_chunks)

    for warn in profile.warnings:
        logger.warning("Ingest warning: %s", warn)

    return IngestedCorpus(chunks=all_chunks, tables=tables, profile=profile)
