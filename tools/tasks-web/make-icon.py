#!/usr/bin/env python3
# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10"]
# ///
"""Write the Corvus icon files into tools/tasks-web/static/.

Run from Work with: uv run tools/tasks-web/make-icon.py

One drawing, defined below, gives four files: `icon.svg` (scalable, also the favicon), `icon.png` (256 px, Linux),
`icon.ico` (16 to 256 px, PNG images inside, Windows) and `icon.icns` (16 to 1024 px, PNG images inside, macOS).
The drawing: a white rounded square on the macOS icon grid with a faint light-grey edge, and a black raven in
flight (Corvus is the Latin name of the ravens and crows), seen from below with its wings spread, filled even-odd and centred. The
PNG files add the soft drop shadow macOS puts under an icon, from 128 px up; the SVG has none.

Provenance: the raven is a silhouette traced with potrace from an image the owner generated, kept below as SVG path
data in a 1000 x 1000 box. No third-party artwork is used.

Every PNG carries a tEXt chunk with ICON_MARKER and the SVG a comment with it: install-app.py
removes an installed icon on --uninstall only when it carries that marker.
"""

from __future__ import annotations

import io
import re
import struct
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter
from PIL.PngImagePlugin import PngInfo

STATIC = Path(__file__).resolve().parent / "static"
ICON_MARKER = "actions-brain-icon"

# Geometry, in units of the icon size (y downwards). The square follows the macOS grid: 824 px in 1024.
MARGIN = 100 / 1024
RADIUS = 185 / 1024
EDGE_COLOR = (0xD6, 0xD6, 0xD6)  # hairline around the white square, 1/512 of the size wide
BIRD_COLOR = (0x11, 0x11, 0x11)
BIRD_WIDTH = 0.74  # the wingspan, as a share of the square's width
BOX = 1000  # the path data lives in a BOX x BOX square, the bird's bounding box centred in it
OVERSAMPLE = 4  # draw at 4x, then shrink with LANCZOS
CURVE_STEPS = 16  # minimum segments per cubic; more on large sizes so 1024 px stays smooth
SHADOW = (0.22, 10 / 1024, 6 / 1024)  # opacity, blur radius and downward offset, in units of the size
SHADOW_FROM = 128  # no shadow below this size

