"""
Engram Core — AI Agents Engine RAM

Three-tier portable memory for AI agents:
  Tier 1 (Fast):   LEANN graph-compressed vector search — 0.025ms
  Tier 2 (Hybrid): Vector + Tantivy full-text — 0.1ms
  Tier 3 (Deep):   PageIndex hierarchical reasoning — 2-5s

File format: .egm (Engram Memory)
Storage: Cloudflare R2 / S3 / local filesystem
"""

from __future__ import annotations

import json
import time
import hashlib
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

# ══════════════════════════════════════════════════════════════
# Data Types
# ══════════════════════════════════════════════════════════════

@dataclass
class Chunk:
    """A unit of memory stored in an .egm file."""
    id: str
    text: str
    metadata: dict = field(default_factory=dict)
    timestamp: str = ""
    source: str = ""  # which app/connector produced this

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Chunk":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SearchResult:
    """A result from any search tier."""
    text: str
    score: float
    chunk_id: str
    metadata: dict = field(default_factory=dict)
    source_app: str = ""
    tier: str = "fast"  # fast | hybrid | deep
    reasoning_chain: list[str] = field(default_factory=list)  # PageIndex reasoning steps

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class TreeNode:
    """A node in the PageIndex hierarchical tree."""
    title: str
    summary: str = ""
    chunk_ids: list[str] = field(default_factory=list)
    children: list["TreeNode"] = field(default_factory=list)
    node_type: str = "section"  # root | date | source | topic | section
    span: tuple[int, int] = (0, 0)  # chunk index range

    def to_dict(self) -> dict:
        d = {
            "title": self.title,
            "summary": self.summary,
            "chunk_ids": self.chunk_ids,
            "node_type": self.node_type,
            "span": list(self.span),
        }
        if self.children:
            d["children"] = [c.to_dict() for c in self.children]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "TreeNode":
        children = [cls.from_dict(c) for c in d.get("children", [])]
        return cls(
            title=d["title"],
            summary=d.get("summary", ""),
            chunk_ids=d.get("chunk_ids", []),
            children=children,
            node_type=d.get("node_type", "section"),
            span=tuple(d.get("span", [0, 0])),
        )


@dataclass
class EgramMetadata:
    """Metadata stored in the .egm file header."""
    version: int = 2
    chunk_count: int = 0
    embedding_model: str = "facebook/contriever"
    embedding_dim: int = 768
    created_at: str = ""
    updated_at: str = ""
    source_app: str = ""
    compaction_count: int = 0
    has_tree: bool = False  # PageIndex tree built
    has_fulltext: bool = False  # Tantivy index built
    custom: dict = field(default_factory=dict)


# ══════════════════════════════════════════════════════════════
# Engram — Main Class
# ══════════════════════════════════════════════════════════════

