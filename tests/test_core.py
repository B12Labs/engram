"""Tests for Engram core functionality."""

import json
import tempfile
from pathlib import Path

from engram.core import Engram, UnifiedIndex, SearchResult, TreeNode, _estimate_complexity


class TestEngram:
    """Test core Engram memory operations."""

    def test_create_empty(self):
        memory = Engram()
        assert memory.chunk_count == 0
        assert memory.model_name == "facebook/contriever"

    def test_add_chunk(self):
        memory = Engram()
        chunk_id = memory.add("Meeting notes from April 12")
        assert memory.chunk_count == 1
        assert chunk_id.startswith("chunk_")

    def test_add_many(self):
        memory = Engram()
        ids = memory.add_many([
            {"text": "First memory"},
            {"text": "Second memory", "metadata": {"priority": "high"}},
            {"text": "Third memory", "source": "email"},
        ])
        assert len(ids) == 3
        assert memory.chunk_count == 3

    def test_search_basic(self):
        memory = Engram()
        memory.add("The budget was approved for $50k")
        memory.add("New hire starts on Monday")
        memory.add("Deployment scheduled for Friday")

        results = memory.search("budget approved")
        assert len(results) > 0
        assert results[0].tier == "fast"
        assert "budget" in results[0].text.lower()

    def test_search_hybrid(self):
        memory = Engram()
        memory.add("Q2 roadmap discussion")
        memory.add("Budget review meeting")

        results = memory.search_hybrid("roadmap")
        assert len(results) > 0
        assert results[0].tier == "hybrid"

    def test_search_deep_without_llm(self):
        memory = Engram()
        memory.add("April 12: Budget approved", metadata={"type": "decision"})
        memory.add("April 11: Budget proposed", metadata={"type": "proposal"})
        memory.build_tree()

        results = memory.search_deep("budget decision")
        assert isinstance(results, list)
        # Without LLM, falls back to tree-guided search

    def test_recall_auto_tier(self):
        memory = Engram()
        memory.add("Deployment on Friday")

        # Simple query → Tier 1
        results = memory.recall("deployment")
        assert len(results) > 0

    def test_save_and_load(self):
        memory = Engram()
        memory.add("Test memory item", metadata={"key": "value"}, source="test")
        memory.add("Second item")
        memory.build_tree()

        with tempfile.NamedTemporaryFile(suffix=".egm", delete=False) as f:
            path = f.name

        try:
            memory.save(path)
            assert Path(path).exists()

            loaded = Engram.load(path)
            assert loaded.chunk_count == 2
            assert loaded._tree is not None
            assert loaded._metadata.has_tree is True

            results = loaded.search("test memory")
            assert len(results) > 0
        finally:
            Path(path).unlink(missing_ok=True)

    def test_delete_chunk(self):
        memory = Engram()
        id1 = memory.add("Keep this")
        id2 = memory.add("Delete this")
        assert memory.chunk_count == 2

        result = memory.delete(id2)
        assert result is True
        assert memory.chunk_count == 1

    def test_delete_by_metadata(self):
        memory = Engram()
        memory.add("User A data", metadata={"user_id": "user_123"})
        memory.add("User A more data", metadata={"user_id": "user_123"})
        memory.add("User B data", metadata={"user_id": "user_456"})

        deleted = memory.delete_by_metadata(user_id="user_123")
        assert deleted == 2
        assert memory.chunk_count == 1

    def test_compact(self):
        memory = Engram()
        memory.add("Item 1")
        memory.add("Item 2")
        assert len(memory._wal) == 2

        memory.compact()
        assert len(memory._wal) == 0
        assert memory._tree is not None
        assert memory._metadata.compaction_count == 1

    def test_stats(self):
        memory = Engram()
        memory.add("Test")
        stats = memory.stats()
        assert stats["chunk_count"] == 1
        assert stats["model"] == "facebook/contriever"
        assert stats["has_tree"] is False


class TestTreeNode:
    """Test PageIndex tree operations."""

    def test_build_tree(self):
        memory = Engram()
        memory.add("Morning meeting", source="meet")
        memory.add("Email from Sarah", source="email")
        memory.add("Slack message", source="slack")

        tree = memory.build_tree()
        assert tree.node_type == "root"
        assert len(tree.children) >= 1  # at least one date node

    def test_tree_serialization(self):
        node = TreeNode(
            title="Root",
            node_type="root",
            children=[
                TreeNode(title="2026-04-12", node_type="date", chunk_ids=["c1", "c2"]),
            ],
        )
        d = node.to_dict()
        restored = TreeNode.from_dict(d)
        assert restored.title == "Root"
        assert len(restored.children) == 1
        assert restored.children[0].chunk_ids == ["c1", "c2"]


class TestUnifiedIndex:
    """Test cross-app search."""

    def test_unified_search(self):
        meet = Engram()
        meet.add("Budget approved in meeting")

        email = Engram()
        email.add("Budget email from Sarah")

        unified = UnifiedIndex({"meet": meet, "email": email})
        results = unified.search("budget")
        assert len(results) >= 2
        sources = {r.source_app for r in results}
        assert "meet" in sources
        assert "email" in sources

    def test_total_chunks(self):
        m1 = Engram()
        m1.add("A")
        m2 = Engram()
        m2.add("B")
        m2.add("C")

        unified = UnifiedIndex({"m1": m1, "m2": m2})
        assert unified.total_chunks == 3
        assert set(unified.memory_names) == {"m1", "m2"}


class TestComplexityEstimation:
    """Test query complexity auto-detection."""

    def test_simple_queries(self):
        assert _estimate_complexity("budget") == "simple"
        assert _estimate_complexity("Sarah") == "simple"
        assert _estimate_complexity("deploy Friday") == "simple"

    def test_medium_queries(self):
        assert _estimate_complexity("budget and deployment") == "medium"
        assert _estimate_complexity("meetings related to hiring") == "medium"

    def test_complex_queries(self):
        assert _estimate_complexity("why was the budget rejected") == "complex"
        assert _estimate_complexity("what happened after the meeting") == "complex"
        assert _estimate_complexity("timeline of hiring decisions") == "complex"


class TestEgmFileFormat:
    """Test .egm file format integrity."""

    def test_file_contains_magic(self):
        memory = Engram()
        memory.add("Test")

        with tempfile.NamedTemporaryFile(suffix=".egm", delete=False) as f:
            path = f.name

        try:
            memory.save(path)
            content = json.loads(Path(path).read_text())
            assert content["magic"] == "ENGRAM"
            assert content["version"] == 2
            assert len(content["chunks"]) == 1
        finally:
            Path(path).unlink(missing_ok=True)

    def test_file_with_tree(self):
        memory = Engram()
        memory.add("Test 1", source="meet")
        memory.add("Test 2", source="email")
        memory.build_tree()

        with tempfile.NamedTemporaryFile(suffix=".egm", delete=False) as f:
            path = f.name

        try:
            memory.save(path)
            content = json.loads(Path(path).read_text())
            assert content["tree"] is not None
            assert content["tree"]["node_type"] == "root"
            assert content["metadata"]["has_tree"] is True
        finally:
            Path(path).unlink(missing_ok=True)
