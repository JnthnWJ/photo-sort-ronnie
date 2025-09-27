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
    src_root = opts.source.expanduser().resolve()

    # Determine whether to include videos based on Live Photos mode
    mode_lp = getattr(opts, "live_photos", "preserve_both")
    include_videos = mode_lp != "image_only"

    image_exts = {".jpg", ".jpeg", ".png", ".heic"}
    video_exts = {".mov"}

    # Collect candidate files
    files: List[Path] = []
    if opts.recursive:
        for dirpath, _dirs, names in os.walk(src_root):
            d = Path(dirpath)
            for name in names:
                ext = Path(name).suffix.lower()
                if ext in image_exts or (include_videos and ext in video_exts):
                    files.append(d / name)
    else:
        for p in src_root.iterdir():
            if p.is_file():
                ext = p.suffix.lower()
                if ext in image_exts or (include_videos and ext in video_exts):
                    files.append(p)

    # Group by Live Photo pairing key
    def _pair_key(p: Path) -> str:
        stem = p.stem
        # Normalize IMG_E1234 -> IMG_1234 to pair edited stills with their MOV
        if stem.startswith("IMG_E") and len(stem) > 5 and stem[5:].isdigit():
            return "IMG_" + stem[5:]
        return stem

    groups: dict[str, dict[str, Optional[Path]]] = {}
    for p in files:
        ext = p.suffix.lower()
        key = _pair_key(p)
        g = groups.setdefault(key, {"image": None, "video": None})
        if ext in image_exts and g["image"] is None:
            g["image"] = p
        elif ext in video_exts and g["video"] is None:
            g["video"] = p

    for key, parts in groups.items():
        img = parts["image"]
        vid = parts["video"]
        include_image = img is not None and mode_lp in ("preserve_both", "image_only")
        include_video = vid is not None and mode_lp in ("preserve_both", "video_only")

        # Determine date and reason (prefer image when present)
        date_src = img or vid
        dt, reason = extract_photo_date(date_src, opts.fallback_use_file_times) if date_src else (None, "unknown")
        dst_dir = _dest_dir_for(opts.dest_root, dt)

        if include_image and img is not None:
            img_name = img.name
            if getattr(opts, "convert_heic_to_jpeg", False) and img.suffix.lower() == ".heic":
                img_name = img.stem + ".jpg"
            actions.append(Action(src=img, dst=dst_dir / img_name, op=opts.mode, used_date=dt, reason=reason))

        if include_video and vid is not None:
            # Align video basename with image stem if image exists
            if img is not None:
                vid_name = img.stem + vid.suffix.lower()
            else:
                vid_name = vid.name
            actions.append(Action(src=vid, dst=dst_dir / vid_name, op=opts.mode, used_date=dt, reason=reason))

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
            # Handle optional HEIC -> JPEG conversion if destination is JPEG
            src_ext = act.src.suffix.lower()
            dst_ext = final_dst.suffix.lower()
            if src_ext == ".heic" and dst_ext in (".jpg", ".jpeg"):
                try:
                    with Image.open(act.src) as img:
                        exif_bytes = img.info.get("exif")
                        img.save(final_dst, format="JPEG", quality=95, exif=exif_bytes)
                    # Preserve timestamps from source
                    try:
                        st = act.src.stat()
                        os.utime(final_dst, (st.st_atime, st.st_mtime))
                    except Exception:
                        pass
                    # If move mode, remove original HEIC after successful conversion
                    if act.op == "move":
                        try:
                            os.remove(act.src)
                        except Exception:
                            pass
                except Exception as e:
                    # Fallback: copy/move original HEIC to a .heic destination
                    fb_dst = reg.next_available(final_dst.with_suffix(".heic"))
                    if log:
                        log(f"Conversion failed for {act.src}: {e}; falling back to {fb_dst}")
                    if act.op == "copy":
                        shutil.copy2(act.src, fb_dst)
                    else:
                        shutil.move(str(act.src), str(fb_dst))
                    return act.src, fb_dst, True, None
            else:
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

