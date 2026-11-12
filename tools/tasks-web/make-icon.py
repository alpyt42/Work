#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Write the Actions Brain icon files into tools/tasks-web/static/ (standard library only).

Run from Work with: uv run tools/tasks-web/make-icon.py

One drawing, defined below, gives four files: `icon.svg` (scalable), `icon.png` (256 px, Linux),
`icon.ico` (16 to 256 px, PNG images inside, Windows) and `icon.icns` (16 to 1024 px, PNG images
inside, macOS). The drawing: a rounded square on the macOS icon grid, filled with a midnight-to-
electric-blue gradient and a soft light from the top left; a small constellation of linked nodes
(the brain, the memory) behind a raised white check mark (the actions). Below 64 px the
constellation and the glows are left out so the check mark stays readable.

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

# Geometry, in units of the icon size (y downwards). The square follows the macOS grid: 824 px in 1024.
MARGIN = 100 / 1024
RADIUS = 185 / 1024
# Background: three stops along the diagonal from the bottom left to the top right.
GRADIENT = ((0x12, 0x0C, 0x3A), (0x3A, 0x2E, 0xB0), (0x22, 0xC3, 0xEE))
LIGHT = ((0.26, 0.18), 0.72, 0.22)  # centre, radius and strength of the white light on the background
RIM = 0.006  # width of the thin light rim inside the square's edge
# The constellation: nodes (x, y, radius) and the links between them.
NODES = ((0.29, 0.38, 0.016), (0.37, 0.26, 0.020), (0.50, 0.20, 0.017), (0.63, 0.24, 0.020),
         (0.72, 0.35, 0.015), (0.49, 0.34, 0.026), (0.38, 0.47, 0.014))
LINKS = ((0, 1), (1, 2), (2, 3), (3, 4), (1, 5), (5, 2), (5, 3), (0, 5), (5, 6), (0, 6), (4, 5))
LINK_WIDTH = 0.007
LINK_COLOR, LINK_ALPHA = (0xB8, 0xE4, 0xFF), 0.55
NODE_COLOR, NODE_GLOW = (0xE6, 0xF2, 0xFF), 0.050
# The check mark: polyline, stroke width, colours from left to right, and its shadow.
CHECK = ((0.30, 0.565), (0.45, 0.715), (0.765, 0.40))
STROKE = 0.105
CHECK_LEFT, CHECK_RIGHT = (0xFF, 0xFF, 0xFF), (0xBF, 0xF0, 0xFF)
CHECK_GLOW = ((0x7D, 0xE3, 0xFF), 0.065, 0.28)  # colour, reach and strength of the light under the check
CHECK_SHADOW = (0.018, 0.040, 0.32)  # downward offset, blur and strength
SQUARE_SHADOW = (0.010, 0.030, 0.30)
SMALL = 64  # below this size: the simplified drawing (no constellation, no glow)

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_TYPES = ((b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"ic12", 64), (b"ic07", 128), (b"ic13", 256),
              (b"ic08", 256), (b"ic14", 512), (b"ic09", 512), (b"ic10", 1024))


def square_distance(x: float, y: float) -> float:
    """Signed distance (negative inside) from (x, y) to the rounded square."""
    half = 0.5 - MARGIN
    qx = abs(x - 0.5) - (half - RADIUS)
    qy = abs(y - 0.5) - (half - RADIUS)
    return math.hypot(max(qx, 0.0), max(qy, 0.0)) + min(max(qx, qy), 0.0) - RADIUS


def segment_distance(x: float, y: float, a: tuple[float, float], b: tuple[float, float]) -> float:
    (ax, ay), (bx, by) = a, b
    dx, dy = bx - ax, by - ay
    t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(x - ax - t * dx, y - ay - t * dy)


def check_distance(x: float, y: float, stroke: float) -> float:
    return min(segment_distance(x, y, a, b) for a, b in pairwise(CHECK)) - stroke / 2


