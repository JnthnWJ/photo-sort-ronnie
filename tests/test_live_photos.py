import os
from pathlib import Path

from photosorter.ops import Options
from photosorter.core import plan_actions


def _make(tmp_path: Path, name: str) -> Path:
    p = tmp_path / name
    p.write_bytes(b"")
    return p


def test_plan_preserve_both_with_conversion(tmp_path):
    # Arrange: Live Photo pair with date in filename
    _make(tmp_path, "IMG_20240305.HEIC")
    _make(tmp_path, "IMG_20240305.MOV")
    out = tmp_path / "out"

    opts = Options(
        source=tmp_path,
        dest_root=out,
        mode="copy",
        recursive=False,
        dry_run=True,
        fallback_use_file_times=True,
        max_workers=1,
        convert_heic_to_jpeg=True,
        live_photos="preserve_both",
    )

    # Act
    actions = plan_actions(opts)

    # Assert
    # Expect two actions: JPEG and MOV under 2024/03
    dsts = [a.dst for a in actions]
    assert len(dsts) == 2
    jpgs = [d for d in dsts if d.suffix.lower() == ".jpg"]
    movs = [d for d in dsts if d.suffix.lower() == ".mov"]
    assert len(jpgs) == 1 and len(movs) == 1
    assert jpgs[0].parts[-3:-1] == ("2024", "03")
    assert movs[0].parts[-3:-1] == ("2024", "03")
    assert jpgs[0].stem == movs[0].stem == "IMG_20240305"


def test_plan_image_only(tmp_path):
    _make(tmp_path, "IMG_20240305.HEIC")
    _make(tmp_path, "IMG_20240305.MOV")
    out = tmp_path / "out"

    opts = Options(
        source=tmp_path,
        dest_root=out,
        mode="copy",
        recursive=False,
        dry_run=True,
        fallback_use_file_times=True,
        max_workers=1,
        convert_heic_to_jpeg=False,
        live_photos="image_only",
    )

    actions = plan_actions(opts)
    # Only the HEIC should be planned, and with its native extension
    assert len(actions) == 1
    assert actions[0].dst.suffix.lower() == ".heic"
    assert actions[0].dst.parts[-3:-1] == ("2024", "03")


def test_plan_img_e_pairing(tmp_path):
    # IMG_E still with base MOV; MOV should adopt IMG_E stem in output
    _make(tmp_path, "IMG_E20240305.HEIC")
    _make(tmp_path, "IMG_20240305.MOV")
    out = tmp_path / "out"

    opts = Options(
        source=tmp_path,
        dest_root=out,
        mode="copy",
        recursive=False,
        dry_run=True,
        fallback_use_file_times=True,
        max_workers=1,
        convert_heic_to_jpeg=True,
        live_photos="preserve_both",
    )

    actions = plan_actions(opts)
    dsts = [a.dst for a in actions]
    jpg = next(d for d in dsts if d.suffix.lower() == ".jpg")
    mov = next(d for d in dsts if d.suffix.lower() == ".mov")
    assert jpg.stem == mov.stem == "IMG_E20240305"

