"""Tests for app.publish.image_dims.jpeg_size -- a minimal, hand-built
JPEG byte sequence (SOI immediately followed by a single SOF0 segment
declaring height=100, width=200) is used rather than a real image file,
so the test has no binary fixture to maintain."""
from __future__ import annotations

from app.publish.image_dims import jpeg_size

MINIMAL_JPEG_200x100 = bytes(
    [
        0xFF, 0xD8,              # SOI
        0xFF, 0xC0,              # SOF0 marker
        0x00, 0x11,               # segment length = 17 (includes these 2 bytes)
        0x08,                      # precision
        0x00, 0x64,                # height = 100
        0x00, 0xC8,                 # width = 200
        0x03,                        # 3 components
        0x01, 0x22, 0x00,
        0x02, 0x11, 0x01,
        0x03, 0x11, 0x01,
    ]
)


def test_parses_minimal_valid_jpeg():
    assert jpeg_size(MINIMAL_JPEG_200x100) == (200, 100)


def test_returns_none_for_non_jpeg_data():
    assert jpeg_size(b"not a jpeg at all, just some bytes") is None


def test_returns_none_for_empty_data():
    assert jpeg_size(b"") is None


def test_returns_none_for_truncated_header():
    assert jpeg_size(b"\xff\xd8\xff") is None
