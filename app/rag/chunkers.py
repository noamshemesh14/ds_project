"""
Chunking utilities for RAG: text (sliding window) and CSV (row-based).
"""
import re
from pathlib import Path
from typing import Iterator

import pandas as pd

from app.rag.config import CHUNK_OVERLAP, CHUNK_SIZE, CSV_CHUNK_MODE, RAG_DATA_DIR


def chunk_text(
    text: str,
    chunk_size: int = CHUNK_SIZE,
    overlap: int = CHUNK_OVERLAP,
    source_file: str = "",
    source_type: str = "text",
) -> Iterator[tuple[str, dict]]:
    """
    Split text into overlapping chunks. Yields (chunk_text, metadata).
    Prefer splitting on paragraph then sentence boundaries.
    """
    text = text.strip()
    if not text:
        return

    # Split into paragraphs first
    paragraphs = re.split(r"\n\s*\n", text)
    current = []
    current_len = 0
    chunk_index = 0

    def flush():
        nonlocal current, current_len, chunk_index
        if not current:
            return
        chunk = "\n\n".join(current)
        if chunk.strip():
            yield chunk, {
                "source_file": source_file,
                "source_type": source_type,
                "chunk_index": chunk_index,
            }
            chunk_index += 1
        current = []
        current_len = 0

    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        if current_len + len(para) + 2 <= chunk_size:
            current.append(para)
            current_len += len(para) + 2
        else:
            if current:
                yield from flush()
            # If single paragraph is too long, split by sentences
            if len(para) > chunk_size:
                sentences = re.split(r"(?<=[.!?])\s+", para)
                for sent in sentences:
                    if current_len + len(sent) + 1 <= chunk_size:
                        current.append(sent)
                        current_len += len(sent) + 1
                    else:
                        if current:
                            yield from flush()
                        # Very long sentence: hard split
                        for i in range(0, len(sent), chunk_size - overlap):
                            piece = sent[i : i + chunk_size]
                            if piece.strip():
                                yield piece, {
                                    "source_file": source_file,
                                    "source_type": source_type,
                                    "chunk_index": chunk_index,
                                }
                                chunk_index += 1
                        current_len = 0
                        current = []
            else:
                current.append(para)
                current_len += len(para) + 2
    yield from flush()


def load_and_chunk_text_file(filepath: Path, source_type: str) -> Iterator[tuple[str, dict]]:
    """Load a single text file and yield (chunk, metadata)."""
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        text = f.read()
    yield from chunk_text(
        text,
        source_file=filepath.name,
        source_type=source_type,
    )


def csv_row_to_text(row: pd.Series, columns: list[str] | None = None) -> str:
    """Turn one CSV row into a single searchable text (for embedding)."""
    if columns is None:
        columns = [c for c in row.index if row[c] is not None and str(row[c]).strip()]
    parts = []
    for col in columns:
        if col in row.index:
            val = row[col]
            if pd.notna(val) and str(val).strip():
                parts.append(f"{col}: {val}")
    return " | ".join(parts)


def chunk_csv(
    filepath: Path,
    source_type: str,
    text_columns: list[str] | None = None,
    mode: str = CSV_CHUNK_MODE,
) -> Iterator[tuple[str, dict]]:
    """
    Read CSV and yield (chunk_text, metadata) per row (or row group).
    text_columns: which columns to concatenate; None = all.
    """
    df = pd.read_csv(filepath, encoding="utf-8", on_bad_lines="skip")
    if df.empty:
        return

    cols = text_columns or list(df.columns)
    id_col = "course_id" if "course_id" in df.columns else (df.columns[0] if len(df.columns) else None)

    if mode == "one_row_per_chunk":
        for idx, row in df.iterrows():
            text = csv_row_to_text(row, cols)
            if not text.strip():
                continue
            meta = {
                "source_file": filepath.name,
                "source_type": source_type,
            }
            if id_col and id_col in row and pd.notna(row[id_col]):
                meta["course_id"] = str(row[id_col]).strip()
            if "faculty" in df.columns and pd.notna(row.get("faculty")):
                meta["faculty"] = str(row["faculty"]).strip()
            yield text, meta
    else:
        # group_by_course: group consecutive rows with same course_id
        group_col = id_col or df.columns[0]
        for key, group in df.groupby(group_col, sort=False):
            texts = [csv_row_to_text(row, cols) for _, row in group.iterrows()]
            combined = "\n".join(t for t in texts if t.strip())
            if not combined.strip():
                continue
            meta = {
                "source_file": filepath.name,
                "source_type": source_type,
                "course_id": str(key).strip() if pd.notna(key) else "",
            }
            yield combined, meta
