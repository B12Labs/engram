# Engram Architecture

## Overview

Engram is a hybrid of two technologies:

1. **LEANN** — Low-storage End-to-end vector index that achieves 97% storage savings through graph pruning
2. **Memvid** — Portable single-file memory format with sub-millisecond FAISS retrieval

## File Format (.egm)

An `.egm` file is a single binary container with the following sections:

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
│   meet.egm     │◄── sync ─│   meet.egm     │
│   social.egm   │── pull ──│   social.egm   │
│   unified.egm  │           │   unified.egm  │
└──────────────────┘           └──────────────────┘

Write: local first → async push to cloud
Read:  check local cache → miss? pull from cloud → cache → search
Sync:  compare timestamps → only transfer if cloud is newer
```

## Unified Cross-App Search

Each app maintains its own `.egm` file. A lightweight `unified.egm` indexes summaries across all apps:

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

Cross-app search hits `unified.egm` first (one file, sub-ms), then drills into the specific app file for full content.

## Compaction

The WAL accumulates writes. Periodically, Engram compacts:
1. Merge WAL entries into the main chunk store
2. Re-embed new chunks
3. Re-prune the LEANN graph
4. Rebuild FAISS entry points
5. Update full-text index
6. Write new `.egm` file atomically

Compaction runs in the background. Reads continue against the existing file during compaction.

## Embedding Models

Engram is model-agnostic. Supported embedding models:
- `facebook/contriever` (default, good general-purpose)
- `text-embedding-3-small` (OpenAI, high quality)
- `Qwen3-Embedding` (open-source, multilingual)
- `sentence-transformers/all-MiniLM-L6-v2` (lightweight)
- Any model via custom adapter

The embedding model is recorded in metadata so the file remains self-describing.


## Time-Partitioned Sharding

For agents with years of data, Engram splits each app's memory into time-based shards.

### Manifest File

A tiny JSON file (~1-5 KB) that's always cached. Contains:
- List of all shards per app
- Date range and tier for each shard
- Chunk count and file size
- Pointer to unified cross-app index

### Shard Lifecycle

```
Write → HOT shard (current quarter)
         ↓ (end of quarter)
Compact → WARM shard (last quarter)
         ↓ (end of year)
Merge → Annual shard (COLD)
         ↓ (5+ years)
Archive → Decade shard (ARCHIVE, optional)
```

### Query Routing

```
recall("budget") →
  1. Check manifest (always cached)
  2. Search HOT shard (0.025ms)
  3. Good results? → return
  4. Expand to WARM shards (~130ms pull)
  5. Still not found? → check unified archive
  6. Pull specific COLD shard (~500ms)
  7. Return results with shard metadata
```

### Storage Layout on R2

```
boss-engram/{user_id}/
  manifest.json
  meet/meet.2026-Q2.egm
  meet/meet.2026-Q1.egm
  meet/meet.2025.egm
  social/social.2026-Q2.egm
  unified/unified.2026.egm
  unified/unified.archive.egm
```
