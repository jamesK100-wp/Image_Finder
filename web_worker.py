"""Run each uploaded workbook in its own output directory and process."""
import functools
import sys
from pathlib import Path

import download_images as downloader
import enhance_photos
import select_photos


def run(folder, wide=True):
    root = Path(folder).resolve()
    select_photos.BASE_DIR = root
    enhance_photos.BASE_DIR = root
    if wide:
        enhance_photos.enhance_selected = functools.partial(enhance_photos.enhance_selected, wide=True)
    for name, relative in {
        "OUTPUT_FOLDER": "Restaurant_Images",
        "PROGRESS_FILE": "progress/progress.json",
        "REPORT_FILE": "output/image_download_report.xlsx",
        "FAILED_FILE": "output/failed_restaurants.xlsx",
        "LOG_FILE": "logs/downloader.log",
    }.items():
        setattr(downloader, name, str(root / relative))
    downloader.LOGGER = downloader.setup_logging()
    sys.argv = ["download_images.py", "--input", str(root / "input.xlsx"), "--workers", "3"]
    downloader.main()


if __name__ == "__main__":
    run(sys.argv[1], sys.argv[2] == "wide")
