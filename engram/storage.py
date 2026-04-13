"""
Engram Storage — Cloud sync for .egm files.

Supports Cloudflare R2 (recommended, zero egress), AWS S3, and local filesystem.
Pattern: write locally first, async push to cloud, pull-on-miss for reads.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

from .core import Engram


class LocalStorage:
    """Local filesystem storage for .egm files."""

    def __init__(self, base_dir: str = "./engram-data"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, memory: Engram, key: str) -> str:
        path = self.base_dir / key
        path.parent.mkdir(parents=True, exist_ok=True)
        memory.save(str(path))
        return str(path)

    def load(self, key: str) -> Optional[Engram]:
        path = self.base_dir / key
        if not path.exists():
            return None
        return Engram.load(str(path))

    def exists(self, key: str) -> bool:
        return (self.base_dir / key).exists()

    def delete(self, key: str) -> bool:
        path = self.base_dir / key
        if path.exists():
            path.unlink()
            return True
        return False

    def list(self, prefix: str = "") -> list[str]:
        results = []
        search_dir = self.base_dir / prefix if prefix else self.base_dir
        if search_dir.exists():
            for p in search_dir.rglob("*.egm"):
                results.append(str(p.relative_to(self.base_dir)))
        return results


class R2Storage:
    """
    Cloudflare R2 storage for .egm files.
    Zero egress fees. S3-compatible API.

    Requires: pip install boto3
    """

    def __init__(
        self,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        cache_dir: str = "/tmp/engram-cache",
    ):
        import boto3
        self.bucket = bucket
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.s3 = boto3.client(
            "s3",
            endpoint_url=endpoint,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name="auto",
        )

    def upload(self, local_path: str, key: str) -> None:
        """Upload an .egm file to R2."""
        self.s3.upload_file(local_path, self.bucket, key)

    def download(self, key: str, local_path: str) -> None:
        """Download an .egm file from R2."""
        Path(local_path).parent.mkdir(parents=True, exist_ok=True)
        self.s3.download_file(self.bucket, key, local_path)

    def load(self, key: str) -> Optional[Engram]:
        """Load an .egm file from R2 with local caching."""
        cache_path = self.cache_dir / key

        if cache_path.exists():
            # Check if cache is still fresh (compare with R2 last-modified)
            try:
                response = self.s3.head_object(Bucket=self.bucket, Key=key)
                remote_mtime = response["LastModified"].timestamp()
                local_mtime = cache_path.stat().st_mtime
                if local_mtime >= remote_mtime:
                    return Engram.load(str(cache_path))
            except Exception:
                # If HEAD fails, use cached version
                return Engram.load(str(cache_path))

        # Cache miss or stale — download from R2
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            self.download(key, str(cache_path))
            return Engram.load(str(cache_path))
        except Exception:
            return None

    def save(self, memory: Engram, key: str) -> None:
        """Save to local cache and async upload to R2."""
        cache_path = self.cache_dir / key
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        memory.save(str(cache_path))
        self.upload(str(cache_path), key)

    def delete(self, key: str) -> None:
        """Delete from R2 and local cache (GDPR)."""
        try:
            self.s3.delete_object(Bucket=self.bucket, Key=key)
        except Exception:
            pass
        cache_path = self.cache_dir / key
        if cache_path.exists():
            cache_path.unlink()

    def exists(self, key: str) -> bool:
        try:
            self.s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception:
            return False

    def list(self, prefix: str = "") -> list[str]:
        results = []
        try:
            response = self.s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix)
            for obj in response.get("Contents", []):
                results.append(obj["Key"])
        except Exception:
            pass
        return results

    def sync(self, local_dir: str, remote_prefix: str, strategy: str = "pull-on-miss") -> dict:
        """
        Sync between local cache and R2.
        Strategies:
          - pull-on-miss: only download files not in local cache
          - pull-all: download all remote files
          - push-all: upload all local files
          - bidirectional: sync both directions (newest wins)
        """
        stats = {"pulled": 0, "pushed": 0, "skipped": 0}
        local = Path(local_dir)
        local.mkdir(parents=True, exist_ok=True)

        if strategy in ("pull-on-miss", "pull-all", "bidirectional"):
            remote_files = self.list(remote_prefix)
            for key in remote_files:
                local_path = local / key.replace(remote_prefix, "", 1).lstrip("/")
                if strategy == "pull-on-miss" and local_path.exists():
                    stats["skipped"] += 1
                    continue
                local_path.parent.mkdir(parents=True, exist_ok=True)
                self.download(key, str(local_path))
                stats["pulled"] += 1

        if strategy in ("push-all", "bidirectional"):
            for egm_file in local.rglob("*.egm"):
                relative = str(egm_file.relative_to(local)).replace("\\", "/")
                key = f"{remote_prefix}/{relative}" if remote_prefix else relative
                self.upload(str(egm_file), key)
                stats["pushed"] += 1

        return stats


class S3Storage(R2Storage):
    """
    AWS S3 storage. Same interface as R2Storage.
    Note: S3 charges egress fees ($0.09/GB). Prefer R2 when possible.
    """

    def __init__(
        self,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str = "us-east-1",
        cache_dir: str = "/tmp/engram-cache",
    ):
        import boto3
        self.bucket = bucket
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self.s3 = boto3.client(
            "s3",
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
