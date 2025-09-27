from __future__ import annotations
import re
from datetime import date
from typing import Optional

# Common filename date patterns, tolerant of separators and prefixes
# Examples:
#   20240305, 2024-03-05, 2024_03_05, IMG_20240305, PXL_20240305_123456
#   2024.03.05, 2024 03 05

# Strict YYYY MM DD with optional separators between parts
_SEP = r"[-_ .]?"
YYYY = r"(?P<y>19\d{2}|20\d{2})"
MM = r"(?P<m>0[1-9]|1[0-2])"
DD = r"(?P<d>0[1-9]|[12][0-9]|3[01])"

# 1) Continuous YYYYMMDD possibly embedded in larger names
_CONTIGUOUS = re.compile(rf"(?<!\d){YYYY}{MM}{DD}(?!\d)")
# 2) With separators YYYY[-_]MM[-_]DD
_WITH_SEP = re.compile(rf"(?<!\d){YYYY}{_SEP}{MM}{_SEP}{DD}(?!\d)")

# 3) Android/Google style like PXL_20240305_* or IMG_20240305_*
_PREFIXED = re.compile(rf"(?:IMG|PXL|VID|MOV|DSC){_SEP}{YYYY}{MM}{DD}")

_PATTERNS = [_CONTIGUOUS, _WITH_SEP, _PREFIXED]


def _to_date(y: str, m: str, d: str) -> Optional[date]:
    try:
        return date(int(y), int(m), int(d))
    except Exception:
        return None


def date_from_filename(name: str) -> Optional[date]:
    """Try to extract a date from the base filename.

    Returns a datetime.date if a plausible YYYY-MM-DD is found, else None.
    """
    base = name
    for pat in _PATTERNS:
        m = pat.search(base)
        if not m:
            continue
        gd = m.groupdict()
        if {"y", "m", "d"}.issubset(gd):
            dt = _to_date(gd["y"], gd["m"], gd["d"])
            if dt:
                return dt
        else:
            # For prefixed pattern without named groups, slice out groups
            # Find contiguous YYYYMMDD inside the match
            s = m.group(0)
            m2 = re.search(r"(19\d{2}|20\d{2})(0[1-9]|1[0-2])([0-3]\d)", s)
            if m2:
                return _to_date(m2.group(1), m2.group(2), m2.group(3))
    return None