def mix(a: tuple[float, ...], b: tuple[float, ...], t: float) -> tuple[float, ...]:
    return tuple(u + (v - u) * t for u, v in zip(a, b, strict=True))


def coverage(distance: float, pixel: float) -> float:
    """Anti-aliased coverage of a shape from its signed distance, over one pixel."""
    return min(1.0, max(0.0, 0.5 - distance / pixel))


def falloff(distance: float, reach: float) -> float:
    """Soft glow or shadow: 1 at the shape, 0 at `reach` beyond it."""
    return max(0.0, 1.0 - max(distance, 0.0) / reach) ** 2


def background(x: float, y: float) -> tuple[float, ...]:
    t = min(1.0, max(0.0, (x - y + 1.0) / 2.0))
    color = mix(GRADIENT[0], GRADIENT[1], t / 0.5) if t < 0.5 else mix(GRADIENT[1], GRADIENT[2], (t - 0.5) / 0.5)
    (cx, cy), reach, strength = LIGHT
    light = strength * max(0.0, 1.0 - math.hypot(x - cx, y - cy) / reach) ** 2
    return mix(color, (255.0, 255.0, 255.0), light)


def pixel_color(x: float, y: float, pixel: float, detailed: bool) -> tuple[float, float, float, float]:
    """Premultiplied RGBA (0-255 colour, 0-1 alpha) of the drawing at (x, y)."""
    r = g = b = a = 0.0

    def over(color: tuple[float, ...], alpha: float) -> None:
        nonlocal r, g, b, a
        if alpha <= 0.0:
            return
        r, g, b = (c * alpha + d * (1.0 - alpha) for c, d in zip(color, (r, g, b), strict=True))
        a = alpha + a * (1.0 - alpha)

    edge = square_distance(x, y)
    inside = coverage(edge, pixel)
    if detailed and inside < 1.0:  # the square's own shadow, outside it
        offset, reach, strength = SQUARE_SHADOW
        over((0.0, 0.0, 0.0), strength * falloff(square_distance(x, y - offset), reach) * (1.0 - inside))
    if inside <= 0.0:
        return r, g, b, a
    over(background(x, y), inside)
    if detailed and edge > -RIM:  # thin light rim along the inside of the edge
        over((255.0, 255.0, 255.0), 0.10 * inside * (1.0 - max(0.0, -edge) / RIM))
    if detailed and 0.19 < x < 0.77 and 0.13 < y < 0.53:
        for i, j in LINKS:
            d = segment_distance(x, y, NODES[i][:2], NODES[j][:2]) - LINK_WIDTH / 2
            over(LINK_COLOR, LINK_ALPHA * coverage(d, pixel) * inside)
        for nx, ny, radius in NODES:
            d = math.hypot(x - nx, y - ny) - radius
            over(NODE_COLOR, 0.30 * falloff(d, NODE_GLOW) * inside)
            over(NODE_COLOR, coverage(d, pixel) * inside)
    stroke = STROKE if detailed else STROKE * 1.25
    offset, reach, strength = CHECK_SHADOW
    if detailed:
        glow, glow_reach, glow_strength = CHECK_GLOW
        over(glow, glow_strength * falloff(check_distance(x, y, stroke), glow_reach) * inside)
        over((0.0, 0.0, 0.0), strength * falloff(check_distance(x, y - offset, stroke), reach) * inside)
    t = min(1.0, max(0.0, (x - CHECK[0][0]) / (CHECK[-1][0] - CHECK[0][0])))
    over(mix(CHECK_LEFT, CHECK_RIGHT, t), coverage(check_distance(x, y, stroke), pixel) * inside)
    return r, g, b, a


def raster(size: int, detailed: bool, oversample: int = 1) -> list[list[tuple[float, ...]]]:
    """Premultiplied RGBA pixels at `size`, averaged from `oversample`² samples each."""
    full = size * oversample
    pixel = 1.0 / full
    samples = [[pixel_color((column + 0.5) / full, (row + 0.5) / full, pixel, detailed) for column in range(full)]
               for row in range(full)]
    return shrink(samples, oversample) if oversample > 1 else samples