# The raven, in a 1000 x 1000 box: absolute M, L, C and Z commands, one closed subpath.
RAVEN_PATH = (
    "M491.94 728.3C484.16 724.9 479.23 721.55 476.99 718.12C476.19 716.92 475.06 713.03 474.46 709.47"
    "L473.37 703.02L470.75 709.04C467.56 716.36 465.29 718.1 460.1 717.23"
    "C454.94 716.36 444.11 710.79 441.72 707.79C440.04 705.67 439.84 704.53 440.28 699.82"
    "C440.57 696.79 441.64 691.22 442.65 687.44C443.67 683.66 444.51 680.16 444.52 679.65"
    "C444.54 679.15 442.46 682.24 439.91 686.53C433.82 696.77 431.29 699.36 427.39 699.36"
    "C420.25 699.36 410.7 691.71 408.73 684.4C407.61 680.3 408.4 677.32 413.14 667.74L416.31 661.32"
    "L410.95 666.44C400.58 676.36 398.7 677.04 391.11 673.68C382.76 669.99 381.0 662.6 386.21 653.12"
    "L389.29 647.52L382.78 649.71C374.75 652.41 366.64 652.11 363.53 649.0L361.6 647.07L364.17 642.17"
    "C367.93 634.99 374.48 627.44 396.7 604.67C417.31 583.56 424.88 575.32 434.26 563.82L439.76 557.07"
    "L435.58 553.06C433.28 550.85 431.37 549.15 431.33 549.27C431.29 549.4 430.45 551.07 429.47 552.99"
    "C423.33 565.06 408.9 566.8 397.13 556.9L394.38 554.58L393.82 559.32"
    "C393.05 565.83 391.69 566.93 384.55 566.83C377.02 566.72 370.25 563.51 364.42 557.28"
    "C362.07 554.76 360.0 552.7 359.83 552.7C359.65 552.7 359.22 554.24 358.87 556.12"
    "C357.79 561.86 356.91 562.79 352.63 562.77C344.33 562.72 335.81 555.79 330.84 545.06"
    "C329.4 541.96 328.2 540.09 328.18 540.92C328.1 543.9 324.39 554.49 322.92 555.96"
    "C318.8 560.08 303.11 552.35 295.61 542.52L292.1 537.92L290.34 540.71"
    "C287.2 545.66 280.77 546.08 272.54 541.87C267.38 539.23 265.15 536.11 263.91 529.8L262.86 524.49"
    "L258.23 527.37C254.18 529.89 252.79 530.25 247.1 530.25C235.09 530.25 229.15 525.09 229.15 514.66"
    "C229.15 511.52 229.56 506.77 230.07 504.1C230.58 501.43 230.82 499.08 230.62 498.87"
    "C230.41 498.67 228.25 499.51 225.8 500.75C210.59 508.44 194.76 508.7 187.27 501.38"
    "C183.87 498.05 184.04 496.9 188.83 490.82C190.79 488.34 192.31 486.24 192.21 486.15"
    "C192.11 486.06 189.96 486.33 187.44 486.75C180.3 487.94 170.58 487.73 164.29 486.25"
    "C158.39 484.85 148.19 480.21 147.07 478.4C146.49 477.46 151.71 469.21 157.27 462.27L159.6 459.37"
    "L152.44 461.3C142.82 463.9 123.72 464.06 116.93 461.59C110.99 459.43 105.2 455.73 105.62 454.35"
    "C105.8 453.75 109.08 451.19 112.92 448.67C116.75 446.15 120.65 443.58 121.59 442.97"
    "C122.99 442.04 122.57 441.96 119.16 442.51C116.89 442.87 107.81 443.16 98.99 443.15"
    "C81.8 443.14 73.73 441.98 60.49 437.62C53.32 435.26 42.95 429.96 42.43 428.39"
    "C42.26 427.87 46.84 426.75 52.91 425.81C72.24 422.82 97.02 416.08 117.55 408.23"
    "C119.95 407.32 121.9 406.35 121.9 406.08C121.89 405.81 114.16 405.5 104.71 405.4"
    "C68.66 404.99 42.46 400.25 22.37 390.49C14.18 386.51 -0.0 376.63 -0.0 374.9"
    "C-0.0 374.55 3.82 374.99 8.48 375.89C34.93 380.95 60.95 382.8 84.78 381.31"
    "C99.19 380.41 116.98 378.28 117.92 377.34C118.14 377.12 114.9 376.45 110.72 375.84"
    "C71.76 370.19 36.11 355.13 15.28 335.54C8.38 329.04 -0.35 319.02 0.31 318.35"
    "C0.54 318.13 4.91 320.05 10.03 322.61C42.69 339.0 80.34 349.93 114.56 352.96"
    "C127.04 354.06 130.27 353.73 123.86 352.0C110.46 348.39 83.08 334.74 70.12 325.21"
    "C60.56 318.17 46.95 303.97 40.44 294.25C35.43 286.75 29.33 275.95 29.33 274.56"
    "C29.33 274.31 34.38 278.26 40.56 283.34C62.11 301.09 90.21 318.19 114.12 328.11"
    "C136.14 337.25 156.94 340.82 143.22 333.1C109.05 313.89 93.97 300.42 82.22 278.64"
    "C80.46 275.37 78.71 271.67 78.34 270.44C77.74 268.43 78.18 268.62 82.4 272.15"
    "C92.95 280.98 118.79 299.73 130.29 306.89C145.34 316.26 174.52 330.79 193.03 338.13"
    "C212.53 345.87 236.66 352.84 280.1 363.3C292.83 366.36 299.43 368.52 308.51 372.59"
    "C370.86 400.55 380.59 403.92 401.47 404.81C407.77 405.08 416.53 404.93 420.94 404.48"
    "C425.36 404.04 428.96 403.92 428.96 404.22C428.96 404.52 427.42 405.67 425.53 406.76"
    "C421.29 409.22 422.53 409.31 434.46 407.39C444.01 405.86 448.84 403.3 455.96 396.01"
    "C459.86 392.02 459.75 391.5 455.5 393.7C454.01 394.47 452.8 394.86 452.8 394.56"
    "C452.8 394.27 455.32 391.06 458.41 387.44C465.6 378.98 467.81 374.09 470.21 361.25"
    "C472.9 346.84 474.93 341.92 480.78 335.6C485.38 330.64 486.01 329.36 490.26 316.48"
    "C495.32 301.16 498.04 295.14 499.91 295.14C501.48 295.14 503.89 300.79 508.57 315.51"
    "C513.02 329.48 513.34 330.14 518.52 335.73C523.95 341.59 525.74 345.99 528.8 360.96"
    "C531.8 375.59 533.14 378.55 540.7 387.26C543.77 390.79 546.28 394.0 546.28 394.39"
    "C546.29 394.78 545.07 394.47 543.58 393.7C542.1 392.93 540.58 392.3 540.2 392.3"
    "C539.06 392.3 544.64 397.78 549.95 401.88C554.6 405.46 555.77 405.9 564.82 407.37"
    "C575.8 409.16 578.47 408.95 574.01 406.63C572.38 405.78 571.04 404.87 571.04 404.6"
    "C571.04 404.33 576.91 404.39 584.1 404.73C610.35 406.0 624.47 402.27 667.74 382.67"
    "C698.57 368.71 696.6 369.37 753.44 353.79C825.22 334.12 862.27 316.12 910.63 277.43"
    "C915.67 273.4 920.35 269.67 921.03 269.14C924.23 266.67 915.27 283.6 908.88 292.08"
    "C903.41 299.36 891.0 311.17 882.62 317.06C878.87 319.7 870.34 324.97 863.67 328.77"
    "C856.92 332.6 851.78 336.09 852.1 336.6C854.44 340.39 889.55 327.97 912.36 315.28"
    "C928.95 306.06 950.78 290.76 964.54 278.72C967.46 276.16 970.08 274.06 970.34 274.06"
    "C971.1 274.06 963.62 287.59 959.2 294.23C949.55 308.7 933.95 323.34 917.85 333.01"
    "C909.24 338.18 890.53 346.93 880.84 350.31C870.07 354.07 871.98 354.53 889.8 352.48"
    "C923.59 348.6 957.34 338.49 988.31 322.98C994.74 319.76 1000.0 317.47 1000.0 317.88"
    "C1000.0 319.11 988.5 331.51 981.86 337.44C960.9 356.17 929.61 369.19 890.62 375.43"
    "C885.15 376.3 881.23 377.31 881.91 377.67C885.1 379.38 913.54 381.59 932.17 381.57"
    "C953.29 381.54 969.59 380.04 988.31 376.37C994.24 375.21 999.08 374.57 999.08 374.94"
    "C999.08 376.08 992.58 381.4 985.6 385.95C974.1 393.46 954.89 399.59 932.63 402.85"
    "C922.01 404.41 880.99 406.4 878.58 405.48C877.81 405.18 877.18 405.3 877.18 405.75"
    "C877.18 406.66 880.76 408.11 896.43 413.54C910.99 418.6 928.39 422.93 943.89 425.37"
    "C952.1 426.66 956.85 427.8 956.64 428.42C956.46 428.97 953.03 431.16 949.01 433.29"
    "C935.22 440.6 914.45 444.35 893.58 443.3C887.22 442.98 880.62 442.48 878.91 442.18L875.8 441.64"
    "L879.01 443.72C880.77 444.87 885.09 447.63 888.6 449.86L894.98 453.93L892.14 456.46"
    "C890.58 457.86 886.88 459.96 883.92 461.12C879.23 462.98 877.0 463.24 866.18 463.21"
    "C856.74 463.19 852.23 462.75 847.16 461.36C843.5 460.36 840.51 459.69 840.51 459.88"
    "C840.51 460.07 842.54 462.73 845.01 465.79C847.49 468.85 850.24 472.71 851.14 474.38"
    "C852.57 477.03 852.61 477.6 851.45 478.99C849.26 481.64 839.81 485.59 832.86 486.76"
    "C826.53 487.83 813.5 487.47 808.44 486.09C806.38 485.52 806.54 485.9 810.06 489.9"
    "C814.86 495.35 815.68 498.02 813.35 500.59C806.25 508.45 790.07 508.76 775.37 501.34"
    "C772.28 499.78 769.55 498.71 769.3 498.96C769.04 499.21 769.29 501.53 769.85 504.11"
    "C771.35 511.1 771.1 518.76 769.25 522.44C764.95 531.01 750.35 533.08 740.4 526.54"
    "C738.52 525.3 736.76 524.29 736.5 524.29C736.24 524.29 736.02 525.72 736.02 527.48"
    "C736.02 537.19 727.78 544.45 716.75 544.45C712.75 544.45 712.0 544.12 709.78 541.33L707.29 538.21"
    "L704.82 541.61C699.55 548.89 688.6 556.02 681.18 557.02C677.98 557.45 677.35 557.21 675.93 555.04"
    "C675.04 553.68 673.63 549.65 672.79 546.07L671.26 539.57L668.3 545.91"
    "C664.45 554.13 657.94 560.42 651.26 562.36C644.36 564.37 642.14 563.31 640.71 557.34L639.59 552.69"
    "L635.33 557.23C629.67 563.26 622.13 566.72 614.45 566.83C611.07 566.88 608.26 566.45 607.6 565.8"
    "C606.98 565.19 606.29 562.4 606.06 559.61C605.83 556.82 605.44 554.54 605.19 554.54"
    "C604.94 554.54 603.27 555.83 601.47 557.4C596.84 561.47 592.5 563.07 586.01 563.1"
    "C578.94 563.14 574.14 560.29 570.46 553.87C569.09 551.46 567.9 549.4 567.82 549.27"
    "C567.75 549.15 565.78 550.87 563.46 553.1L559.23 557.15L568.93 568.77"
    "C574.27 575.17 589.2 591.18 602.12 604.36C636.41 639.35 641.74 647.07 633.85 650.37"
    "C628.17 652.74 621.55 651.93 610.91 647.56C609.17 646.84 609.15 646.89 610.62 648.56"
    "C612.71 650.95 616.85 659.98 616.86 662.18C616.86 663.15 616.02 665.69 615.0 667.81"
    "C613.52 670.86 612.2 672.07 608.64 673.6C606.17 674.66 603.15 675.53 601.93 675.53"
    "C599.19 675.53 593.99 672.13 588.13 666.5L583.68 662.24L587.05 668.75"
    "C590.53 675.46 591.85 681.08 590.86 685.0C590.0 688.44 584.12 694.99 579.87 697.25"
    "C577.79 698.37 574.48 699.29 572.52 699.32C567.99 699.37 564.94 696.28 558.89 685.55"
    "C556.5 681.3 554.54 678.09 554.54 678.42C554.54 678.76 555.54 682.88 556.78 687.59"
    "C558.82 695.39 559.47 699.82 559.21 704.14C558.82 710.86 537.88 720.8 532.85 716.66"
    "C532.0 715.97 530.0 712.57 528.39 709.12L525.48 702.84L524.99 708.27"
    "C524.31 715.77 521.67 720.49 516.22 723.99C512.09 726.64 501.46 731.45 499.79 731.43"
    "C499.4 731.42 495.87 730.01 491.94 728.3Z"
)


ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_TYPES = ((b"icp4", 16), (b"icp5", 32), (b"ic11", 32), (b"ic12", 64), (b"ic07", 128), (b"ic13", 256),
              (b"ic08", 256), (b"ic14", 512), (b"ic09", 512), (b"ic10", 1024))


