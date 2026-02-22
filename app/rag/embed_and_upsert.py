"""
One-off (or periodic) script: chunk all RAG data sources, embed with OpenAI, upsert to Pinecone.
Run from project root:
  py -m app.rag.embed_and_upsert
Requires: .env with OPENAI_API_KEY, PINECONE_API_KEY; optional PINECONE_INDEX_NAME, RAG_DATA_DIR.
"""
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

# Load .env first, before any app imports
_project_root = Path(__file__).resolve().parent.parent.parent
_env_file = _project_root / ".env"
if _env_file.exists():
    load_dotenv(dotenv_path=str(_env_file), override=True)
load_dotenv(override=True)  # also from cwd (e.g. when run from ds_project)


def _read_key_from_env_file(key: str) -> str:
    """Read a key from project .env as fallback (handles encoding/path issues)."""
    if not _env_file.exists():
        return ""
    try:
        with open(_env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                if k.strip() == key:
                    return (v.strip() or "").strip("'\"").strip()
    except Exception:
        pass
    return ""


from app.rag.chunkers import chunk_csv, load_and_chunk_text_file
from app.rag.config import (
    CSV_FILES,
    EMBEDDING_BASE_URL,
    EMBEDDING_DIMENSIONS,
    EMBEDDING_MODEL,
    PINECONE_INDEX_NAME,
    RAG_ADDITIONAL_DIR,
    RAG_DATA_DIR,
    TEXT_FILES,
    UPSERT_BATCH_SIZE,
)

OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or _read_key_from_env_file("OPENAI_API_KEY") or "").strip()
PINECONE_API_KEY = (os.getenv("PINECONE_API_KEY") or _read_key_from_env_file("PINECONE_API_KEY") or "").strip()


def _source_type_from_filename(name: str, additional: bool = False) -> str:
    if additional:
        return "additional"
    if "catalog" in name.lower():
        return "catalog"
    if "attachment" in name.lower():
        return "attachments"
    if "course_description" in name.lower():
        return "course_description"
    if "dds_courses" in name.lower():
        return "dds_courses"
    if "all_faculties" in name.lower():
        return "all_faculties"
    return "csv"


def _sanitize_metadata(meta: dict) -> dict:
    """Pinecone allows string, number, boolean, list of strings."""
    out = {}
    for k, v in meta.items():
        if v is None:
            continue
        if isinstance(v, (str, int, float, bool)):
            out[k] = v
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[k] = v
        else:
            out[k] = str(v)
    return out


def get_all_chunks(incremental: bool = False):
    """Yield (text, metadata) for every chunk from configured files.
    If incremental=True, only yield chunks from RAG_ADDITIONAL_DIR (new files only).
    """
    if incremental:
        add_dir = Path(RAG_ADDITIONAL_DIR)
        if not add_dir.exists():
            raise FileNotFoundError(
                f"RAG additional directory not found: {add_dir}\n"
                f"Create it and put your new .txt files there, then run:\n  py -m app.rag.embed_and_upsert --incremental"
            )
        # Optional: explicit list from env RAG_ADDITIONAL_FILES (comma-separated)
        env_files = (os.getenv("RAG_ADDITIONAL_FILES") or "").strip()
        if env_files:
            fnames = [f.strip() for f in env_files.split(",") if f.strip()]
        else:
            fnames = sorted(
                p.name for p in add_dir.glob("*.txt")
                if p.name.lower() != "readme.txt"
            )
        if not fnames:
            raise FileNotFoundError(
                f"No .txt files in {add_dir}. Add your new text files (UTF-8) there and run:\n  py -m app.rag.embed_and_upsert --incremental"
            )
        for fname in fnames:
            path = add_dir / fname
            if not path.is_file():
                print(f"Skip (not found): {path}")
                continue
            stype = _source_type_from_filename(fname, additional=True)
            for chunk_text, meta in load_and_chunk_text_file(path, source_type=stype):
                yield chunk_text, meta
        return

    data_dir = Path(RAG_DATA_DIR)
    if not data_dir.exists():
        raise FileNotFoundError(f"RAG data directory not found: {data_dir}")

    for fname in TEXT_FILES:
        path = data_dir / fname
        if not path.exists():
            print(f"Skip (not found): {path}")
            continue
        stype = _source_type_from_filename(fname)
        for chunk_text, meta in load_and_chunk_text_file(path, source_type=stype):
            yield chunk_text, meta

    for fname in CSV_FILES:
        path = data_dir / fname
        if not path.exists():
            print(f"Skip (not found): {path}")
            continue
        stype = _source_type_from_filename(fname)
        for chunk_text, meta in chunk_csv(path, source_type=stype):
            yield chunk_text, meta


