#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the Actions Brain icon files into tools/tasks-web/static/ (standard library only).

Run from Work with: uv run tools/tasks-web/make-icon.py

One drawing, defined below, gives four files: `icon.svg` (scalable), `icon.png` (256 px, Linux),
`icon.ico` (16 to 256 px, PNG images inside, Windows) and `icon.icns` (16 to 1024 px, PNG images
inside, macOS). The drawing is a white check mark on a rounded square of the app's steel accent.
Every PNG carries a tEXt chunk with ICON_MARKER and the SVG a comment with it: install-app.py
removes an installed icon on --uninstall only when it carries that marker.
"""

from __future__ import annotations

import math
import struct
import zlib
from itertools import pairwise
from pathlib import Path

STATIC = Path(__file__).resolve().parent / "static"
ICON_MARKER = "actions-brain-icon"
BACKGROUND = (0x2F, 0x5D, 0x8A)  # --accent of [data-accent="steel"] in static/app.css
FOREGROUND = (0xFF, 0xFF, 0xFF)
MARGIN = 0.06  # empty border around the rounded square, in units of the icon size
RADIUS = 0.22  # corner radius of the square
CHECK = ((0.28, 0.52), (0.44, 0.68), (0.74, 0.36))  # the check mark's polyline (y downwards)
STROKE = 0.10  # width of the check mark
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_TYPES = ((b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"ic12", 64), (b"ic07", 128), (b"ic13", 256),
              (b"ic08", 256), (b"ic14", 512), (b"ic09", 512), (b"ic10", 1024))


def rounded_square_distance(x: float, y: float) -> float:
    """Signed distance (negative inside) from (x, y) to the rounded square, in units of the icon size."""
    half = 0.5 - MARGIN
    qx = abs(x - 0.5) - (half - RADIUS)
    qy = abs(y - 0.5) - (half - RADIUS)
    outside = math.hypot(max(qx, 0.0), max(qy, 0.0))
    return outside + min(max(qx, qy), 0.0) - RADIUS


def check_distance(x: float, y: float) -> float:
    """Signed distance from (x, y) to the stroked check mark (round caps and joins)."""
    best = math.inf
    for (ax, ay), (bx, by) in pairwise(CHECK):
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - ax - t * dx, y - ay - t * dy))
    return best - STROKE / 2


def render(size: int) -> bytes:
    """RGBA rows of the icon at `size` px, anti-aliased over one pixel, each row prefixed by PNG filter 0."""
    rows = bytearray()
    for row in range(size):
        rows.append(0)
        y = (row + 0.5) / size
        for column in range(size):
            x = (column + 0.5) / size
            back = min(1.0, max(0.0, 0.5 - rounded_square_distance(x, y) * size))
            if back == 0.0:
                rows += b"\0\0\0\0"
                continue
            mark = min(1.0, max(0.0, 0.5 - check_distance(x, y) * size)) * back
            alpha = mark + back * (1.0 - mark)
            color = (round((fg * mark + bg * back * (1.0 - mark)) / alpha) for fg, bg in zip(FOREGROUND, BACKGROUND, strict=True))
            rows += bytes((*color, round(alpha * 255)))
    return bytes(rows)


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(size: int) -> bytes:
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA, no interlace
    text = b"Software\0" + f"{ICON_MARKER} (tools/tasks-web/make-icon.py)".encode("ascii")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"tEXt", text)
            + chunk(b"IDAT", zlib.compress(render(size), 9)) + chunk(b"IEND", b""))


def ico(images: dict[int, bytes]) -> bytes:
    """An ICO file whose entries are PNG images (read by Windows Vista and later)."""
    sizes = sorted(images)
    offset = 6 + 16 * len(sizes)
    directory, payload = b"", b""
    for size in sizes:
        data = images[size]
        side = 0 if size >= 256 else size  # 0 means 256 in an ICO directory entry
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset + len(payload))
        payload += data
    return struct.pack("<HHH", 0, 1, len(sizes)) + directory + payload


def icns(images: dict[int, bytes]) -> bytes:
    body = b"".join(kind + struct.pack(">I", 8 + len(images[size])) + images[size] for kind, size in ICNS_TYPES)
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def svg() -> str:
    side = 1 - 2 * MARGIN
    points = " ".join(f"{x * 256:g},{y * 256:g}" for x, y in CHECK)
    color = "#{:02X}{:02X}{:02X}".format(*BACKGROUND)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 256 256">\n'
            f"  <!-- {ICON_MARKER}: written by tools/tasks-web/make-icon.py -->\n"
            f'  <rect x="{MARGIN * 256:g}" y="{MARGIN * 256:g}" width="{side * 256:g}" height="{side * 256:g}" '
            f'rx="{RADIUS * 256:g}" fill="{color}"/>\n'
            f'  <polyline points="{points}" fill="none" stroke="#FFFFFF" stroke-width="{STROKE * 256:g}" '
            f'stroke-linecap="round" stroke-linejoin="round"/>\n'
            f"</svg>\n")


def main() -> int:
    images = {size: png(size) for size in sorted({*ICO_SIZES, *(size for _, size in ICNS_TYPES)})}
    STATIC.mkdir(parents=True, exist_ok=True)
    (STATIC / "icon.svg").write_text(svg(), encoding="utf-8", newline="\n")
    (STATIC / "icon.png").write_bytes(images[256])
    (STATIC / "icon.ico").write_bytes(ico({size: images[size] for size in ICO_SIZES}))
    (STATIC / "icon.icns").write_bytes(icns(images))
    for name in ("icon.svg", "icon.png", "icon.ico", "icon.icns"):
        print(f"{STATIC / name} ({(STATIC / name).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
