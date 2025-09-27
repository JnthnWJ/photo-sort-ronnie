from __future__ import annotations
from pathlib import Path
from typing import Iterable, List, Optional, Tuple, Callable
from datetime import datetime, date
import os
import sys
import shutil
import logging

from .ops import Options, Action, DuplicateRegistry
from .patterns import date_from_filename

try:
    # Enable HEIC/AVIF support via Pillow
    from pillow_heif import register_heif_opener  # type: ignore
    register_heif_opener()
except Exception:
    pass

try:
    from PIL import Image, ExifTags  # type: ignore
except Exception as e:
    raise RuntimeError("Pillow is required for image processing") from e

logger = logging.getLogger("photosorter")

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".heic"}


def iter_photo_files(root: Path, recursive: bool = True) -> Iterable[Path]:
    root = root.expanduser().resolve()
    if recursive:
        for dirpath, _dirs, files in os.walk(root):
            dpath = Path(dirpath)
            for f in files:
                ext = Path(f).suffix.lower()
                if ext in SUPPORTED_EXTS:
                    yield dpath / f
    else:
        for p in root.iterdir():
            if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS:
                yield p


def _parse_exif_datetime(dt_str: str) -> Optional[date]:
    # EXIF often uses "YYYY:MM:DD HH:MM:SS"
    try:
        return datetime.strptime(dt_str, "%Y:%m:%d %H:%M:%S").date()
    except Exception:
        # Try broader formats
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y/%m/%d %H:%M:%S", "%Y:%m:%d"):
            try:
                return datetime.strptime(dt_str, fmt).date()
            except Exception:
                pass
    return None


def _exif_dict(img: Image.Image) -> dict:
    exif = img.getexif() or {}
    tags = {}
    for k, v in exif.items():
        name = ExifTags.TAGS.get(k, str(k))
        tags[name] = v
    return tags


def extract_photo_date(p: Path, use_file_times: bool = True) -> Tuple[Optional[date], str]:
    """Return (date, reason) for the best guess of a photo's date.

    reason is one of: "exif", "filename", "filetime", "unknown".
    If use_file_times is False, the filesystem time fallback is skipped.
    """
    # 1) EXIF
    try:
        with Image.open(p) as img:
            tags = _exif_dict(img)
            for key in ("DateTimeOriginal", "DateTime", "CreateDate"):
                v = tags.get(key)
                if v:
                    if isinstance(v, bytes):
                        try:
                            v = v.decode("utf-8", "ignore")
                        except Exception:
                            v = str(v)
                    dt = _parse_exif_datetime(str(v))
                    if dt:
                        return dt, "exif"
    except Exception:
        pass

    # 2) Filename patterns
    dt = date_from_filename(p.name)
    if dt:
        return dt, "filename"

    # 3) Filesystem times (optional)
    if use_file_times:
        try:
            st = p.stat()
            # Prefer birth time if available (macOS), else modification
            if hasattr(st, "st_birthtime"):
                dt = datetime.fromtimestamp(getattr(st, "st_birthtime")).date()
            else:
                dt = datetime.fromtimestamp(st.st_mtime).date()
            return dt, "filetime"
        except Exception:
            pass

    # 4) Unknown
    return None, "unknown"


def _dest_dir_for(dest_root: Path, dt: Optional[date]) -> Path:
    if dt is None:
        return dest_root / "unknown"
    return dest_root / f"{dt.year:04d}" / f"{dt.month:02d}"


def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def plan_actions(opts: Options) -> List[Action]:
    actions: List[Action] = []
    for p in iter_photo_files(opts.source, opts.recursive):
        dt, reason = extract_photo_date(p, opts.fallback_use_file_times)
        dst_dir = _dest_dir_for(opts.dest_root, dt)
        dst = dst_dir / p.name
        actions.append(Action(src=p, dst=dst, op=opts.mode, used_date=dt, reason=reason))
    return actions


def execute_actions(
    actions: List[Action],
    *,
    progress: Callable[[int, int, str], None] | None = None,
    log: Callable[[str], None] | None = None,
    on_error: Callable[[str], None] | None = None,
    stop_flag: Optional["threading.Event"] = None,
    max_workers: int = 8,
) -> None:
    """Execute copy/move plan with duplicate-safe destination selection.

    This function processes actions potentially in parallel, ensures destination
    directories exist, and appends numeric suffixes when collisions occur.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    import threading

    total = len(actions)
    reg = DuplicateRegistry()
    idx = 0
    lock = threading.Lock()

    def do_one(act: Action) -> tuple[Path, Path, bool, Optional[str]]:
        try:
            if stop_flag and stop_flag.is_set():
                return act.src, act.dst, False, "cancelled"
            # Decide final destination with duplicate handling
            dst_dir = _dest_dir_for(Path(act.dst).parents[1] if act.used_date else Path(act.dst).parent.parent, act.used_date)
            # above line reconstructs dest_dir from act.used_date and act.dst root
            # Better: just use act.dst.parent as base dir
            dst_dir = act.dst.parent
            _ensure_dir(dst_dir)
            final_dst = reg.next_available(act.dst)
            if log:
                log(f"{act.op.upper()} {act.src} -> {final_dst} [{act.reason}]")
            if stop_flag and stop_flag.is_set():
                return act.src, final_dst, False, "cancelled"
            if act.op == "copy":
                shutil.copy2(act.src, final_dst)
            else:
                shutil.move(str(act.src), str(final_dst))
            return act.src, final_dst, True, None
        except Exception as e:
            return act.src, act.dst, False, str(e)

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futures = [ex.submit(do_one, a) for a in actions]
        for fut in as_completed(futures):
            src, dst, ok, err = fut.result()
            with lock:
                idx += 1
                if progress:
                    progress(idx, total, f"Processed: {src.name}")
            if not ok and on_error:
                on_error(f"Failed {src} -> {dst}: {err}")

