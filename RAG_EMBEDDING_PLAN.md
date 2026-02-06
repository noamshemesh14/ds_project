# RAG Embedding Plan – Academy Q&A Chat

This document defines the embedding pipeline to power the **chat button** with a RAG (Retrieval-Augmented Generation) system over your academy data, using **Pinecone** as the vector store.

---

## 1. Data inventory and roles

| File | Content | Use in RAG |
|------|--------|------------|
| **unified_catalogs_over_years.txt** | Course catalogs over multiple years | General catalog questions, history, what was offered when |
| **unified_attachments.txt** | Annexes: policies, procedures, benefits | Regulations, procedures, benefits, how things work |
| **unified_course_description.txt** | Syllabi, descriptions, prerequisites, credits, exam formats (3 years) | Course content, prerequisites, exam types |
| **students_grade_sheet.csv** | 30k students: course IDs, names, categories, descriptions, grades | Aggregated stats only; **do not embed PII**. Use for “typical grades” or “course difficulty” only if anonymized/summarized |
| **dds_courses_details.csv** | DDS faculty: this semester – times, rooms, instructors, capacity, exam dates | Current DDS schedule, rooms, instructors |
| **all_faculties_courses_details.csv** | All faculties: descriptions, credits, instructors, hours, schedule, rooms | Current offerings, cross-faculty search |

**Recommendation:** Put all files under a single folder, e.g. `data/` or `rag_data/`, so paths are easy to configure.

---

## 2. Recommended stack

| Component | Choice | Notes |
|----------|--------|--------|
| **Vector DB** | Pinecone | Managed, good for hybrid + metadata filter |
| **Embeddings** | OpenAI `text-embedding-3-small` (or `text-embedding-3-large`) | 1536 (small) or 3072 (large) dimensions; same as your existing OpenAI usage |
| **Chunking** | Text: semantic/sentence-aware; CSV: row-based or small row groups | See below |
| **Language** | Hebrew + English | OpenAI embeddings handle both; keep chunk sizes in a range that fits the model (e.g. ≤8k tokens per chunk for safety) |

---

## 3. Parameters summary

Use these as defaults; you can tune later.

| Parameter | Value | Notes |
|-----------|--------|--------|
| **Embedding model** | `text-embedding-3-small` | Or `text-embedding-3-large`; works with OpenAI or llmod.ai (set `EMBEDDING_BASE_URL`) |
| **Dimensions** | `1536` (small) or `3072` (large) | Must match Pinecone index |
| **Chunk size (text)** | `1024` characters | Configurable via `RAG_CHUNK_SIZE` |
| **Chunk overlap (text)** | `0.2` (20% of chunk = 204 chars) | Set `RAG_CHUNK_OVERLAP=0.2` for ratio or e.g. `204` for absolute |
| **CSV chunking** | 1 row = 1 chunk, or merge 2–3 rows into one text | Keeps context (e.g. course + description) |
| **Pinecone metric** | `cosine` | Standard for normalized embeddings |
| **Top-k retrieval** | `5` | Number of chunks returned per query; set `RAG_TOP_K=5` |
| **Upsert batch size** | `100` vectors per request | Pinecone-friendly |

---

## 4. Chunking strategy per source

### 4.1 Text files (unified_*.txt)

- **Method:** Sliding window with overlap.
- **Parameters:** `chunk_size=800`, `overlap=150` (characters).
- **Split:** Prefer splitting on paragraph breaks (`\n\n`) or sentence boundaries; if a “paragraph” is longer than `chunk_size`, split by sentences and then apply the sliding window.
- **Metadata to store:**  
  `source_file`, `source_type` (e.g. `catalog` / `attachments` / `course_description`), `chunk_index`, `year` (if present in content or filename).

### 4.2 CSV files

- **students_grade_sheet.csv:**  
  **Do not embed raw rows** (PII). If you use it at all, use only **pre-aggregated** content, e.g. “Course X: typical grade distribution, N students” in a short text paragraph, then embed that. For the **first phase**, skip this file or add it later as summary-only.
- **dds_courses_details.csv** and **all_faculties_courses_details.csv:**  
  - **Option A:** One chunk per row: concatenate relevant columns (e.g. course_id, course_name, description, credits, instructors, schedule, room, exam_date) into one string.  
  - **Option B:** If a row is very long, group 2–3 rows (e.g. by course_id) into one chunk so “course + description + schedule” stay together.
- **Metadata to store:**  
  `source_file`, `source_type` (e.g. `dds_courses` / `all_faculties`), `course_id`, `faculty` (if available), `semester`/`year` (if available).

---

## 5. Pinecone index configuration

- **Index name:** e.g. `academy-rag` (or per environment: `academy-rag-dev`).
- **Dimensions:** `1536` for `text-embedding-3-small`, or `3072` for `text-embedding-3-large`.
- **Metric:** `cosine`.
- **Cloud and region:** Same as your app (e.g. `gcp-starter` or `aws` in your region).
- **Metadata:** Enable metadata indexing for the fields you will filter on (e.g. `source_type`, `course_id`, `faculty`) so you can restrict retrieval later (e.g. “only course descriptions” or “only DDS”).

Create the index once (script or Pinecone console); the embedding script will only **upsert** vectors.

---

## 6. Step-by-step embedding pipeline

