"""
Engram Connectors — Ingest data from various sources into .egm memory files.

Each connector yields chunks of text with metadata that Engram stores and indexes.
"""

from __future__ import annotations

import hashlib
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Iterator


class BaseConnector(ABC):
    """Base class for all data connectors."""

    @abstractmethod
    def chunks(self) -> Iterator[dict]:
        """
        Yield chunks of data to ingest.
        Each chunk is a dict with:
          - text: str (required)
          - metadata: dict (optional)
          - source: str (optional)
        """
        ...


class TextConnector(BaseConnector):
    """Ingest plain text files."""

    def __init__(self, path: str, chunk_size: int = 1000, overlap: int = 200):
        self.path = Path(path)
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunks(self) -> Iterator[dict]:
        if self.path.is_file():
            yield from self._chunk_file(self.path)
        elif self.path.is_dir():
            for f in self.path.rglob("*.txt"):
                yield from self._chunk_file(f)

    def _chunk_file(self, filepath: Path) -> Iterator[dict]:
        text = filepath.read_text(encoding="utf-8", errors="ignore")
        for i in range(0, len(text), self.chunk_size - self.overlap):
            chunk_text = text[i:i + self.chunk_size].strip()
            if len(chunk_text) > 50:
                yield {
                    "text": chunk_text,
                    "metadata": {"file": str(filepath), "offset": i},
                    "source": "file",
                }


class MarkdownConnector(BaseConnector):
    """Ingest Markdown files, splitting by headers."""

    def __init__(self, path: str):
        self.path = Path(path)

    def chunks(self) -> Iterator[dict]:
        files = [self.path] if self.path.is_file() else list(self.path.rglob("*.md"))
        for f in files:
            text = f.read_text(encoding="utf-8", errors="ignore")
            sections = self._split_by_headers(text)
            for title, content in sections:
                if len(content.strip()) > 30:
                    yield {
                        "text": f"{title}\n{content}".strip(),
                        "metadata": {"file": str(f), "section": title},
                        "source": "markdown",
                    }

    def _split_by_headers(self, text: str) -> list[tuple[str, str]]:
        import re
        sections = []
        parts = re.split(r'^(#{1,6}\s+.+)$', text, flags=re.MULTILINE)
        current_title = "Introduction"
        current_content = ""
        for part in parts:
            if part.startswith('#'):
                if current_content.strip():
                    sections.append((current_title, current_content))
                current_title = part.strip('# \n')
                current_content = ""
            else:
                current_content += part
        if current_content.strip():
            sections.append((current_title, current_content))
        return sections


class PDFConnector(BaseConnector):
    """Ingest PDF files. Requires: pip install pymupdf"""

    def __init__(self, path: str, chunk_size: int = 1000):
        self.path = path
        self.chunk_size = chunk_size

    def chunks(self) -> Iterator[dict]:
        try:
            import fitz  # pymupdf
        except ImportError:
            raise ImportError("PDFConnector requires pymupdf: pip install pymupdf")

        doc = fitz.open(self.path)
        for page_num in range(len(doc)):
            page = doc[page_num]
            text = page.get_text().strip()
            if len(text) > 30:
                yield {
                    "text": text,
                    "metadata": {
                        "file": self.path,
                        "page": page_num + 1,
                        "total_pages": len(doc),
                    },
                    "source": "pdf",
                }


class JSONConnector(BaseConnector):
    """Ingest JSON or JSONL files."""

    def __init__(self, path: str, text_field: str = "text", metadata_fields: list[str] | None = None):
        self.path = Path(path)
        self.text_field = text_field
        self.metadata_fields = metadata_fields or []

    def chunks(self) -> Iterator[dict]:
        import json

        if self.path.suffix == ".jsonl":
            with open(self.path) as f:
                for line in f:
                    item = json.loads(line)
                    yield self._item_to_chunk(item)
        else:
            data = json.loads(self.path.read_text())
            items = data if isinstance(data, list) else [data]
            for item in items:
                yield self._item_to_chunk(item)

    def _item_to_chunk(self, item: dict) -> dict:
        text = item.get(self.text_field, str(item))
        metadata = {k: item[k] for k in self.metadata_fields if k in item}
        return {"text": text, "metadata": metadata, "source": "json"}


class CSVConnector(BaseConnector):
    """Ingest CSV files."""

    def __init__(self, path: str, text_col: str, metadata_cols: list[str] | None = None):
        self.path = path
        self.text_col = text_col
        self.metadata_cols = metadata_cols or []

    def chunks(self) -> Iterator[dict]:
        import csv
        with open(self.path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                text = row.get(self.text_col, "")
                if len(text.strip()) > 10:
                    metadata = {k: row[k] for k in self.metadata_cols if k in row}
                    yield {"text": text, "metadata": metadata, "source": "csv"}


class TranscriptConnector(BaseConnector):
    """Ingest meeting transcripts (speaker-labeled text)."""

    def __init__(self, path: str, chunk_by: str = "speaker_turn"):
        self.path = Path(path)
        self.chunk_by = chunk_by

    def chunks(self) -> Iterator[dict]:
        text = self.path.read_text(encoding="utf-8", errors="ignore")
        import re

        # Common transcript formats: "Speaker Name: text" or "[00:00:00] Speaker: text"
        turns = re.split(r'\n(?=(?:\[[0-9:]+\]\s*)?[A-Z][a-z]+ ?[A-Z]?[a-z]*\s*:)', text)
        for turn in turns:
            turn = turn.strip()
            if len(turn) > 20:
                speaker_match = re.match(r'(?:\[([0-9:]+)\]\s*)?([^:]+):\s*(.*)', turn, re.DOTALL)
                metadata = {}
                if speaker_match:
                    if speaker_match.group(1):
                        metadata["timestamp"] = speaker_match.group(1)
                    metadata["speaker"] = speaker_match.group(2).strip()
                yield {
                    "text": turn,
                    "metadata": metadata,
                    "source": "transcript",
                }


class HTMLConnector(BaseConnector):
    """Ingest HTML files, extracting text content."""

    def __init__(self, path: str):
        self.path = Path(path)

    def chunks(self) -> Iterator[dict]:
        import re
        files = [self.path] if self.path.is_file() else list(self.path.rglob("*.html"))
        for f in files:
            html = f.read_text(encoding="utf-8", errors="ignore")
            # Strip HTML tags
            text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL)
            text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL)
            text = re.sub(r'<[^>]+>', ' ', text)
            text = re.sub(r'\s+', ' ', text).strip()
            if len(text) > 50:
                yield {
                    "text": text[:5000],  # cap at 5k chars per page
                    "metadata": {"file": str(f)},
                    "source": "html",
                }