def shrink(pixels: list[list[tuple[float, ...]]], factor: int) -> list[list[tuple[float, ...]]]:
    """Box-filter premultiplied pixels down by an integer factor."""
    size = len(pixels) // factor
    count = factor * factor
    out = []
    for row in range(size):
        line = []
        for column in range(size):
            total = [0.0, 0.0, 0.0, 0.0]
            for dy in range(factor):
                source = pixels[row * factor + dy]
                for dx in range(factor):
                    for k, value in enumerate(source[column * factor + dx]):
                        total[k] += value
            line.append(tuple(value / count for value in total))
        out.append(line)
    return out


def encode(pixels: list[list[tuple[float, ...]]]) -> bytes:
    """Straight 8-bit RGBA rows, each prefixed by PNG filter 0."""
    rows = bytearray()
    for line in pixels:
        rows.append(0)
        for r, g, b, a in line:
            if a <= 0.0:
                rows += b"\0\0\0\0"
                continue
            rows += bytes((*(min(255, max(0, round(c / a))) for c in (r, g, b)), min(255, round(a * 255))))
    return bytes(rows)


def chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def png(pixels: list[list[tuple[float, ...]]]) -> bytes:
    size = len(pixels)
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)  # 8-bit RGBA, no interlace
    text = b"Software\0" + f"{ICON_MARKER} (tools/tasks-web/make-icon.py)".encode("ascii")
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"tEXt", text)
            + chunk(b"IDAT", zlib.compress(encode(pixels), 9)) + chunk(b"IEND", b""))


def images() -> dict[int, bytes]:
    """Every size once: the large ones shrunk from one 1024 px drawing, the small ones drawn simplified."""
    sizes = sorted({*ICO_SIZES, *(size for _, size in ICNS_TYPES)})
    large = raster(1024, detailed=True)
    out = {}
    for size in sizes:
        out[size] = png(large if size == 1024 else shrink(large, 1024 // size) if size >= SMALL
                        else raster(size, detailed=False, oversample=4))
    return out


def ico(pngs: dict[int, bytes]) -> bytes:
    """An ICO file whose entries are PNG images (read by Windows Vista and later)."""
    sizes = sorted(pngs)
    offset = 6 + 16 * len(sizes)
    directory, payload = b"", b""
    for size in sizes:
        data = pngs[size]
        side = 0 if size >= 256 else size  # 0 means 256 in an ICO directory entry
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(data), offset + len(payload))
        payload += data
    return struct.pack("<HHH", 0, 1, len(sizes)) + directory + payload


def icns(pngs: dict[int, bytes]) -> bytes:
    body = b"".join(kind + struct.pack(">I", 8 + len(pngs[size])) + pngs[size] for kind, size in ICNS_TYPES)
    return b"icns" + struct.pack(">I", 8 + len(body)) + body


