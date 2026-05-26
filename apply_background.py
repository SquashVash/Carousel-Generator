"""
apply_background.py

Usage:
    python apply_background.py <folder>

Goes over every PNG/JPG in <folder>, composites assets/Background.png
behind each one, and saves the result back into a `composited/` subfolder
inside that same folder.
"""

import sys
from pathlib import Path
from PIL import Image


ASSETS_DIR = Path(__file__).parent / "assets"
BACKGROUND_PATH = ASSETS_DIR / "Background.png"

SUPPORTED = {".png", ".jpg", ".jpeg", ".webp"}


def apply_background(image_path: Path, background: Image.Image, out_dir: Path):
    img = Image.open(image_path).convert("RGBA")

    # Resize background to match the slide if needed
    if background.size != img.size:
        bg = background.resize(img.size, Image.LANCZOS)
    else:
        bg = background.copy()

    # Composite: paste the slide on top of the background
    bg.paste(img, (0, 0), mask=img)

    out_path = out_dir / image_path.name
    bg.convert("RGB").save(out_path)
    print(f"  Saved: {out_path}")


def main():
    if len(sys.argv) < 2:
        folder = input("Enter the run folder path: ").strip().strip('"')
    else:
        folder = sys.argv[1]

    folder = Path(folder)
    if not folder.is_dir():
        print(f"Error: '{folder}' is not a valid directory.")
        sys.exit(1)

    # Optional second argument: custom background image path
    if len(sys.argv) >= 3:
        bg_path = Path(sys.argv[2])
    else:
        bg_path = BACKGROUND_PATH

    if not bg_path.exists():
        print(f"Error: background not found at '{bg_path}'")
        sys.exit(1)

    background = Image.open(bg_path).convert("RGBA")

    images = [f for f in sorted(folder.iterdir()) if f.suffix.lower() in SUPPORTED]
    if not images:
        print("No images found in the folder.")
        sys.exit(0)

    out_dir = folder / "composited"
    out_dir.mkdir(exist_ok=True)

    print(f"Processing {len(images)} image(s) from: {folder}")
    print(f"Output folder: {out_dir}\n")

    for img_path in images:
        apply_background(img_path, background, out_dir)

    print(f"\nDone! {len(images)} image(s) composited.")


if __name__ == "__main__":
    main()
