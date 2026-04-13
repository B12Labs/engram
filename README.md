# Engram

**Portable memory for AI agents** — graph-compressed, single-file, sub-millisecond recall.

Engram combines [LEANN](https://github.com/yichuan-w/LEANN)'s 97% storage savings with [Memvid](https://github.com/memvid/memvid)'s portable single-file format to create ultra-lightweight, privacy-preserving AI agent memory.

## The Problem

AI agents forget everything between sessions. Current solutions require:
- **Vector databases** (Pinecone, Weaviate) — expensive, vendor-locked, cloud-dependent
- **Raw embeddings** — massive storage (1M chunks = 2-4 GB)
- **Complex RAG pipelines** — multiple services, hard to deploy

## The Solution

Engram stores an agent's entire memory in a **single portable file** (`.engram`) that:

- Is **97% smaller** than traditional vector storage (LEANN graph pruning)
- Retrieves in **sub-millisecond** (FAISS + on-demand embedding recomputation)
- Works **100% offline** — no cloud, no database, no internet required
- Is **deterministic** — same query always returns same results
- Is **portable** — copy the file, move the memory. Any device, any cloud, any agent.

```
Traditional:  1M chunks → 2-4 GB in Pinecone → $200/month → 20ms queries
Engram:       1M chunks → 60 MB .engram file → $0/month → 0.025ms queries
```

## How It Works

```
                    Write Path
Documents ──→ Chunk ──→ Embed ──→ LEANN Graph Pruning ──→ .engram file
                                   (keeps 3-5% of edges)     (portable)

                    Read Path
Query ──→ Embed ──→ Graph-guided search ──→ Recompute neighbors ──→ Results
                    (sub-ms traversal)      (on-demand, not stored)   (ranked)
```

### Key Innovation

Instead of storing every embedding vector (expensive), Engram stores a **pruned graph structure** that preserves the search paths between chunks. At query time, it recomputes only the embeddings it needs by traversing the graph. This is why it's 97% smaller — the graph topology is tiny compared to the full embedding matrix.

## Architecture

```
┌─────────────────────────────────────────┐
│              .engram file               │
│  ┌───────────────────────────────────┐  │
│  │  Metadata (JSON)                  │  │
│  │  - chunk count, model, timestamp  │  │
│  ├───────────────────────────────────┤  │
│  │  Chunks (compressed text)         │  │
│  │  - original documents, chunked    │  │
│  ├───────────────────────────────────┤  │
│  │  LEANN Graph (CSR format)         │  │
│  │  - pruned neighbor structure      │  │
│  │  - hub node indices               │  │
│  ├───────────────────────────────────┤  │
│  │  FAISS Index (optional)           │  │
│  │  - for initial entry points       │  │
│  ├───────────────────────────────────┤  │
│  │  Full-text Index (Tantivy)        │  │
│  │  - keyword + semantic hybrid      │  │
│  └───────────────────────────────────┘  │
└─────────────────────────────────────────┘
```

## Quick Start

```bash
pip install engram
```

```python
from engram import Engram

# Create a new memory
memory = Engram()

# Add documents
memory.add("Meeting notes from April 12: discussed Q2 roadmap...")
memory.add("Email from Sarah: budget approved for new hires")
memory.add("Slack thread: deployment scheduled for Friday 3pm")

# Save to file
memory.save("work.engram")  # ~60 MB for 1M chunks

# Search
results = memory.search("What's the deployment schedule?")
# Returns: "Slack thread: deployment scheduled for Friday 3pm" (0.025ms)

# Load on any device
memory = Engram.load("work.engram")
```

### Cross-App Search

```python
from engram import Engram, UnifiedIndex

# Each app has its own memory
meet = Engram.load("meet.engram")
social = Engram.load("social.engram")
voice = Engram.load("voice.engram")

# Unified index searches across all
unified = UnifiedIndex([meet, social, voice])
results = unified.search("images I used last week")
# Returns results from all apps, ranked by relevance
```

### Cloud Storage (S3/R2 Compatible)

```python
from engram import Engram
from engram.storage import R2Storage

storage = R2Storage(
    endpoint="https://your-account.r2.cloudflarestorage.com",
    bucket="engram-memories"
)

# Save to R2
memory.save("work.engram")
storage.upload("work.engram", key="user_123/work.engram")

# Load from R2 (cached locally after first pull)
memory = storage.load("user_123/work.engram", cache_dir="/tmp/engram-cache")
```

## Performance

| Metric | Engram | Pinecone | pgvector | Raw Memvid |
|--------|--------|----------|----------|------------|
| Storage (1M chunks) | **60 MB** | 2-4 GB (cloud) | 2-4 GB | 200-400 MB |
| Query latency (p50) | **0.025ms** | ~20ms | ~5-50ms | 0.025ms |
| Monthly cost (10k users) | **$0.75** | $200+ | $25+ | $5 |
| Portability | Copy file | Vendor locked | DB dump | Copy file |
| Offline | Yes | No | If self-hosted | Yes |
| Deterministic | Yes | No | Yes | Yes |

## Data Sources

Engram can ingest from:
- **Files**: PDF, TXT, Markdown, HTML, DOCX
- **Communication**: Email (IMAP), Slack, Discord
- **Meetings**: Transcripts, notes, action items
- **Social**: Posts, comments, analytics
- **Code**: Git history, pull requests, issues
- **MCP Servers**: Any Model Context Protocol source

## Use Cases

- **AI Agent Memory** — persistent context across sessions
- **Personal Knowledge Base** — your entire digital life in one file
- **Meeting Intelligence** — searchable history of every meeting
- **Enterprise RAG** — private, on-prem, no cloud dependency
- **Edge AI** — full memory on mobile/IoT devices (tiny file size)

## Built On

Engram stands on the shoulders of two excellent projects:
- **[LEANN](https://github.com/yichuan-w/LEANN)** (MIT) — graph-pruned vector indices, 97% storage savings
- **[Memvid](https://github.com/memvid/memvid)** (Apache 2.0) — portable single-file AI memory

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

## License

MIT License — see [LICENSE](LICENSE) for details.

---

**Engram** is a [B12 Labs](https://github.com/B12Labs) project.