def svg() -> str:
    """The same drawing as scalable vector graphics, on a 1024 canvas."""
    def hexa(color: tuple[int, ...]) -> str:
        return "#{:02X}{:02X}{:02X}".format(*color)

    s, m, side = 1024, MARGIN * 1024, (1 - 2 * MARGIN) * 1024
    (lx, ly), reach, strength = LIGHT
    links = "\n".join(f'    <line x1="{NODES[i][0] * s:g}" y1="{NODES[i][1] * s:g}" x2="{NODES[j][0] * s:g}" '
                      f'y2="{NODES[j][1] * s:g}"/>' for i, j in LINKS)
    nodes = "\n".join(f'    <circle cx="{x * s:g}" cy="{y * s:g}" r="{radius * s:g}"/>' for x, y, radius in NODES)
    points = " ".join(f"{x * s:g},{y * s:g}" for x, y in CHECK)
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <!-- {ICON_MARKER}: written by tools/tasks-web/make-icon.py -->
  <defs>
    <linearGradient id="back" x1="0" y1="1" x2="1" y2="0">
      <stop offset="0" stop-color="{hexa(GRADIENT[0])}"/>
      <stop offset="0.5" stop-color="{hexa(GRADIENT[1])}"/>
      <stop offset="1" stop-color="{hexa(GRADIENT[2])}"/>
    </linearGradient>
    <radialGradient id="light" cx="{lx * s:g}" cy="{ly * s:g}" r="{reach * s:g}" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="#FFFFFF" stop-opacity="{strength:g}"/>
      <stop offset="1" stop-color="#FFFFFF" stop-opacity="0"/>
    </radialGradient>
    <linearGradient id="check" x1="{CHECK[0][0] * s:g}" y1="0" x2="{CHECK[-1][0] * s:g}" y2="0" gradientUnits="userSpaceOnUse">
      <stop offset="0" stop-color="{hexa(CHECK_LEFT)}"/>
      <stop offset="1" stop-color="{hexa(CHECK_RIGHT)}"/>
    </linearGradient>
    <filter id="shadow" x="-20%" y="-20%" width="140%" height="140%">
      <feDropShadow dx="0" dy="{CHECK_SHADOW[0] * s:g}" stdDeviation="{CHECK_SHADOW[1] * s / 3:g}" flood-color="#000000" flood-opacity="{CHECK_SHADOW[2]:g}"/>
    </filter>
    <filter id="glow" x="-100%" y="-100%" width="300%" height="300%">
      <feGaussianBlur stdDeviation="{NODE_GLOW * s / 3:g}"/>
    </filter>
    <filter id="lift" x="-10%" y="-10%" width="120%" height="125%">
      <feDropShadow dx="0" dy="{SQUARE_SHADOW[0] * s:g}" stdDeviation="{SQUARE_SHADOW[1] * s / 3:g}" flood-color="#000000" flood-opacity="{SQUARE_SHADOW[2]:g}"/>
    </filter>
  </defs>
  <g filter="url(#lift)">
    <rect x="{m:g}" y="{m:g}" width="{side:g}" height="{side:g}" rx="{RADIUS * s:g}" fill="url(#back)"/>
  </g>
  <rect x="{m:g}" y="{m:g}" width="{side:g}" height="{side:g}" rx="{RADIUS * s:g}" fill="url(#light)"/>
  <rect x="{m + RIM * s / 2:g}" y="{m + RIM * s / 2:g}" width="{side - RIM * s:g}" height="{side - RIM * s:g}" rx="{(RADIUS - RIM / 2) * s:g}" fill="none" stroke="#FFFFFF" stroke-opacity="0.10" stroke-width="{RIM * s:g}"/>
  <g stroke="{hexa(LINK_COLOR)}" stroke-opacity="{LINK_ALPHA:g}" stroke-width="{LINK_WIDTH * s:g}" stroke-linecap="round">
{links}
  </g>
  <g fill="{hexa(NODE_COLOR)}" opacity="0.30" filter="url(#glow)">
{nodes}
  </g>
  <g fill="{hexa(NODE_COLOR)}">
{nodes}
  </g>
  <polyline points="{points}" fill="none" stroke="url(#check)" stroke-width="{STROKE * s:g}" stroke-linecap="round" stroke-linejoin="round" filter="url(#shadow)"/>
</svg>
"""


def main() -> int:
    pngs = images()
    STATIC.mkdir(parents=True, exist_ok=True)
    (STATIC / "icon.svg").write_text(svg(), encoding="utf-8", newline="\n")
    (STATIC / "icon.png").write_bytes(pngs[256])
    (STATIC / "icon.ico").write_bytes(ico({size: pngs[size] for size in ICO_SIZES}))
    (STATIC / "icon.icns").write_bytes(icns(pngs))
    for name in ("icon.svg", "icon.png", "icon.ico", "icon.icns"):
        print(f"{STATIC / name} ({(STATIC / name).stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
