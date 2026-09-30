"""Save Excel reports atomically, including when an existing report is open."""
import logging
import tempfile
from datetime import datetime
from pathlib import Path


def save_excel_report(frame, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=f"{destination.stem}_{stamp}_",
        suffix=".xlsx", delete=False,
    ) as handle:
        temporary = Path(handle.name)
    try:
        frame.to_excel(temporary, index=False, engine="openpyxl")
        try:
            temporary.replace(destination)
        except PermissionError:
            logging.getLogger("restaurant_image_downloader").warning(
                "Cannot replace report %s (it may be open in Excel). Saved new report: %s",
                destination, temporary,
            )
            return temporary
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return destination