1. **Environment**
   - Create `.env` (or extend existing) with:
     - `OPENAI_API_KEY` (for embeddings).
     - `PINECONE_API_KEY`.
     - `PINECONE_INDEX_NAME=academy-rag` (or your name).
     - Optional: `PINECONE_ENV` or `PINECONE_HOST` if needed by the client.
   - Install: `pinecone-client`, `openai`, `python-dotenv`, and CSV/string dependencies (e.g. `pandas` for CSVs).

2. **Data placement**
   - Put all 6 files in one folder, e.g. `rag_data/`.
   - Config (e.g. in script or `config.py`): list of paths or globs for each source type (txt vs csv).

3. **Load and normalize**
   - **Text:** Read each `.txt` with UTF-8; normalize line endings; optionally strip excessive newlines.
   - **CSV:** Read with `pandas`; for each row (or row group), build one string from chosen columns; handle missing values (e.g. empty string).

4. **Chunk**
   - Text: apply sliding-window chunker with `chunk_size=800`, `overlap=150`; attach `source_file`, `source_type`, `chunk_index`.
   - CSV: one (or 2–3) row(s) per chunk; attach `source_file`, `source_type`, `course_id`, etc.

5. **Embed**
   - Call OpenAI Embeddings API for each chunk (or batched, e.g. 100 chunks per request to respect rate limits).
   - Use the same model you will use in production (e.g. `text-embedding-3-small`).

6. **Upsert to Pinecone**
   - Build vectors: `id` (unique, e.g. `source_file + "_" + chunk_index` or UUID), `values`, `metadata` (only types supported by Pinecone: string, number, boolean, list of strings).
   - Upsert in batches of 100; reuse the same index name from env.

7. **Validation**
   - After upsert, run a few test queries (e.g. “מה תנאי הקבלה לקורס X?” or “exam format”) and check that retrieved chunks are relevant.
   - Optionally: small script that embeds a query and prints top-k IDs and metadata.

8. **Chat integration (later)**
   - In `/api/chat`: embed the user message → query Pinecone (top-k, optional metadata filter) → pass retrieved chunks as context to your LLM → return the model reply. (Out of scope for this “embedding-only” plan.)

---

## 7. Parameters quick reference

```text
# Chunking (text)
chunk_size = 1024
chunk_overlap = 0.2   # 20% of chunk_size (204 chars)

# Retrieval
top_k = 5

# Embedding (OpenAI or llmod.ai via EMBEDDING_BASE_URL)
embedding_model = "text-embedding-3-small"
embedding_dimensions = 1536

# Pinecone (create index in Pinecone console; script only upserts)
index_name = "academy-rag"
metric = "cosine"
batch_size_upsert = 100

# CSV
csv_chunk_mode = "one_row_per_chunk"  # or "group_by_course"
```

---

## 8. Next steps after embedding

1. **RAG retrieval:** Add a function that takes a query string, embeds it, runs Pinecone query, returns top-k chunks + metadata.
2. **Chat endpoint:** Replace the current keyword logic in `/api/chat` with: retrieve context from Pinecone → build a prompt with context + user message → call your LLM → return response.
3. **UI:** The existing “צ'אט” button and `sendChatMessage()` already call `/api/chat`; no UI change needed for a first version, only backend.
4. **Optional:** Add metadata filters in retrieval (e.g. only `source_type=course_description`) and/or separate namespaces per source for A/B testing.

---

## 9. File layout suggestion

```text
ds_project/
  rag_data/                          # You place the 6 files here
    unified_catalogs_over_years.txt
    unified_attachments.txt
    unified_course_description.txt
    students_grade_sheet.csv
    dds_courses_details.csv
    all_faculties_courses_details.csv
  app/
    rag/                              # Optional: RAG module
      embed_and_upsert.py             # Script to run once / periodically
      chunkers.py                    # Text + CSV chunking
      retriever.py                   # Query Pinecone (for chat later)
  RAG_EMBEDDING_PLAN.md              # This file
```

You can run the embedding script from the project root or via `python -m app.rag.embed_and_upsert` after configuring paths and env.

---

## 10. How to run the embedding script

1. **Install dependencies**
   ```bash
   py -m pip install -r requirements.txt
   ```
   (Ensures `openai`, `pinecone-client`, `pandas`, `python-dotenv` are installed.)

2. **Create `rag_data/` and add your 6 files**
   - Place the 3 `.txt` and 3 `.csv` files (or the subset you want) inside `rag_data/`.
   - The script skips missing files and logs "Skip (not found): ...".

3. **Set environment variables** (in `.env`)
   - **Embeddings:** If using **llmod.ai**, set `OPENAI_API_KEY` to your llmod key and `EMBEDDING_BASE_URL` to llmod’s embedding API base URL (OpenAI-compatible). Otherwise use your OpenAI key and omit `EMBEDDING_BASE_URL`.
   - **Pinecone:** Create an index in the [Pinecone console](https://app.pinecone.io) (dimension = 1536 for `text-embedding-3-small`, metric = cosine), then set `PINECONE_API_KEY` and optionally `PINECONE_INDEX_NAME=academy-rag`.
   - Optional: `RAG_DATA_DIR=./rag_data`, `RAG_CHUNK_SIZE=1024`, `RAG_CHUNK_OVERLAP=0.2`, `RAG_TOP_K=5`.

4. **Run**
   ```bash
   py -m app.rag.embed_and_upsert
   ```
   The script creates the Pinecone index if it does not exist, then chunks, embeds, and upserts all data. At the end you can run a few test queries in Pinecone or in your app to validate retrieval.
