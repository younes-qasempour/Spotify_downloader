import os
import sys
from pathlib import Path
from PIL import Image


def convert_image_to_icon(input_image_path: str, output_ico_path: str, output_png_path: str = ""):
    """
    Converts any source image (PNG, JPG, WEBP) into a multi-resolution Windows .ico file
    containing crisp icon sizes: 256x256, 128x128, 64x64, 48x48, 32x32, 16x16.
    Also optionally exports a high-resolution 256x256 PNG for window headers.
    """
    input_p = Path(input_image_path).resolve()
    if not input_p.exists():
        raise FileNotFoundError(f"Source image not found: {input_p}")

    print(f"Loading source image: {input_p}")
    img = Image.open(str(input_p))

    # Convert to RGBA for clean transparency/color presentation
    if img.mode != "RGBA":
        img = img.convert("RGBA")

    out_ico = Path(output_ico_path).resolve()
    out_ico.parent.mkdir(parents=True, exist_ok=True)

    # Windows standard icon sizes
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]

    print(f"Generating multi-resolution .ico at {out_ico} with sizes: {sizes}...")
    img.save(str(out_ico), format="ICO", sizes=sizes)
    print(f"[OK] Saved {out_ico} ({os.path.getsize(out_ico):,} bytes)")

    if output_png_path:
        out_png = Path(output_png_path).resolve()
        resized_256 = img.resize((256, 256), Image.Resampling.LANCZOS)
        resized_256.save(str(out_png), format="PNG")
        print(f"[OK] Saved {out_png} ({os.path.getsize(out_png):,} bytes)")


if __name__ == "__main__":
    assets_dir = Path(__file__).resolve().parent
    repo_root = assets_dir.parent

    # Candidate source image files in order of priority:
    # 1. assets/image_0.png
    # 2. repo_root/image_0.png
    # 3. repo_root/Icon.jpg / Icon.jpeg
    candidates = [
        assets_dir / "image_0.png",
        repo_root / "image_0.png",
        repo_root / "Icon.jpg",
        repo_root / "Icon.jpeg",
        repo_root / "Icon.png",
    ]

    # Allow custom CLI argument: python assets/convert_icon.py path/to/my_image.png
    if len(sys.argv) > 1:
        candidates.insert(0, Path(sys.argv[1]))

    chosen = None
    for cand in candidates:
        if cand.exists() and cand.is_file():
            chosen = cand
            break

    if not chosen:
        print("❌ Error: No source image found! Looked for:")
        for cand in candidates:
            print(f"  - {cand}")
        print("\nUsage:")
        print("  python assets/convert_icon.py <path_to_image_0.png>")
        sys.exit(1)

    target_ico = assets_dir / "icon.ico"
    target_png = assets_dir / "icon.png"
    convert_image_to_icon(str(chosen), str(target_ico), str(target_png))