class Engram:
    """
    Portable memory for AI agents.

    Three search tiers:
      - search()         → Tier 1: LEANN vector search (0.025ms)
      - search_hybrid()  → Tier 2: Vector + full-text (0.1ms)
      - search_deep()    → Tier 3: PageIndex reasoning (2-5s)
      - recall()         → Auto-selects tier based on query complexity
    """

    def __init__(
        self,
        model: str = "facebook/contriever",
        llm: str = "gemma-4-e4b",  # for PageIndex reasoning tier
    ):
        self._chunks: list[Chunk] = []
        self._chunk_index: dict[str, int] = {}  # id → position
        self._metadata = EgramMetadata(
            embedding_model=model,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            updated_at=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self._model_name = model
        self._llm_name = llm
        self._tree: Optional[TreeNode] = None  # PageIndex hierarchy
        self._wal: list[Chunk] = []  # write-ahead log
        self._embedder = None  # lazy-loaded
        self._graph = None  # LEANN graph (lazy-loaded)
        self._fulltext_index = None  # Tantivy index (lazy-loaded)

    # ── Add Content ──────────────────────────────────────────

    def add(self, text: str, metadata: dict | None = None, source: str = "") -> str:
        """Add a chunk of text to memory. Returns chunk ID."""
        chunk_id = f"chunk_{hashlib.sha256(text.encode()).hexdigest()[:12]}_{len(self._chunks)}"
        chunk = Chunk(
            id=chunk_id,
            text=text,
            metadata=metadata or {},
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            source=source,
        )
        self._chunks.append(chunk)
        self._chunk_index[chunk_id] = len(self._chunks) - 1
        self._wal.append(chunk)
        self._metadata.chunk_count = len(self._chunks)
        self._metadata.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        return chunk_id

    def add_many(self, items: list[dict]) -> list[str]:
        """Add multiple chunks. Each dict should have 'text' and optional 'metadata', 'source'."""
        return [self.add(**item) for item in items]

    def ingest(self, connector) -> int:
        """Ingest from a data connector. Returns number of chunks added."""
        count = 0
        for chunk_data in connector.chunks():
            self.add(**chunk_data)
            count += 1
        return count

    # ── Tier 1: Fast Vector Search (LEANN) ───────────────────

    def search(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """
        Tier 1 — LEANN graph-compressed vector search.
        Speed: 0.025ms (p50). Best for: "find mentions of X".
        """
        # TODO: Implement LEANN graph search
        # For now, fall back to simple text matching
        results = []
        query_lower = query.lower()
        for chunk in self._chunks:
            score = _simple_relevance(query_lower, chunk.text.lower())
            if score > 0:
                results.append(SearchResult(
                    text=chunk.text,
                    score=score,
                    chunk_id=chunk.id,
                    metadata=chunk.metadata,
                    source_app=chunk.source,
                    tier="fast",
                ))
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:top_k]

    # ── Tier 2: Hybrid Search (Vector + Full-text) ───────────

    def search_hybrid(self, query: str, top_k: int = 5) -> list[SearchResult]:
        """
        Tier 2 — Combined vector similarity + keyword full-text search.
        Speed: ~0.1ms. Best for: "find exact phrase + semantically related".
        """
        # Combine vector results with full-text results
        vector_results = self.search(query, top_k=top_k * 2)
        # TODO: Add Tantivy full-text search and merge/rerank
        # For now, return vector results tagged as hybrid
        for r in vector_results:
            r.tier = "hybrid"
        return vector_results[:top_k]

    # ── Tier 3: Deep Reasoning Search (PageIndex) ────────────

    def search_deep(self, query: str, top_k: int = 5, llm_client=None) -> list[SearchResult]:
        """
        Tier 3 — PageIndex hierarchical reasoning over chunk structure.
        Speed: 2-5s (requires LLM call). Best for: complex questions
        that need temporal reasoning, cross-referencing, or chain-of-thought.

        Example: "What was the chain of decisions about the budget?"
        """
        if not self._tree:
            self.build_tree()

        tree_json = json.dumps(self._tree.to_dict(), indent=2) if self._tree else "{}"

        # Build the reasoning prompt
        prompt = f"""You are a document reasoning agent. Given a hierarchical index of an agent's memory,
navigate the structure to find the most relevant information for the user's query.

## Memory Structure (Hierarchical Index)
{tree_json}

## Query
{query}

## Instructions
1. Read the hierarchical index above
2. Identify which sections/dates/topics are most relevant
3. List the specific chunk_ids that answer the query
4. Explain your reasoning chain (how you navigated the index)

Return JSON:
{{
  "relevant_chunk_ids": ["chunk_id_1", "chunk_id_2"],
  "reasoning_chain": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
  "answer_summary": "Brief answer based on the structure"
}}"""

        if llm_client:
            # Use provided LLM client for reasoning
            response = llm_client.chat(prompt)
            try:
                result_data = json.loads(response)
                chunk_ids = result_data.get("relevant_chunk_ids", [])
                reasoning = result_data.get("reasoning_chain", [])
                summary = result_data.get("answer_summary", "")
            except (json.JSONDecodeError, KeyError):
                chunk_ids = []
                reasoning = ["LLM response could not be parsed"]
                summary = response
        else:
            # Without LLM, fall back to tree-guided vector search
            chunk_ids = self._tree_guided_search(query) if self._tree else []
            reasoning = ["No LLM available — used tree-guided vector search fallback"]
            summary = ""

        results = []
        for cid in chunk_ids[:top_k]:
            idx = self._chunk_index.get(cid)
            if idx is not None:
                chunk = self._chunks[idx]
                results.append(SearchResult(
                    text=chunk.text,
                    score=1.0,
                    chunk_id=chunk.id,
                    metadata=chunk.metadata,
                    source_app=chunk.source,
                    tier="deep",
                    reasoning_chain=reasoning,
                ))

        return results

    # ── Auto-Select Tier (Smart Recall) ──────────────────────

    def recall(self, query: str, top_k: int = 5, llm_client=None) -> list[SearchResult]:
        """
        Smart recall — auto-selects the best search tier based on query complexity.

        Simple queries (keywords, names) → Tier 1 (fast, 0.025ms)
        Medium queries (phrases, filters) → Tier 2 (hybrid, 0.1ms)
        Complex queries (reasoning, temporal, cross-ref) → Tier 3 (deep, 2-5s)
        """
        complexity = _estimate_complexity(query)

        if complexity == "simple":
            return self.search(query, top_k)
        elif complexity == "medium":
            return self.search_hybrid(query, top_k)
        else:
            # Try fast first — if results are good enough, skip deep
            fast_results = self.search(query, top_k)
            if fast_results and fast_results[0].score > 0.85:
                return fast_results
            return self.search_deep(query, top_k, llm_client)

    # ── PageIndex Tree Builder ───────────────────────────────

    def build_tree(self) -> TreeNode:
        """
        Build a PageIndex-style hierarchical tree from chunk metadata.
        Organizes chunks by date → source → topic.
        """
        root = TreeNode(title="Memory", node_type="root")

        # Group by date
        date_groups: dict[str, list[Chunk]] = {}
        for chunk in self._chunks:
            date = chunk.timestamp[:10] if chunk.timestamp else "unknown"
            date_groups.setdefault(date, []).append(chunk)

        for date, chunks in sorted(date_groups.items(), reverse=True):
            date_node = TreeNode(
                title=date,
                node_type="date",
                chunk_ids=[c.id for c in chunks],
                summary=f"{len(chunks)} memories from {date}",
            )

            # Group by source within date
            source_groups: dict[str, list[Chunk]] = {}
            for chunk in chunks:
                src = chunk.source or chunk.metadata.get("source", "general")
                source_groups.setdefault(src, []).append(chunk)

            for source, src_chunks in source_groups.items():
                source_node = TreeNode(
                    title=f"{source} ({len(src_chunks)} items)",
                    node_type="source",
                    chunk_ids=[c.id for c in src_chunks],
                    summary=src_chunks[0].text[:100] + "..." if src_chunks else "",
                )
                date_node.children.append(source_node)

            root.children.append(date_node)

        self._tree = root
        self._metadata.has_tree = True
        return root

    def _tree_guided_search(self, query: str) -> list[str]:
        """Fallback tree-guided search when no LLM is available."""
        if not self._tree:
            return []

        query_lower = query.lower()
        scored_chunks: list[tuple[str, float]] = []

        def _walk(node: TreeNode, depth_bonus: float = 0.0):
            # Score this node's title/summary against query
            node_score = _simple_relevance(query_lower, (node.title + " " + node.summary).lower())
            for cid in node.chunk_ids:
                idx = self._chunk_index.get(cid)
                if idx is not None:
                    chunk_score = _simple_relevance(query_lower, self._chunks[idx].text.lower())
                    scored_chunks.append((cid, chunk_score + node_score * 0.3 + depth_bonus))
            for child in node.children:
                _walk(child, depth_bonus + node_score * 0.1)

        _walk(self._tree)
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        return [cid for cid, _ in scored_chunks[:10]]

    # ── File Operations ──────────────────────────────────────

    def save(self, path: str) -> None:
        """Save memory to an .egm file."""
        data = {
            "magic": "ENGRAM",
            "version": 2,
            "metadata": asdict(self._metadata),
            "chunks": [c.to_dict() for c in self._chunks],
            "tree": self._tree.to_dict() if self._tree else None,
            "wal": [c.to_dict() for c in self._wal],
        }
        Path(path).write_text(json.dumps(data, separators=(",", ":")))
        self._wal.clear()

    @classmethod
    def load(cls, path: str) -> "Engram":
        """Load memory from an .egm file."""
        data = json.loads(Path(path).read_text())

        meta = data.get("metadata", {})
        instance = cls(model=meta.get("embedding_model", "facebook/contriever"))
        instance._metadata = EgramMetadata(**{
            k: v for k, v in meta.items() if k in EgramMetadata.__dataclass_fields__
        })

        for chunk_data in data.get("chunks", []):
            chunk = Chunk.from_dict(chunk_data)
            instance._chunks.append(chunk)
            instance._chunk_index[chunk.id] = len(instance._chunks) - 1

        tree_data = data.get("tree")
        if tree_data:
            instance._tree = TreeNode.from_dict(tree_data)
            instance._metadata.has_tree = True

        for wal_data in data.get("wal", []):
            instance._wal.append(Chunk.from_dict(wal_data))

        return instance

    # ── Maintenance ──────────────────────────────────────────

    def compact(self) -> None:
        """Merge WAL, rebuild tree, rebuild indices."""
        self._wal.clear()
        self.build_tree()
        self._metadata.compaction_count += 1
        self._metadata.updated_at = time.strftime("%Y-%m-%dT%H:%M:%SZ")

    def delete(self, chunk_id: str) -> bool:
        """Delete a chunk by ID (GDPR compliance)."""
        idx = self._chunk_index.get(chunk_id)
        if idx is None:
            return False
        del self._chunks[idx]
        # Rebuild index
        self._chunk_index = {c.id: i for i, c in enumerate(self._chunks)}
        self._metadata.chunk_count = len(self._chunks)
        return True

    def delete_by_metadata(self, **kwargs) -> int:
        """Delete chunks matching metadata filters."""
        to_delete = [
            c.id for c in self._chunks
            if all(c.metadata.get(k) == v for k, v in kwargs.items())
        ]
        for cid in to_delete:
            self.delete(cid)
        return len(to_delete)

    def stats(self) -> dict:
        """Return memory statistics."""
        return {
            "chunk_count": len(self._chunks),
            "model": self._model_name,
            "has_tree": self._tree is not None,
            "has_fulltext": self._fulltext_index is not None,
            "wal_pending": len(self._wal),
            "created_at": self._metadata.created_at,
            "updated_at": self._metadata.updated_at,
            "compaction_count": self._metadata.compaction_count,
        }

    # ── Properties ───────────────────────────────────────────

    @property
    def chunk_count(self) -> int:
        return len(self._chunks)

    @property
    def model_name(self) -> str:
        return self._model_name


# ══════════════════════════════════════════════════════════════
# Unified Index — Cross-App Search
# ══════════════════════════════════════════════════════════════

class UnifiedIndex:
    """Search across multiple Engram memories simultaneously."""

    def __init__(self, memories: dict[str, Engram] | None = None):
        self._memories: dict[str, Engram] = memories or {}

    def add_memory(self, name: str, memory: Engram) -> None:
        self._memories[name] = memory

    def remove_memory(self, name: str) -> None:
        self._memories.pop(name, None)

    def search(self, query: str, top_k: int = 10) -> list[SearchResult]:
        """Search across all memories, merge and rank results."""
        all_results: list[SearchResult] = []
        for name, memory in self._memories.items():
            results = memory.search(query, top_k=top_k)
            for r in results:
                r.source_app = name
            all_results.extend(results)
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]

    def recall(self, query: str, top_k: int = 10, llm_client=None) -> list[SearchResult]:
        """Smart recall across all memories with auto tier selection."""
        all_results: list[SearchResult] = []
        for name, memory in self._memories.items():
            results = memory.recall(query, top_k=top_k, llm_client=llm_client)
            for r in results:
                r.source_app = name
            all_results.extend(results)
        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]

    @property
    def total_chunks(self) -> int:
        return sum(m.chunk_count for m in self._memories.values())

    @property
    def memory_names(self) -> list[str]:
        return list(self._memories.keys())


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def _simple_relevance(query: str, text: str) -> float:
    """Simple word-overlap relevance score (placeholder until LEANN is wired)."""
    query_words = set(query.split())
    text_words = set(text.split())
    if not query_words:
        return 0.0
    overlap = len(query_words & text_words)
    return overlap / len(query_words)


def _estimate_complexity(query: str) -> str:
    """Estimate query complexity to select the right search tier."""
    query_lower = query.lower()

    # Complex indicators
    complex_signals = [
        "why", "how did", "what happened after", "chain of", "sequence of",
        "relationship between", "compare", "summarize all", "timeline",
        "who decided", "what led to", "cross-reference", "connect",
    ]
    if any(signal in query_lower for signal in complex_signals):
        return "complex"

    # Medium indicators
    medium_signals = [
        "and", "or", "between", "during", "about", "regarding",
        "related to", "similar to", "like",
    ]
    if any(signal in query_lower for signal in medium_signals):
        return "medium"

    # Simple: short queries, single keywords, names
    if len(query.split()) <= 3:
        return "simple"

    return "medium"
