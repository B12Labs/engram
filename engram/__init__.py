"""
Engram — AI Agents Engine RAM

Portable, graph-compressed, single-file memory for AI agents.
Three-tier search: LEANN vectors (0.025ms) → Tantivy hybrid (0.1ms) → PageIndex reasoning (2-5s).

Usage:
    from engram import Engram, UnifiedIndex

    memory = Engram()
    memory.add("Meeting notes: discussed Q2 roadmap")
    memory.save("work.egm")

    memory = Engram.load("work.egm")
    results = memory.recall("What was discussed?")
"""

__version__ = "0.2.0"

from .core import Engram, UnifiedIndex, SearchResult, Chunk, TreeNode
from .partitions import PartitionedMemory, Manifest, ShardInfo

__all__ = [
    "Engram",
    "UnifiedIndex",
    "SearchResult",
    "Chunk",
    "TreeNode",
    "PartitionedMemory",
    "Manifest",
    "ShardInfo",
]
