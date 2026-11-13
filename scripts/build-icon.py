from io import BytesIO
from pathlib import Path
import struct

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
PUBLIC = ROOT / "frontend" / "public"
source = Image.open(ASSETS / "pocketpc-icon-source.png").convert("RGBA")

# The generated artwork includes a small white outer margin. Crop it so the
# Windows icon uses the available tile while preserving the rounded square.
width, height = source.size
margin = round(min(width, height) * 0.025)
source = source.crop((margin, margin, width - margin, height - margin))
# Make only the connected near-white canvas around the rounded tile transparent.
# Highlights inside the artwork are preserved because they are not edge-connected.
for corner in ((0, 0), (source.width - 1, 0), (0, source.height - 1), (source.width - 1, source.height - 1)):
    ImageDraw.floodfill(source, corner, (255, 255, 255, 0), thresh=24)

# Remove the near-transparent white glow left by the original canvas. It is
# harmless at full size but makes the Windows taskbar icon look soft.
alpha = source.getchannel("A").point(lambda value: 0 if value <= 28 else round((value - 28) * 255 / 227))
source.putalpha(alpha)


def flat_small_icon(size):
    """Preserve the exact PocketPC mark but flatten details that blur when tiny."""
    frame = source.resize((size, size), Image.Resampling.LANCZOS)
    frame_alpha = frame.getchannel("A").point(
        lambda value: 0 if value < 40 else (255 if value > 220 else value)
    )
    rgb = ImageEnhance.Contrast(frame.convert("RGB")).enhance(1.18)
    rgb = rgb.filter(ImageFilter.UnsharpMask(radius=0.45, percent=220, threshold=1))
    # A small fixed palette removes the original glossy gradients while
    # retaining the actual P-shaped monitor and centered phone silhouette.
    rgb = rgb.quantize(
        colors=7, method=Image.Quantize.FASTOCTREE, dither=Image.Dither.NONE
    ).convert("RGB")
    frame = rgb.convert("RGBA")
    frame.putalpha(frame_alpha)
    return frame


def icon_frame(size):
    """Use a flat taskbar mark at small sizes and detailed art when enlarged."""
    if size <= 48:
        return flat_small_icon(size)
    return source.resize((size, size), Image.Resampling.LANCZOS)


def save_png_ico(path, sizes):
    """Write dedicated PNG-compressed ICO frames instead of auto-scaled ones."""
    payloads = []
    for size in sizes:
        stream = BytesIO()
        icon_frame(size).save(stream, format="PNG", optimize=True)
        payloads.append((size, stream.getvalue()))

    header_size = 6 + 16 * len(payloads)
    offset = header_size
    directory = []
    for size, payload in payloads:
        dimension = 0 if size == 256 else size
        directory.append(struct.pack(
            "<BBBBHHII", dimension, dimension, 0, 0, 1, 32, len(payload), offset
        ))
        offset += len(payload)

    path.write_bytes(
        struct.pack("<HHH", 0, 1, len(payloads)) + b"".join(directory) +
        b"".join(payload for _size, payload in payloads)
    )


icon_frame(256).save(ASSETS / "pocketpc-icon.png", optimize=True)
icon_frame(64).save(ASSETS / "pocketpc-icon-64.png", optimize=True)
icon_frame(24).save(ASSETS / "pocketpc-icon-24.png", optimize=True)
icon_frame(32).save(ASSETS / "pocketpc-icon-32.png", optimize=True)
save_png_ico(ASSETS / "pocketpc.ico", (16, 20, 24, 32, 40, 48, 64, 128, 256))

# iOS uses apple-touch-icon for Home Screen web apps. Keep these icons
# opaque so iOS does not substitute a generated letter tile or alter the
# transparent corners unpredictably.
PUBLIC.mkdir(parents=True, exist_ok=True)
for size, filename in (
    (180, "apple-touch-icon.png"),
    (192, "pocketpc-app-192.png"),
    (512, "pocketpc-app-512.png"),
):
    canvas = Image.new("RGBA", (size, size), "#101820")
    inset = round(size * 0.04)
    icon = source.resize((size - inset * 2, size - inset * 2), Image.Resampling.LANCZOS)
    canvas.alpha_composite(icon, (inset, inset))
    canvas.convert("RGB").save(PUBLIC / filename, optimize=True)
