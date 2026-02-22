"""
RAG embedding pipeline configuration.
Adjust paths and parameters here; override with env vars where noted.
"""
import os
from pathlib import Path

# ----- Paths -----
# Folder containing the 6 data files (relative to project root or absolute)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RAG_DATA_DIR = Path(os.getenv("RAG_DATA_DIR", str(PROJECT_ROOT / "rag_data")))

# Data files (names only; must sit inside RAG_DATA_DIR)
TEXT_FILES = [
    "unified_catalogs_over_years.txt",
    "unified_attachments.txt",
    "unified_course_description.txt",
]

# ----- Incremental updates (new files only, no re-embedding of old ones) -----
# Put new .txt files in this folder and run:  py -m app.rag.embed_and_upsert --incremental
# All .txt files in RAG_ADDITIONAL_DIR are embedded and upserted to the same Pinecone index.
# Hebrew/UTF-8 text is supported; save files as UTF-8.
RAG_ADDITIONAL_DIR = os.getenv("RAG_ADDITIONAL_DIR", str(PROJECT_ROOT / "rag_data_additional"))
# Optional: set RAG_ADDITIONAL_FILES (comma-separated names) to embed only those .txt files from this folder.
# Example: RAG_ADDITIONAL_FILES="new_doc1.txt,new_doc2.txt"

CSV_FILES = [
    "dds_courses_details.csv",
    "all_faculties_courses_details.csv",
    # "students_grade_sheet.csv",  # Skip by default (PII); use only anonymized summaries
]

# ----- Chunking (text) -----
CHUNK_SIZE = int(os.getenv("RAG_CHUNK_SIZE", "1024"))  # characters
# Overlap: env "0.2" = 20% of chunk_size (204 chars); or set absolute e.g. "204"
_overlap_raw = os.getenv("RAG_CHUNK_OVERLAP", "0.2")
try:
    _ov = float(_overlap_raw)
    CHUNK_OVERLAP = int(CHUNK_SIZE * _ov) if 0 < _ov <= 1 else int(_ov)
except ValueError:
    CHUNK_OVERLAP = int(0.2 * 1024)  # 204

# ----- Retrieval -----
TOP_K = int(os.getenv("RAG_TOP_K", "5"))  # number of chunks to retrieve per query
MIN_SCORE = float(os.getenv("RAG_MIN_SCORE", "0.7"))  # minimum similarity score threshold
MAX_CONTEXT_LENGTH = int(os.getenv("RAG_MAX_CONTEXT_LENGTH", "3000"))  # max characters for context

# ----- Embedding -----
# Optional: for llmod.ai or other OpenAI-compatible embedding API
EMBEDDING_BASE_URL = os.getenv("EMBEDDING_BASE_URL") or os.getenv("OPENAI_BASE_URL") or None
# llmod.ai keys only allow model "RPRTHPB-text-embedding-3-small"; use that when base URL is set
_default_model = "RPRTHPB-text-embedding-3-small" if EMBEDDING_BASE_URL else "text-embedding-3-small"
EMBEDDING_MODEL = os.getenv("RAG_EMBEDDING_MODEL", _default_model)
# Dimensions: 1536 for text-embedding-3-small, 3072 for text-embedding-3-large
EMBEDDING_DIMENSIONS = int(os.getenv("RAG_EMBEDDING_DIMENSIONS", "1536"))

# ----- Pinecone -----
PINECONE_INDEX_NAME = os.getenv("PINECONE_INDEX_NAME", "academy-rag")
PINECONE_METRIC = "cosine"
UPSERT_BATCH_SIZE = int(os.getenv("RAG_UPSERT_BATCH_SIZE", "100"))

# ----- CSV chunking -----
# "one_row_per_chunk" or "group_by_course" (e.g. 2-3 rows per chunk)
CSV_CHUNK_MODE = os.getenv("RAG_CSV_CHUNK_MODE", "one_row_per_chunk")
