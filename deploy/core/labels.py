"""Shaft label formatting and parsing.

A label like '19-01' is a display convenience over (batch_no, seq). It is
never sorted or compared as text: 'BATCH#-SHAFT#' text-sorts wrong once a
batch reaches double digits ('19-100' < '19-20' as strings). Callers must
sort by batch_no and seq directly.
"""

from __future__ import annotations

import re

_LABEL_RE = re.compile(r"^(\d+)-(\d+)$")


def shaft_label(batch_no: int, seq: int, seq_width: int) -> str:
    if batch_no <= 0:
        raise ValueError(f"batch_no must be positive, got {batch_no}")
    if seq <= 0:
        raise ValueError(f"seq must be positive, got {seq}")
    if len(str(seq)) > seq_width:
        raise ValueError(f"seq {seq} does not fit seq_width {seq_width}")
    return f"{batch_no}-{seq:0{seq_width}d}"


def parse_label(label: str) -> tuple[int, int]:
    match = _LABEL_RE.match(label.strip())
    if not match:
        raise ValueError(f"{label!r} is not a valid shaft label")
    return int(match.group(1)), int(match.group(2))


def required_seq_width(expected_count: int) -> int:
    """The narrowest width that fits expected_count shafts, floored at 2."""
    return max(2, len(str(max(expected_count, 1))))