def embed_batch(client, texts: list[str], model: str = EMBEDDING_MODEL):
    """Call OpenAI Embeddings API; return list of vectors."""
    resp = client.embeddings.create(input=texts, model=model)
    return [e.embedding for e in resp.data]


def run(incremental: bool = False):
    if not OPENAI_API_KEY:
        raise ValueError(
            "OPENAI_API_KEY is missing or empty in .env (the saved file on disk has no value after the =).\n"
            "Fix: open .env, put your key after OPENAI_API_KEY= with no space, then save the file (Ctrl+S)."
        )
    if not PINECONE_API_KEY:
        raise ValueError(
            "PINECONE_API_KEY is missing or empty. Add it to .env in the project root, e.g.:\n"
            "  PINECONE_API_KEY=your_pinecone_key"
        )

    from openai import OpenAI
    from pinecone import Pinecone, ServerlessSpec

    client_kw = {"api_key": OPENAI_API_KEY}
    if EMBEDDING_BASE_URL:
        client_kw["base_url"] = EMBEDDING_BASE_URL
    openai_client = OpenAI(**client_kw)

    pc = Pinecone(api_key=PINECONE_API_KEY)
    index_name = PINECONE_INDEX_NAME
    existing = pc.list_indexes().names()
    if index_name not in existing:
        print(f"Creating index {index_name} (dim={EMBEDDING_DIMENSIONS}, metric=cosine)")
        pc.create_index(
            name=index_name,
            dimension=EMBEDDING_DIMENSIONS,
            metric="cosine",
            spec=ServerlessSpec(cloud="aws", region="us-east-1"),
        )
    index = pc.Index(index_name)

    chunks = list(get_all_chunks(incremental=incremental))
    mode = "incremental (new files only)" if incremental else "full"
    print(f"Mode: {mode}. Total chunks to embed: {len(chunks)}")

    total_upserted = 0
    batch_texts = []
    batch_metas = []

    for i, (text, meta) in enumerate(chunks):
        batch_texts.append(text)
        batch_metas.append(_sanitize_metadata(meta))

        if len(batch_texts) >= UPSERT_BATCH_SIZE:
            vectors = embed_batch(openai_client, batch_texts)
            ids = [str(uuid.uuid4()) for _ in range(len(vectors))]
            to_upsert = [
                {"id": vid, "values": vec, "metadata": {**batch_metas[j], "text": batch_texts[j][:1000]}}
                for j, (vid, vec) in enumerate(zip(ids, vectors))
            ]
            # Pinecone metadata values must be <= 40KB; keep stored "text" short for display
            index.upsert(vectors=to_upsert)
            total_upserted += len(to_upsert)
            print(f"Upserted batch: {total_upserted} / {len(chunks)}")
            batch_texts = []
            batch_metas = []

    if batch_texts:
        vectors = embed_batch(openai_client, batch_texts)
        ids = [str(uuid.uuid4()) for _ in range(len(vectors))]
        to_upsert = [
            {"id": vid, "values": vec, "metadata": {**batch_metas[j], "text": batch_texts[j][:1000]}}
            for j, (vid, vec) in enumerate(zip(ids, vectors))
        ]
        index.upsert(vectors=to_upsert)
        total_upserted += len(to_upsert)

    print(f"Done. Total vectors in index: {total_upserted}")


if __name__ == "__main__":
    import sys
    incremental = "--incremental" in sys.argv or (os.getenv("RAG_INCREMENTAL", "").strip().lower() in ("1", "true", "yes"))
    run(incremental=incremental)
