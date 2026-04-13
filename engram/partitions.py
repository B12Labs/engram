"""
Engram Partitions — Time-based sharding for long-lived agent memory.

Handles 10+ years of data by splitting .egm files into time-partitioned shards:
  - HOT:     Current quarter (always cached, 0ms access)
  - WARM:    Last quarter + last year (cached on access, ~130ms cold start)
  - COLD:    2+ years old (pull on demand, ~500ms-2s)
  - ARCHIVE: 5+ years old (pull on demand, evict immediately)

The manifest.json file (~1-5 KB) is always cached and tells Engram
where to find data without downloading any shards.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from pathlib import Path
from typing import Optional

from .core import Engram, SearchResult


@dataclass
class ShardInfo:
    """Metadata about a single .egm shard in the partition."""
    key: str  # R2/S3 path: "meet/meet.2026-Q2.egm"
    tier: str  # hot | warm | cold | archive
    chunks: int
    size_mb: float
    date_from: str  # ISO date: "2026-04-01"
    date_to: str  # ISO date: "2026-06-30"
    app: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "tier": self.tier,
            "chunks": self.chunks,
            "size_mb": self.size_mb,
            "from": self.date_from,
            "to": self.date_to,
        }

    @classmethod
    def from_dict(cls, d: dict, app: str = "") -> "ShardInfo":
        return cls(
            key=d["key"],
            tier=d.get("tier", "cold"),
            chunks=d.get("chunks", 0),
            size_mb=d.get("size_mb", 0),
            date_from=d.get("from", ""),
            date_to=d.get("to", ""),
            app=app,
        )

    def contains_date(self, target: str) -> bool:
        """Check if a date falls within this shard's range."""
        return self.date_from <= target <= self.date_to


@dataclass
class AppManifest:
    """Manifest for a single app's shards."""
    total_chunks: int = 0
    shards: list[ShardInfo] = field(default_factory=list)

    def hot_shards(self) -> list[ShardInfo]:
        return [s for s in self.shards if s.tier == "hot"]

    def warm_shards(self) -> list[ShardInfo]:
        return [s for s in self.shards if s.tier == "warm"]

    def cold_shards(self) -> list[ShardInfo]:
        return [s for s in self.shards if s.tier in ("cold", "archive")]

    def shard_for_date(self, target: str) -> Optional[ShardInfo]:
        for s in self.shards:
            if s.contains_date(target):
                return s
        return None


@dataclass
class Manifest:
    """
    Master manifest for a user's partitioned memory.
    Always cached locally (~1-5 KB). Tells Engram where everything is.
    """
    version: int = 2
    user_id: str = ""
    created: str = ""
    updated: str = ""
    apps: dict[str, AppManifest] = field(default_factory=dict)
    unified_current: str = ""  # key to current year unified index
    unified_archive: str = ""  # key to archive unified index

    def to_dict(self) -> dict:
        return {
            "version": self.version,
            "user_id": self.user_id,
            "created": self.created,
            "updated": self.updated,
            "apps": {
                name: {
                    "total_chunks": app.total_chunks,
                    "shards": [s.to_dict() for s in app.shards],
                }
                for name, app in self.apps.items()
            },
            "unified": {
                "current": self.unified_current,
                "archive": self.unified_archive,
            },
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Manifest":
        m = cls(
            version=d.get("version", 2),
            user_id=d.get("user_id", ""),
            created=d.get("created", ""),
            updated=d.get("updated", ""),
            unified_current=d.get("unified", {}).get("current", ""),
            unified_archive=d.get("unified", {}).get("archive", ""),
        )
        for app_name, app_data in d.get("apps", {}).items():
            m.apps[app_name] = AppManifest(
                total_chunks=app_data.get("total_chunks", 0),
                shards=[ShardInfo.from_dict(s, app=app_name) for s in app_data.get("shards", [])],
            )
        return m

    def save(self, path: str) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2))

    @classmethod
    def load(cls, path: str) -> "Manifest":
        return cls.from_dict(json.loads(Path(path).read_text()))


def _current_quarter() -> str:
    """Return current quarter label: '2026-Q2'"""
    now = datetime.now()
    q = (now.month - 1) // 3 + 1
    return f"{now.year}-Q{q}"


