from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, List
from datetime import date
import threading


@dataclass
class Options:
    source: Path
    dest_root: Path
    mode: str = "copy"  # "copy" or "move"
    recursive: bool = True
    dry_run: bool = True
    fallback_use_file_times: bool = True
    max_workers: int = 8
    convert_heic_to_jpeg: bool = False
    live_photos: str = "preserve_both"  # "preserve_both" | "image_only" | "video_only"


@dataclass
class Action:
    src: Path
    dst: Path
    op: str  # "copy" or "move"
    used_date: Optional[date]
    reason: str  # e.g., "exif", "filename", "filetime", "unknown"


# Thread-safe registry to avoid duplicate destination filenames across workers
class DuplicateRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._used: set[Path] = set()

    def reserve(self, p: Path) -> None:
        with self._lock:
            self._used.add(p)

    def is_taken(self, p: Path) -> bool:
        with self._lock:
            return p in self._used

    def next_available(self, p: Path) -> Path:
        """Compute next available unique path based on existence and in-memory reservations."""
        if not p.exists() and not self.is_taken(p):
            self.reserve(p)
            return p
        stem, suf = p.stem, p.suffix
        i = 1
        while True:
            cand = p.with_name(f"{stem}_{i}{suf}")
            if not cand.exists() and not self.is_taken(cand):
                self.reserve(cand)
                return cand
            i += 1

