# Engram Architecture

## Overview

Engram is a hybrid of two technologies:

1. **LEANN** — Low-storage End-to-end vector index that achieves 97% storage savings through graph pruning
2. **Memvid** — Portable single-file memory format with sub-millisecond FAISS retrieval

## File Format (.engram)

An `.engram` file is a single binary container with the following sections:

```
┌────────────────────────────────────────┐
│ Magic: "ENGRAM\x00\x01" (8 bytes)     │
│ Version: u32                           │
├────────────────────────────────────────┤
│ Section: METADATA                      │
│   - chunk_count: u64                   │
│   - embedding_model: string            │
│   - embedding_dim: u32                 │
│   - created_at: ISO8601                │
│   - updated_at: ISO8601                │
│   - source_app: string (optional)      │
├────────────────────────────────────────┤
│ Section: CHUNKS                        │
│   - Compressed text chunks (zstd)      │
│   - Each chunk: id, text, metadata     │
├────────────────────────────────────────┤
│ Section: GRAPH                         │
│   - CSR format (Compressed Sparse Row) │
│   - node_count: u64                    │
│   - edge_count: u64                    │
│   - indptr: [u64]                      │
│   - indices: [u64]                     │
│   - hub_nodes: [u64]                   │
├────────────────────────────────────────┤
│ Section: FAISS_INDEX                   │
│   - Serialized FAISS index             │
│   - Used for initial entry points      │
├────────────────────────────────────────┤
│ Section: FULLTEXT_INDEX                │
│   - Tantivy index (keyword search)     │
│   - Enables hybrid semantic+keyword    │
├────────────────────────────────────────┤
│ Section: WAL (Write-Ahead Log)         │
│   - Pending writes not yet compacted   │
│   - Appended on each write             │
│   - Merged during compaction           │
└────────────────────────────────────────┘
```

## Storage Strategy: LEANN Graph Pruning

Traditional vector databases store every embedding:
- 1M chunks × 768-dim float32 = **3 GB**

LEANN stores a pruned graph instead:
- High-degree preserving pruning removes low-utility edges
- Hub nodes (high connectivity) are preserved — they're critical for search paths
- Result: **~60 MB** for the same 1M chunks (97% reduction)

At query time, Engram:
1. Embeds the query
2. Uses FAISS to find initial entry points
3. Traverses the pruned graph to find neighbors
4. Recomputes embeddings on-demand for comparison
5. Returns top-k results

## Cloud Sync Architecture

```
Cloud Storage (R2/S3)           Local Device
┌──────────────────┐           ┌──────────────────┐
│ user_123/         │           │ cache/            │
│   meet.engram     │◄── sync ─│   meet.engram     │
│   social.engram   │── pull ──│   social.engram   │
│   unified.engram  │           │   unified.engram  │
└──────────────────┘           └──────────────────┘

Write: local first → async push to cloud
Read:  check local cache → miss? pull from cloud → cache → search
Sync:  compare timestamps → only transfer if cloud is newer
```

## Unified Cross-App Search

Each app maintains its own `.engram` file. A lightweight `unified.engram` indexes summaries across all apps:

```python
# Each write to any app also appends to unified
unified.add({
    "type": "meeting_note",
    "source": "meet",
    "ref": "meeting_2026-04-12",
    "summary": "Discussed Q2 roadmap, approved budget",
    "timestamp": "2026-04-12T14:30:00Z"
})
```

Cross-app search hits `unified.engram` first (one file, sub-ms), then drills into the specific app file for full content.

## Compaction

The WAL accumulates writes. Periodically, Engram compacts:
1. Merge WAL entries into the main chunk store
2. Re-embed new chunks
3. Re-prune the LEANN graph
4. Rebuild FAISS entry points
5. Update full-text index
6. Write new `.engram` file atomically

Compaction runs in the background. Reads continue against the existing file during compaction.

## Embedding Models

Engram is model-agnostic. Supported embedding models:
- `facebook/contriever` (default, good general-purpose)
- `text-embedding-3-small` (OpenAI, high quality)
- `Qwen3-Embedding` (open-source, multilingual)
- `sentence-transformers/all-MiniLM-L6-v2` (lightweight)
- Any model via custom adapter

The embedding model is recorded in metadata so the file remains self-describing.