def _quarter_date_range(quarter_label: str) -> tuple[str, str]:
    """Return date range for a quarter label like '2026-Q2'."""
    year, q = quarter_label.split("-Q")
    q = int(q)
    start_month = (q - 1) * 3 + 1
    end_month = q * 3
    start = f"{year}-{start_month:02d}-01"
    if end_month == 12:
        end = f"{year}-12-31"
    else:
        end = f"{year}-{end_month:02d}-{[0,31,28,31,30,31,30,31,31,30,31,30,31][end_month]}"
    return start, end


class PartitionedMemory:
    """
    Time-partitioned Engram memory.

    Manages multiple .egm shards per app, organized by time period.
    Only the HOT shard (current quarter) is always cached.
    Older shards are pulled on demand from cloud storage.
    """

    def __init__(self, user_id: str, storage=None):
        self.user_id = user_id
        self.storage = storage
        self.manifest = Manifest(
            user_id=user_id,
            created=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            updated=time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        )
        self._loaded_shards: dict[str, Engram] = {}  # key → loaded Engram
        self._cache_dir = Path(f"/tmp/engram-cache/{user_id}")
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def load(cls, user_id: str, storage=None, cache_dir: str = "/tmp/engram-cache") -> "PartitionedMemory":
        """Load a partitioned memory from storage. Only downloads manifest + hot shards."""
        pm = cls(user_id, storage)
        pm._cache_dir = Path(cache_dir) / user_id
        pm._cache_dir.mkdir(parents=True, exist_ok=True)

        # Load manifest
        manifest_key = f"{user_id}/manifest.json"
        if storage:
            manifest_path = pm._cache_dir / "manifest.json"
            if storage.exists(manifest_key):
                storage.download(manifest_key, str(manifest_path))
                pm.manifest = Manifest.load(str(manifest_path))
            else:
                pm.manifest = Manifest(user_id=user_id, created=time.strftime("%Y-%m-%dT%H:%M:%SZ"))
        else:
            manifest_path = pm._cache_dir / "manifest.json"
            if manifest_path.exists():
                pm.manifest = Manifest.load(str(manifest_path))

        # Pre-load HOT shards
        for app_name, app_manifest in pm.manifest.apps.items():
            for shard in app_manifest.hot_shards():
                pm._load_shard(shard)

        return pm

    def _load_shard(self, shard: ShardInfo) -> Engram:
        """Load a shard into memory, pulling from storage if needed."""
        if shard.key in self._loaded_shards:
            return self._loaded_shards[shard.key]

        local_path = self._cache_dir / shard.key
        if not local_path.exists() and self.storage:
            remote_key = f"{self.user_id}/{shard.key}"
            local_path.parent.mkdir(parents=True, exist_ok=True)
            self.storage.download(remote_key, str(local_path))

        if local_path.exists():
            memory = Engram.load(str(local_path))
            self._loaded_shards[shard.key] = memory
            return memory

        # Shard doesn't exist yet — create empty
        memory = Engram()
        self._loaded_shards[shard.key] = memory
        return memory

    def _get_hot_shard(self, app: str) -> tuple[ShardInfo, Engram]:
        """Get or create the current quarter's hot shard for an app."""
        quarter = _current_quarter()
        shard_key = f"{app}/{app}.{quarter}.egm"

        if app not in self.manifest.apps:
            self.manifest.apps[app] = AppManifest()

        app_manifest = self.manifest.apps[app]

        # Find existing hot shard
        for shard in app_manifest.shards:
            if shard.key == shard_key:
                return shard, self._load_shard(shard)

        # Create new hot shard
        date_from, date_to = _quarter_date_range(quarter)
        shard_info = ShardInfo(
            key=shard_key,
            tier="hot",
            chunks=0,
            size_mb=0,
            date_from=date_from,
            date_to=date_to,
            app=app,
        )
        app_manifest.shards.insert(0, shard_info)  # hot first
        memory = Engram()
        self._loaded_shards[shard_key] = memory
        return shard_info, memory

    # ── Write Operations ─────────────────────────────────────

    def add(self, text: str, app: str, metadata: dict | None = None) -> str:
        """Add a chunk to the current quarter's hot shard for the given app."""
        shard_info, memory = self._get_hot_shard(app)
        chunk_id = memory.add(text, metadata=metadata, source=app)
        shard_info.chunks = memory.chunk_count
        self.manifest.apps[app].total_chunks += 1
        self.manifest.updated = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        return chunk_id

    # ── Search Operations ────────────────────────────────────

    def recall(self, query: str, app: str | None = None, top_k: int = 5,
               search_depth: str = "auto", llm_client=None) -> list[SearchResult]:
        """
        Search across partitioned memory with progressive shard loading.

        search_depth:
          - "hot":  Only current quarter (fastest, 0.025ms)
          - "warm": Current quarter + last quarter + last year
          - "cold": All shards (pulls from R2 on demand)
          - "auto": Start with hot, expand if results are insufficient
        """
        apps_to_search = [app] if app else list(self.manifest.apps.keys())
        all_results: list[SearchResult] = []

        for app_name in apps_to_search:
            if app_name not in self.manifest.apps:
                continue
            app_manifest = self.manifest.apps[app_name]

            # Determine which shards to search
            shards_to_search = self._select_shards(app_manifest, search_depth)

            for shard_info in shards_to_search:
                memory = self._load_shard(shard_info)
                results = memory.recall(query, top_k=top_k, llm_client=llm_client)
                for r in results:
                    r.source_app = app_name
                    r.metadata["shard"] = shard_info.key
                    r.metadata["shard_tier"] = shard_info.tier
                all_results.extend(results)

        # Sort by score, deduplicate
        all_results.sort(key=lambda r: r.score, reverse=True)

        # Auto mode: if hot results are weak, expand to warm/cold
        if search_depth == "auto" and all_results and all_results[0].score < 0.5:
            # Expand search to warm shards
            for app_name in apps_to_search:
                if app_name not in self.manifest.apps:
                    continue
                warm_shards = self.manifest.apps[app_name].warm_shards()
                for shard_info in warm_shards:
                    if shard_info.key not in self._loaded_shards:
                        memory = self._load_shard(shard_info)
                        results = memory.recall(query, top_k=top_k, llm_client=llm_client)
                        for r in results:
                            r.source_app = app_name
                            r.metadata["shard"] = shard_info.key
                        all_results.extend(results)
            all_results.sort(key=lambda r: r.score, reverse=True)

        return all_results[:top_k]

    def _select_shards(self, app_manifest: AppManifest, depth: str) -> list[ShardInfo]:
        """Select which shards to search based on depth."""
        if depth == "hot" or depth == "auto":
            return app_manifest.hot_shards()
        elif depth == "warm":
            return app_manifest.hot_shards() + app_manifest.warm_shards()
        elif depth == "cold":
            return app_manifest.shards  # all shards
        return app_manifest.hot_shards()

    def search_date_range(self, query: str, app: str,
                          date_from: str, date_to: str, top_k: int = 5) -> list[SearchResult]:
        """Search within a specific date range — loads only the relevant shards."""
        if app not in self.manifest.apps:
            return []

        relevant_shards = [
            s for s in self.manifest.apps[app].shards
            if s.date_from <= date_to and s.date_to >= date_from
        ]

        all_results: list[SearchResult] = []
        for shard_info in relevant_shards:
            memory = self._load_shard(shard_info)
            results = memory.search(query, top_k=top_k)
            for r in results:
                r.source_app = app
                r.metadata["shard"] = shard_info.key
            all_results.extend(results)

        all_results.sort(key=lambda r: r.score, reverse=True)
        return all_results[:top_k]

    # ── Lifecycle Operations ─────────────────────────────────

    def compact_quarter(self, app: str, quarter: str) -> None:
        """Compact a quarter's shard — rebuild LEANN graph, build PageIndex tree."""
        shard_key = f"{app}/{app}.{quarter}.egm"
        if shard_key in self._loaded_shards:
            memory = self._loaded_shards[shard_key]
            memory.compact()

    def merge_year(self, app: str, year: int) -> None:
        """Merge all quarterly shards for a year into a single annual shard."""
        if app not in self.manifest.apps:
            return

        app_manifest = self.manifest.apps[app]
        year_str = str(year)
        quarterly_shards = [
            s for s in app_manifest.shards
            if s.key.startswith(f"{app}/{app}.{year_str}-Q")
        ]

        if not quarterly_shards:
            return

        # Create merged annual shard
        annual_memory = Engram()
        for shard_info in quarterly_shards:
            quarterly_memory = self._load_shard(shard_info)
            for chunk in quarterly_memory._chunks:
                annual_memory.add(chunk.text, metadata=chunk.metadata, source=chunk.source)

        annual_memory.compact()

        # Save annual shard
        annual_key = f"{app}/{app}.{year_str}.egm"
        annual_path = self._cache_dir / annual_key
        annual_path.parent.mkdir(parents=True, exist_ok=True)
        annual_memory.save(str(annual_path))

        # Update manifest
        date_from = f"{year_str}-01-01"
        date_to = f"{year_str}-12-31"
        annual_shard = ShardInfo(
            key=annual_key,
            tier="warm" if year == datetime.now().year - 1 else "cold",
            chunks=annual_memory.chunk_count,
            size_mb=annual_path.stat().st_size / (1024 * 1024),
            date_from=date_from,
            date_to=date_to,
            app=app,
        )

        # Remove quarterly shards, add annual
        app_manifest.shards = [
            s for s in app_manifest.shards if s not in quarterly_shards
        ]
        app_manifest.shards.append(annual_shard)
        app_manifest.shards.sort(key=lambda s: s.date_from, reverse=True)

        # Upload annual shard to storage
        if self.storage:
            self.storage.upload(str(annual_path), f"{self.user_id}/{annual_key}")

    def promote_tiers(self) -> None:
        """Update shard tiers based on current date. Run periodically."""
        now = datetime.now()
        current_quarter = _current_quarter()

        for app_name, app_manifest in self.manifest.apps.items():
            for shard in app_manifest.shards:
                year = int(shard.date_from[:4])
                is_current_quarter = current_quarter in shard.key

                if is_current_quarter:
                    shard.tier = "hot"
                elif year == now.year:
                    shard.tier = "warm"
                elif year == now.year - 1:
                    shard.tier = "warm"
                elif year <= now.year - 5:
                    shard.tier = "archive"
                else:
                    shard.tier = "cold"

    # ── Save / Sync ──────────────────────────────────────────

    def save(self) -> None:
        """Save all dirty shards and manifest to storage."""
        # Save modified shards
        for shard_key, memory in self._loaded_shards.items():
            local_path = self._cache_dir / shard_key
            local_path.parent.mkdir(parents=True, exist_ok=True)
            memory.save(str(local_path))
            if self.storage:
                self.storage.upload(str(local_path), f"{self.user_id}/{shard_key}")

        # Save manifest
        manifest_path = self._cache_dir / "manifest.json"
        self.manifest.updated = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.manifest.save(str(manifest_path))
        if self.storage:
            self.storage.upload(str(manifest_path), f"{self.user_id}/manifest.json")

    # ── GDPR ─────────────────────────────────────────────────

    def delete_all(self) -> None:
        """Delete all data for this user (GDPR right to erasure)."""
        if self.storage:
            for app_name, app_manifest in self.manifest.apps.items():
                for shard in app_manifest.shards:
                    self.storage.delete(f"{self.user_id}/{shard.key}")
            self.storage.delete(f"{self.user_id}/manifest.json")

        # Clear local cache
        import shutil
        if self._cache_dir.exists():
            shutil.rmtree(self._cache_dir)

    def delete_year(self, app: str, year: int) -> int:
        """Delete a specific year's data for an app."""
        if app not in self.manifest.apps:
            return 0

        year_str = str(year)
        to_delete = [
            s for s in self.manifest.apps[app].shards
            if s.date_from.startswith(year_str)
        ]

        deleted_chunks = 0
        for shard in to_delete:
            deleted_chunks += shard.chunks
            if self.storage:
                self.storage.delete(f"{self.user_id}/{shard.key}")
            local_path = self._cache_dir / shard.key
            if local_path.exists():
                local_path.unlink()
            self._loaded_shards.pop(shard.key, None)

        self.manifest.apps[app].shards = [
            s for s in self.manifest.apps[app].shards if s not in to_delete
        ]
        self.manifest.apps[app].total_chunks -= deleted_chunks
        return deleted_chunks

    # ── Stats ────────────────────────────────────────────────

    def stats(self) -> dict:
        """Return partitioned memory statistics."""
        total_chunks = sum(a.total_chunks for a in self.manifest.apps.values())
        total_shards = sum(len(a.shards) for a in self.manifest.apps.values())
        total_size = sum(
            s.size_mb for a in self.manifest.apps.values() for s in a.shards
        )
        return {
            "user_id": self.user_id,
            "total_chunks": total_chunks,
            "total_shards": total_shards,
            "total_size_mb": round(total_size, 1),
            "apps": list(self.manifest.apps.keys()),
            "loaded_shards": len(self._loaded_shards),
            "created": self.manifest.created,
            "updated": self.manifest.updated,
        }
