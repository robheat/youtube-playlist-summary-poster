"""Dependency-free JPEG dimension reader.

YouTube thumbnails are always JPEG, so only that format is supported here.
Ported from ainformed-dev/pipeline/image_dims.py's approach (a stdlib-only
struct-based reader used there specifically so the pipeline doesn't need
Pillow just to read dimensions) rather than adding a new dependency.
"""
from __future__ import annotations

import struct


def jpeg_size(data: bytes) -> tuple[int, int] | None:
    """Returns (width, height), or None if data isn't a parseable JPEG."""
    if len(data) < 4 or data[:3] != b"\xff\xd8\xff":
        return None

    i = 2
    while i < len(data) - 9:
        if data[i] != 0xFF:
            i += 1
            continue

        marker = data[i + 1]

        # SOF0-SOF15, excluding DHT/JPG/DAC which share the numeric range
        # but aren't actual start-of-frame markers.
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            height, width = struct.unpack(">HH", data[i + 5 : i + 9])
            return (width, height)

        # SOI/EOI/RSTn: standalone 2-byte markers with no length field.
        if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue

        length = int.from_bytes(data[i + 2 : i + 4], "big")
        if length < 2:
            return None
        i += 2 + length

    return None
