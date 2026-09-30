"""Conservative local enhancement; originals are never overwritten."""
import argparse
import json
import logging
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

BASE_DIR = Path(__file__).resolve().parent


def enhance_image(source: Path, destination: Path, long_edge: int = 2400, wide: bool = False):
    if source.resolve() == destination.resolve():
        raise ValueError("Enhanced output must be separate from the original.")
    if not 0 <= long_edge <= 8192:
        raise ValueError("long_edge must be between 0 and 8192; 0 keeps original size.")
    with Image.open(source) as original:
        picture = ImageOps.exif_transpose(original).convert("RGB")
        before = picture.size
        # Blend a small amount of contrast correction to avoid harsh colors.
        corrected = ImageOps.autocontrast(picture, cutoff=0.2, preserve_tone=True)
        picture = Image.blend(picture, corrected, 0.25)
        picture = ImageEnhance.Contrast(picture).enhance(1.03)
        # Enlargement is interpolation, not recovered detail. Never downscale
        # a larger original or enlarge a tiny photo by more than 2x.
        if wide:
            scale = min(2.0, 2560 / picture.width, 1440 / picture.height)
        else:
            scale = max(1.0, min(2.0, long_edge / max(picture.size)))
        if scale != 1:
            picture = picture.resize(
                tuple(max(1, round(dimension * scale)) for dimension in picture.size),
                Image.Resampling.LANCZOS,
            )
        picture = picture.filter(ImageFilter.UnsharpMask(radius=1.2, percent=85, threshold=3))
        if wide:
            canvas = Image.new("RGB", (2560, 1440), (24, 24, 24))
            canvas.paste(picture, ((2560 - picture.width) // 2, (1440 - picture.height) // 2))
            picture = canvas
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(".tmp")
        picture.save(temporary, format="JPEG", quality=97, subsampling=0, optimize=True)
        temporary.replace(destination)
        return {"original_size": before, "enhanced_size": picture.size}


def enhance_selected(long_edge: int = 2400, wide: bool = False):
    logger = logging.getLogger("restaurant_image_downloader")
    source_root = BASE_DIR / "Selected_Restaurant_Images"
    output_root = BASE_DIR / ("Enhanced_Restaurant_Images_16x9" if wide else "Enhanced_Restaurant_Images")
    photos = sorted(source_root.glob("*/*.jpg"))
    if not photos:
        logger.warning("No verified selected photos available for enhancement.")
    records = []
    for source in photos:
        target = output_root / source.relative_to(source_root)
        try:
            dimensions = enhance_image(source, target, long_edge, wide=wide)
            records.append({"source": str(source), "output": str(target), "status": "SUCCESS", **dimensions})
        except (OSError, ValueError) as exc:
            logger.warning("Enhancement failed for %s: %s", source.name, exc)
            records.append({"source": str(source), "status": "ERROR", "error": str(exc)})
    # Clear only generated slot files that no longer exist in the selection.
    generated_names = {f"{slot}_{category}.jpg" for slot in (1, 2, 3) for category in ("ambience", "food")}
    for existing in output_root.glob("*/*.jpg"):
        if existing.name in generated_names and not (source_root / existing.relative_to(output_root)).exists():
            existing.unlink()
    report = BASE_DIR / "output" / ("enhancement_report_16x9.json" if wide else "enhancement_report.json")
    report.parent.mkdir(exist_ok=True)
    report.write_text(json.dumps(records, indent=2), encoding="utf-8")
    succeeded = sum(record["status"] == "SUCCESS" for record in records)
    logger.info("Enhanced %s/%s photos: %s", succeeded, len(records), output_root)
    return records


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wide", action="store_true",
                        help="Export 2560x1440 (16:9) with dark padding; overrides --long-edge.")
    parser.add_argument("--long-edge", type=int, default=2400,
                        help="Target longest edge, capped at 2x enlargement. 0 keeps original size.")
    args = parser.parse_args()
    if not 0 <= args.long_edge <= 8192:
        parser.error("--long-edge must be between 0 and 8192")
    results = enhance_selected(args.long_edge, wide=args.wide)
    raise SystemExit(1 if any(item["status"] == "ERROR" for item in results) else 0)