def subpaths(data: str, steps: int) -> list[list[tuple[float, float]]]:
    """Polylines of the path data (M, L, C, Z, absolute), each cubic flattened into `steps` segments."""
    out: list[list[tuple[float, float]]] = []
    for command, args in re.findall(r"([MLCZ])([^MLCZ]*)", data):
        numbers = [float(n) for n in re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", args)]
        points = list(zip(numbers[::2], numbers[1::2], strict=True))
        if command == "M":
            out.append([points[0]])
        elif command == "L":
            out[-1].extend(points)
        elif command == "C":
            for (x1, y1), (x2, y2), (x3, y3) in zip(points[0::3], points[1::3], points[2::3], strict=True):
                x0, y0 = out[-1][-1]
                for i in range(1, steps + 1):
                    t = i / steps
                    u = 1 - t
                    out[-1].append((u**3 * x0 + 3 * u * u * t * x1 + 3 * u * t * t * x2 + t**3 * x3,
                                    u**3 * y0 + 3 * u * u * t * y1 + 3 * u * t * t * y2 + t**3 * y3))
    return out


def render(size: int) -> Image.Image:
    """The icon at `size` pixels: the square, its edge and the raven, then the shadow from SHADOW_FROM up."""
    big = size * OVERSAMPLE
    margin, radius, hair = MARGIN * big, RADIUS * big, max(1, round(big / 512))
    square = Image.new("L", (big, big), 0)
    ImageDraw.Draw(square).rounded_rectangle((margin, margin, big - margin, big - margin), radius, fill=255)
    inner = Image.new("L", (big, big), 0)
    ImageDraw.Draw(inner).rounded_rectangle((margin + hair, margin + hair, big - margin - hair, big - margin - hair),
                                            radius - hair, fill=255)
    icon = Image.new("RGBA", (big, big), (0, 0, 0, 0))
    icon.paste(Image.new("RGBA", (big, big), (*EDGE_COLOR, 255)), (0, 0), square)
    icon.paste(Image.new("RGBA", (big, big), (255, 255, 255, 255)), (0, 0), inner)
    # The raven: even-odd fill (xor of the subpaths), scaled into the square and centred.
    side = (big - 2 * margin) * BIRD_WIDTH
    scale, offset = side / BOX, (big - side) / 2
    steps = max(CURVE_STEPS, size // 16)
    mask = Image.new("1", (big, big), 0)
    for poly in subpaths(RAVEN_PATH, steps):
        layer = Image.new("1", (big, big), 0)
        ImageDraw.Draw(layer).polygon([(x * scale + offset, y * scale + offset) for x, y in poly], fill=1)
        mask = ImageChops.logical_xor(mask, layer)
    icon.paste(Image.new("RGBA", (big, big), (*BIRD_COLOR, 255)), (0, 0), mask.convert("L"))
    if size >= SHADOW_FROM:  # macOS-style shadow under the square, inside the canvas (margin 100/1024 is wider than its reach)
        opacity, blur, dy = SHADOW
        cast = Image.new("L", (big, big), 0)
        cast.paste(square.point(lambda v: round(v * opacity)), (0, round(dy * big)))
        cast = cast.filter(ImageFilter.GaussianBlur(blur * big))
        shadow = Image.new("RGBA", (big, big), (0, 0, 0, 0))
        shadow.putalpha(cast)
        icon = Image.alpha_composite(shadow, icon)
    return icon.resize((size, size), Image.LANCZOS)


def png(size: int) -> bytes:
    info = PngInfo()
    info.add_text("Software", f"{ICON_MARKER} (tools/tasks-web/make-icon.py)")
    buffer = io.BytesIO()
    render(size).save(buffer, "PNG", pnginfo=info, optimize=True)
    return buffer.getvalue()


def images() -> dict[int, bytes]:
    return {size: png(size) for size in sorted({*ICO_SIZES, *(size for _, size in ICNS_TYPES)})}


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
    """The same drawing as scalable vector graphics on a 1024 canvas (no shadow: it also serves as the favicon)."""
    def hexa(color: tuple[int, ...]) -> str:
        return "#{:02X}{:02X}{:02X}".format(*color)

    s, m, side = 1024, MARGIN * 1024, (1 - 2 * MARGIN) * 1024
    hair = s / 512
    bird = side * BIRD_WIDTH
    place = f"translate({(s - bird) / 2:g} {(s - bird) / 2:g}) scale({bird / BOX:g})"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1024" height="1024" viewBox="0 0 1024 1024">
  <!-- {ICON_MARKER}: written by tools/tasks-web/make-icon.py -->
  <rect x="{m + hair / 2:g}" y="{m + hair / 2:g}" width="{side - hair:g}" height="{side - hair:g}" rx="{RADIUS * s - hair / 2:g}"
        fill="#FFFFFF" stroke="{hexa(EDGE_COLOR)}" stroke-width="{hair:g}"/>
  <path transform="{place}" fill="{hexa(BIRD_COLOR)}" fill-rule="evenodd" d="{RAVEN_PATH}"/>
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
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "machine"))
    import work_config  # tools/machine/work_config.py

    work_config.utf8_stdio()
    raise SystemExit(main())
