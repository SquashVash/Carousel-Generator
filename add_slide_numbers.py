"""
add_slide_numbers.py

Usage:
    python add_slide_numbers.py <run_folder>

Reads every composited PNG from <run_folder>/composited/ (sorted),
counts them, then stamps a neon-green slide-number label
(e.g. "1/9", "2/9") in the top-left corner of each image.
Files are overwritten in place.
"""

import sys
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# ── Style constants ──────────────────────────────────────────────────────────
NEON_GREEN   = (109, 255, 47)   # #6DFF2F default
SHADOW_COLOR = (0, 0, 0, 180)   # subtle dark drop-shadow for legibility
PADDING      = 28               # px inset from the top-left corner
FONT_SIZE    = 42               # px — adjust if needed


def hex_to_rgb(hex_color: str) -> tuple:
    """Convert a hex color string like '#6DFF2F' to an (R, G, B) tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (0, 2, 4))

# Tried in order; first one that loads wins
FONT_CANDIDATES = [
    "arialbd.ttf",            # Arial Bold (Windows)
    "Arial Bold.ttf",
    "Impact.ttf",
    "DejaVuSans-Bold.ttf",
    "LiberationSans-Bold.ttf",
]

SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}
# ────────────────────────────────────────────────────────────────────────────


def load_font(size: int) -> ImageFont.ImageFont:
    for name in FONT_CANDIDATES:
        try:
            return ImageFont.truetype(name, size)
        except (OSError, IOError):
            continue
    # Ultimate fallback: PIL's built-in bitmap font (ignores size)
    print("  Warning: no TrueType font found — using PIL default bitmap font.")
    return ImageFont.load_default()


def stamp_label(image_path: Path, label: str, font: ImageFont.ImageFont, accent_rgb: tuple = NEON_GREEN) -> None:
    img = Image.open(image_path).convert("RGBA")
    draw = ImageDraw.Draw(img)

    x, y = PADDING, PADDING

    # Drop shadow (1 px offset in each diagonal direction for crispness)
    for dx, dy in ((2, 2), (2, -2), (-2, 2), (-2, -2)):
        draw.text((x + dx, y + dy), label, font=font, fill=SHADOW_COLOR)

    # Accent-colored label
    draw.text((x, y), label, font=font, fill=(*accent_rgb, 255))

    img.save(image_path)
    print(f"  Labeled: {image_path.name}  →  {label}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stamp slide numbers onto composited images.")
    parser.add_argument("run_folder", nargs="?", help="Path to the run folder")
    parser.add_argument("--color", default=None,
                        help="Hex accent color for the slide number (e.g. '#6DFF2F')")
    args = parser.parse_args()

    if args.run_folder:
        folder = args.run_folder
    else:
        folder = input("Enter the run folder path: ").strip().strip('"')

    accent_rgb = hex_to_rgb(args.color) if args.color else NEON_GREEN

    run_folder = Path(folder)
    composited_dir = run_folder / "composited"

    if not composited_dir.is_dir():
        print(f"Error: composited folder not found at '{composited_dir}'")
        sys.exit(1)

    images = sorted(
        f for f in composited_dir.iterdir()
        if f.suffix.lower() in SUPPORTED
    )

    if not images:
        print("No images found in composited folder.")
        sys.exit(0)

    total = len(images)
    font  = load_font(FONT_SIZE)

    print(f"Stamping slide numbers on {total} image(s) in: {composited_dir}\n")

    for i, img_path in enumerate(images):
        stamp_label(img_path, f"{i + 1}/{total}", font, accent_rgb)

    print(f"\nDone! {total} image(s) numbered.")


if __name__ == "__main__":
    main()
