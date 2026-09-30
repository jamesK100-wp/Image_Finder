"""Select two ambience images and one food image using a local CLIP model."""
import hashlib
import json
import logging
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
MODEL_ID = "openai/clip-vit-base-patch32"
MODEL_CACHE_DIR = Path(os.environ.get("DATA_DIR", str(BASE_DIR))) / ".model_cache"
PROMPTS = {
    "ambience": [
        "a photo of restaurant seating arrangements with dining tables and chairs",
        "a photo of restaurant booths and seats around dining tables",
        "a photo of a cafe seating area with tables and chairs",
    ],
    "food": [
        "a close-up photo of cooked food on a plate",
        "a photo of sweets, snacks, cakes or ice cream",
        "a close-up photo of a drink or beverage",
    ],
    "other": [
        "a photo of a restaurant exterior, entrance, storefront or building facade",
        "a photo of a restaurant signboard",
        "a photo of ceiling decorations or a wall without seating",
        "a photo of a printed restaurant menu or price list",
        "a graphic advertisement, logo or promotional poster",
        "a selfie or portrait of people",
        "a photo of a receipt, document or screenshot",
    ],
}
CACHE_VERSION = hashlib.sha256(json.dumps(PROMPTS, sort_keys=True).encode()).hexdigest()[:16]


def choose_photos(candidates):
    """Prefer two seating photos; fill remaining slots with distinct food photos."""
    seating = sorted((x for x in candidates if x["category"] == "ambience"),
                     key=lambda x: x["score"], reverse=True)[:2]
    food = sorted((x for x in candidates if x["category"] == "food"),
                  key=lambda x: x["score"], reverse=True)
    selected = list(enumerate(seating, start=1))
    selected.extend(zip(range(len(seating) + 1, 4), food))
    return selected


class PhotoClassifier:
    def __init__(self):
        # Keep model downloads inside this project, not the user's global cache.
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        import torch
        from transformers import CLIPModel, CLIPProcessor
        self.torch = torch
        torch.set_num_threads(min(4, os.cpu_count() or 1))
        cache_dir = str(MODEL_CACHE_DIR)
        self.processor = CLIPProcessor.from_pretrained(MODEL_ID, cache_dir=cache_dir, use_fast=False)
        self.model = CLIPModel.from_pretrained(
            MODEL_ID, cache_dir=cache_dir, use_safetensors=True,
        ).eval()
        self.labels = [label for label, prompts in PROMPTS.items() for _ in prompts]
        self.prompts = [prompt for prompts in PROMPTS.values() for prompt in prompts]

    def classify(self, path):
        from PIL import Image, ImageOps
        with Image.open(path) as source:
            picture = ImageOps.exif_transpose(source).convert("RGB")
            inputs = self.processor(text=self.prompts, images=picture, return_tensors="pt", padding=True)
        with self.torch.inference_mode():
            logits = self.model(**inputs).logits_per_image[0]
        # Compare the best matching description in each category.
        scores = self.torch.stack([
            logits[[i for i, label in enumerate(self.labels) if label == category]].max()
            for category in PROMPTS
        ]).softmax(dim=0).tolist()
        ranked = sorted(zip(PROMPTS, scores), key=lambda item: item[1], reverse=True)
        category, score = ranked[0]
        if score < 0.65 or score - ranked[1][1] < 0.20:
            category = "uncertain"
        return {"category": category, "score": round(score, 4)}


def select_all(progress):
    import pandas as pd
    from PIL import Image, ImageOps
    logger = logging.getLogger("restaurant_image_downloader")
    output = BASE_DIR / "Selected_Restaurant_Images"
    output.mkdir(exist_ok=True)
    cache_path = BASE_DIR / "progress/photo_classifications.json"
    cache_path.parent.mkdir(exist_ok=True)
    cache = json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
    classifier = None
    reports = []
    for entry in progress.data.values():
        folder = Path(entry.get("folder_path") or BASE_DIR / "__missing__")
        candidates, seen, errors = [], set(), []
        from download_images import MATCH_POLICY
        if (entry.get("status") in {"SUCCESS", "DOWNLOAD_ERROR"}
                and entry.get("match_policy") == MATCH_POLICY and folder.is_dir()):
            # Only classify files tied to this verified place, never older folder contents.
            for filename in entry.get("photo_files", []):
                if Path(filename).name != filename:
                    continue
                path = folder / filename
                if not path.is_file():
                    errors.append(f"Missing verified photo: {filename}")
                    continue
                digest = CACHE_VERSION + ":" + hashlib.sha256(path.read_bytes()).hexdigest()
                if digest in seen:
                    continue
                seen.add(digest)
                if digest not in cache and classifier is None:
                    logger.info("Loading local photo classifier (first run downloads model)...")
                    classifier = PhotoClassifier()
                try:
                    if digest not in cache:
                        cache[digest] = classifier.classify(path)
                    candidates.append({"path": path, **cache[digest]})
                except (OSError, ValueError) as exc:
                    errors.append(f"{path.name}: {exc}")
        selected = choose_photos(candidates)
        target = output / folder.name
        if selected:
            target.mkdir(exist_ok=True)
        selected_names = set()
        for slot, item in selected:
            name = f"{slot}_{item['category']}.jpg"
            selected_names.add(name)
            destination = target / name
            with Image.open(item["path"]) as source:
                ImageOps.exif_transpose(source).convert("RGB").save(destination, quality=95)
        # Remove only this selector's previous generated slots, never source photos.
        if target.is_dir():
            for name in ("1_ambience.jpg", "2_ambience.jpg", "1_food.jpg", "2_food.jpg", "3_food.jpg"):
                if name not in selected_names:
                    (target / name).unlink(missing_ok=True)
        ambience = sum(item["category"] == "ambience" for _, item in selected)
        food = sum(item["category"] == "food" for _, item in selected)
        reports.append({
            "Restaurant Name": entry.get("restaurant_name", ""),
            "Ambience Images": ambience, "Food Images": food,
            "Status": ("COMPLETE" if ambience == 2 else "FOOD_FALLBACK") if len(selected) == 3 else "NEEDS_REVIEW",
            "Missing": f"{3-len(selected)} photos" if len(selected) < 3 else "",
            "Food Fallback Images": max(0, food - 1),
            "Folder": str(target) if selected else "",
            "Selection": "; ".join(f"{slot}: {item['path'].name} ({item['score']:.2f})" for slot, item in selected),
            "Error": "; ".join(errors),
            "Google Place ID": entry.get("google_place_id", ""),
            "Matched Name": entry.get("google_restaurant_name", ""),
            "Matched Address": entry.get("google_address", ""),
            "Match Verification": "CURRENT" if entry.get("match_policy") == MATCH_POLICY else "REVALIDATION_REQUIRED",
        })
        temp = cache_path.with_suffix(".tmp")
        temp.write_text(json.dumps(cache, indent=2), encoding="utf-8")
        temp.replace(cache_path)
        logger.info("%s: %s ambience, %s food", entry.get("restaurant_name"), ambience, food)
    report_path = BASE_DIR / "output/photo_selection_report.xlsx"
    report_path.parent.mkdir(exist_ok=True)
    from report_utils import save_excel_report
    report_path = save_excel_report(pd.DataFrame(reports), report_path)
    logger.info("Selected photos: %s", output)
    logger.info("Selection report: %s", report_path)
    from enhance_photos import enhance_selected
    enhance_selected()

