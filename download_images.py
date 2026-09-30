"""
Google Restaurant Image Downloader
----------------------------------
Reads restaurant records from Excel, finds matching Google Places (New)
results, downloads Place Photos, and produces resumable reports.

Windows-friendly, designed for large datasets such as 7,000+ restaurants.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import pandas as pd
import requests
from dotenv import load_dotenv
from rapidfuzz import fuzz


# ============================================================
# EASY CONFIGURATION
# ============================================================

BASE_DIR = Path(__file__).resolve().parent
INPUT_EXCEL = str(BASE_DIR / "restaurants.xlsx")
OUTPUT_FOLDER = str(BASE_DIR / "Restaurant_Images")

MAX_IMAGES = 10  # Candidate pool; final selection is 2 ambience + 1 food.
MAX_WORKERS = 10

MAX_WIDTH = 1600
MAX_HEIGHT = 1600

REQUEST_TIMEOUT = 60
MAX_RETRIES = 5

# A match must have at least this score to be downloaded automatically.
# Increase this value for stricter matching.
MIN_MATCH_SCORE = 72.0

# Strong name match + location evidence is required before download.
STRONG_NAME_SCORE = 85.0
MIN_LOCATION_SCORE = 55.0
MATCH_POLICY = "strict-name-locality-v2"


def restaurant_fingerprint(restaurant):
    return hashlib.sha256(json.dumps(restaurant, sort_keys=True).encode("utf-8")).hexdigest()

PROGRESS_FILE = str(BASE_DIR / "progress/progress.json")
REPORT_FILE = str(BASE_DIR / "output/image_download_report.xlsx")
FAILED_FILE = str(BASE_DIR / "output/failed_restaurants.xlsx")
LOG_FILE = str(BASE_DIR / "logs/downloader.log")

GOOGLE_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PHOTO_URL = "https://places.googleapis.com/v1/{photo_name}/media"

# Only these status codes are retried.
RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


# ============================================================
# COLUMN DETECTION
# ============================================================

COLUMN_ALIASES = {
    "name": [
        "restaurant name", "restaurant", "name", "restaurant_name",
        "business name", "business_name", "outlet name", "outlet"
    ],
    "address": [
        "address", "full address", "restaurant address", "location address"
    ],
    "city": ["city", "town", "district city"],
    "area": [
        "area", "location", "locality", "neighborhood", "neighbourhood",
        "region", "suburb", "area/location"
    ],
    "category": ["category", "restaurant category", "type", "cuisine category"],
    "website": ["website", "website url", "url", "web site"],
    "phone": ["phone", "phone number", "mobile", "contact", "contact number"],
}


# ============================================================
# LOGGING
# ============================================================

def setup_logging() -> logging.Logger:
    # Windows redirected consoles may default to an encoding without Indian scripts.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("restaurant_image_downloader")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)s | %(threadName)s | %(message)s"
    )

    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


LOGGER = setup_logging()


# ============================================================
# HELPERS
# ============================================================

def clean_text(value: Any) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize_text(value: Any) -> str:
    text = html.unescape(clean_text(value)).lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def sanitize_filename(value: str, fallback: str = "Restaurant") -> str:
    value = clean_text(value)
    value = re.sub(r'[<>:"/\\|?*]', " ", value)
    value = re.sub(r"[\x00-\x1f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip().rstrip(".")
    return value[:150] or fallback


def unique_folder_name(base_name: str, row_number: int, used_names: set[str]) -> str:
    base = sanitize_filename(base_name, f"Restaurant_{row_number}")
    if base.lower() not in used_names:
        used_names.add(base.lower())
        return base

    candidate = f"{base}_row_{row_number}"
    counter = 2
    while candidate.lower() in used_names:
        candidate = f"{base}_row_{row_number}_{counter}"
        counter += 1
    used_names.add(candidate.lower())
    return candidate


def similarity(a: str, b: str) -> float:
    a = normalize_text(a)
    b = normalize_text(b)
    if not a or not b:
        return 0.0
    return max(
        fuzz.ratio(a, b),
        fuzz.token_set_ratio(a, b),
        fuzz.token_sort_ratio(a, b),
    )


def location_similarity(restaurant: Dict[str, str], google_address: str) -> float:
    requested = " ".join(
        part for part in [
            restaurant.get("address", ""),
            restaurant.get("area", ""),
            restaurant.get("city", ""),
        ]
        if part
    )
    return similarity(requested, google_address)


def name_similarity(requested_name: str, google_name: str) -> float:
    a = normalize_text(requested_name)
    b = normalize_text(google_name)
    if not a or not b:
        return 0.0

    # Generic business descriptors must not hide a different brand/name.
    generic = {"restaurant", "restaurants", "cafe", "hotel", "banquet", "and", "the", "ltd", "limited"}
    requested = [word for word in a.split() if word not in generic]
    matched = [word for word in b.split() if word not in generic]
    if not requested or not set(requested).issubset(set(matched)):
        return 0.0
    return 100.0


def extract_city_area_score(restaurant: Dict[str, str], google_address: str) -> float:
    address = normalize_text(google_address)
    pieces = [
        normalize_text(restaurant.get("city", "")),
        normalize_text(restaurant.get("area", "")),
    ]
    present = [p for p in pieces if p]
    if any(f" {piece} " not in f" {address} " for piece in present):
        return 0.0
    if pieces[1]:  # An explicit locality must match, together with city if supplied.
        return 100.0
    requested_address = normalize_text(restaurant.get("address", ""))
    # City alone cannot identify a branch. Require a substantial street address.
    if len(requested_address.split()) < 3:
        return 0.0
    requested_numbers = set(re.findall(r"\b\d+\b", requested_address))
    if not requested_numbers.issubset(set(re.findall(r"\b\d+\b", address))):
        return 0.0
    address_score = similarity(requested_address, address)
    return 100.0 if address_score >= 90 else 0.0


def calculate_match_score(
    restaurant: Dict[str, str],
    google_name: str,
    google_address: str,
) -> Tuple[float, float, float, float]:
    n_score = name_similarity(restaurant.get("name", ""), google_name)
    a_score = similarity(restaurant.get("address", ""), google_address)
    loc_score = extract_city_area_score(restaurant, google_address)

    # Name is intentionally weighted most heavily.
    total = (n_score * 0.60) + (a_score * 0.20) + (loc_score * 0.20)
    return total, n_score, a_score, loc_score


def classify_match(
    total: float,
    name_score: float,
    location_score: float,
) -> str:
    if (
        total >= MIN_MATCH_SCORE
        and name_score >= 95
        and location_score == 100
    ):
        return "HIGH"

    return "LOW_CONFIDENCE"


# ============================================================
# PROGRESS STORE
# ============================================================

class ProgressStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.data: Dict[str, Dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.data = {}
            return

        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict):
                self.data = {}
        except (json.JSONDecodeError, OSError):
            LOGGER.warning("Progress file could not be read; starting with empty progress.")
            self.data = {}

    def get(self, key: str) -> Dict[str, Any]:
        return self.data.get(key, {})

    def update(self, key: str, value: Dict[str, Any], save: bool = True) -> None:
        with self.lock:
            current = self.data.get(key, {})
            current.update(value)
            self.data[key] = current
            if save:
                self._save_locked()

    def _save_locked(self) -> None:
        temp = self.path.with_suffix(".tmp")
        temp.write_text(
            json.dumps(self.data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temp.replace(self.path)

    def save(self) -> None:
        with self.lock:
            self._save_locked()


# ============================================================
# GOOGLE PLACES CLIENT
# ============================================================

class GooglePlacesClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.local = threading.local()

    def _request(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> requests.Response:
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        if not hasattr(self.local, "session"):
            self.local.session = requests.Session()

        last_error: Optional[Exception] = None

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                response = self.local.session.request(method, url, **kwargs)

                if response.status_code not in RETRY_STATUS_CODES:
                    return response

                last_error = RuntimeError(
                    f"HTTP {response.status_code}: {response.text[:300]}"
                )

            except (requests.Timeout, requests.ConnectionError) as exc:
                last_error = exc

            if attempt < MAX_RETRIES:
                sleep_seconds = min(2 ** (attempt - 1), 30)
                time.sleep(sleep_seconds)

        if last_error:
            raise last_error

        raise RuntimeError("Request failed without a captured error.")

    def search_places(self, query: str) -> List[Dict[str, Any]]:
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": self.api_key,
            "X-Goog-FieldMask": (
                "places.id,"
                "places.displayName,"
                "places.formattedAddress,"
                "places.photos"
            ),
        }

        body = {
            "textQuery": query,
            "pageSize": 10,
            "languageCode": "en",
        }

        response = self._request(
            "POST",
            GOOGLE_TEXT_SEARCH_URL,
            headers=headers,
            json=body,
        )

        if response.status_code >= 400:
            raise RuntimeError(
                f"Google Text Search HTTP {response.status_code}: "
                f"{response.text[:500]}"
            )

        payload = response.json()
        return payload.get("places", [])

    def download_photo(self, photo_name: str, destination: Path) -> None:
        url = GOOGLE_PHOTO_URL.format(photo_name=photo_name)
        params = {
            "maxWidthPx": MAX_WIDTH,
            "maxHeightPx": MAX_HEIGHT,
            "key": self.api_key,
        }

        response = self._request("GET", url, params=params, allow_redirects=True)

        if response.status_code >= 400:
            raise RuntimeError(
                f"Google Photo HTTP {response.status_code}: "
                f"{response.text[:300]}"
            )

        content_type = (response.headers.get("Content-Type") or "").lower()
        if not content_type.startswith("image/"):
            raise RuntimeError(
                f"Google Photo returned unexpected content type: {content_type}"
            )

        destination.parent.mkdir(parents=True, exist_ok=True)
        temp = destination.with_suffix(".part")
        temp.write_bytes(response.content)
        temp.replace(destination)


# ============================================================
# INPUT EXCEL
# ============================================================

def canonical_column(value: str) -> str:
    return normalize_text(value).replace("_", " ")


def detect_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    normalized_headers = {
        canonical_column(col): col for col in df.columns
    }

    result: Dict[str, Optional[str]] = {
        "name": None,
        "address": None,
        "city": None,
        "area": None,
        "category": None,
        "website": None,
        "phone": None,
    }

    for field, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            key = canonical_column(alias)
            if key in normalized_headers:
                result[field] = normalized_headers[key]
                break

    return result


def load_restaurants(path: str) -> Tuple[pd.DataFrame, Dict[str, Optional[str]]]:
    if not Path(path).exists():
        raise FileNotFoundError(f"Excel file not found: {path}")

    df = pd.read_excel(path, engine="openpyxl")
    if df.empty:
        raise ValueError("The Excel file contains no rows.")

    columns = detect_columns(df)

    if not columns["name"]:
        raise ValueError(
            "Could not detect the restaurant-name column. "
            "Use a column such as: Restaurant Name, Restaurant, Name, or Business Name."
        )

    # Build a stable internal representation while preserving the original data.
    return df, columns


def row_to_restaurant(
    row: pd.Series,
    columns: Dict[str, Optional[str]],
) -> Dict[str, str]:
    def get(field: str) -> str:
        col = columns.get(field)
        return clean_text(row[col]) if col else ""

    return {
        "name": get("name"),
        "address": get("address"),
        "city": get("city"),
        "area": get("area"),
        "category": get("category"),
        "website": get("website"),
        "phone": get("phone"),
    }


# ============================================================
# SEARCH / MATCH / DOWNLOAD
# ============================================================

def build_search_queries(restaurant: Dict[str, str]) -> List[str]:
    name = restaurant.get("name", "")
    area = restaurant.get("area", "")
    city = restaurant.get("city", "")
    address = restaurant.get("address", "")

    queries = []

    primary = " ".join(
        x for x in [name, area, city, "restaurant"] if x
    ).strip()
    if primary:
        queries.append(primary)

    if address:
        q = " ".join(x for x in [name, address, city] if x).strip()
        if q and q not in queries:
            queries.append(q)

    fallback = " ".join(x for x in [name, city] if x).strip()
    if fallback and fallback not in queries:
        queries.append(fallback)

    return queries


def choose_best_place(
    restaurant: Dict[str, str],
    places: List[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    candidates = []

    for place in places:
        google_name = clean_text(
            (place.get("displayName") or {}).get("text", "")
        )
        google_address = clean_text(place.get("formattedAddress", ""))

        total, name_score, address_score, location_score = calculate_match_score(
            restaurant,
            google_name,
            google_address,
        )
        confidence = classify_match(total, name_score, location_score)

        candidates.append(
            {
                "place": place,
                "total": total,
                "name_score": name_score,
                "address_score": address_score,
                "location_score": location_score,
                "confidence": confidence,
            }
        )

    if not candidates:
        return None

    candidates.sort(
        key=lambda x: (
            x["confidence"] == "HIGH",
            x["total"],
            x["name_score"],
            x["location_score"],
        ),
        reverse=True,
    )

    best = candidates[0]
    if (len(candidates) > 1 and best["confidence"] == "HIGH"
            and candidates[1]["confidence"] == "HIGH"
            and best["place"].get("id") != candidates[1]["place"].get("id")
            and best["total"] - candidates[1]["total"] < 3):
        return {**best, "confidence": "LOW_CONFIDENCE", "blocked": True}
    if best["confidence"] == "LOW_CONFIDENCE":
        return {
            **best,
            "blocked": True,
        }

    # Prevent a weak result from winning merely because it is first.
    return {
        **best,
        "blocked": False,
    }


def image_extension(content_type: str) -> str:
    content_type = content_type.lower()
    if "png" in content_type:
        return ".png"
    if "webp" in content_type:
        return ".webp"
    return ".jpg"


def photo_identifier(photo_name: str) -> str:
    # The complete Google photo resource name is stable enough for
    # within-run and progress-file duplicate detection.
    return photo_name


def process_restaurant(
    index: int,
    row_number: int,
    restaurant: Dict[str, str],
    folder_name: str,
    client: GooglePlacesClient,
) -> Dict[str, Any]:
    result = {
        "row_number": row_number,
        "restaurant_name": restaurant["name"],
        "address": restaurant["address"],
        "city": restaurant["city"],
        "area": restaurant["area"],
        "google_place_id": "",
        "google_restaurant_name": "",
        "google_address": "",
        "match_confidence": "",
        "number_of_images": 0,
        "folder_path": "",
        "status": "API_ERROR",
        "error": "",
        "photo_ids": [],
        "photo_files": [],
        "match_policy": MATCH_POLICY,
        "input_fingerprint": restaurant_fingerprint(restaurant),
    }

    folder = Path(OUTPUT_FOLDER) / folder_name
    result["folder_path"] = str(folder)

    if not restaurant["name"]:
        result["status"] = "NOT_FOUND"
        result["error"] = "Restaurant name is empty."
        return result

    try:
        LOGGER.info(
            f"[{index}] {restaurant['name']} | Searching Google Places..."
        )

        all_places: List[Dict[str, Any]] = []
        seen_place_ids = set()

        for query in build_search_queries(restaurant):
            places = client.search_places(query)
            for place in places:
                pid = clean_text(place.get("id", ""))
                if pid and pid not in seen_place_ids:
                    seen_place_ids.add(pid)
                    all_places.append(place)

            # If the first query already gives a strong candidate, we can stop.
            best_so_far = choose_best_place(restaurant, all_places)
            if (
                best_so_far
                and best_so_far["confidence"] == "HIGH"
                and best_so_far["name_score"] >= 90
            ):
                break

        best = choose_best_place(restaurant, all_places)

        if not best:
            result["status"] = "NOT_FOUND"
            result["error"] = "No Google Places result found."
            return result

        place = best["place"]
        google_name = clean_text(
            (place.get("displayName") or {}).get("text", "")
        )
        google_address = clean_text(place.get("formattedAddress", ""))
        place_id = clean_text(place.get("id", ""))

        result["google_place_id"] = place_id
        result["google_restaurant_name"] = google_name
        result["google_address"] = google_address
        result["match_confidence"] = best["confidence"]

        LOGGER.info(
            f"[{index}] Match: {google_name} | "
            f"score={best['total']:.1f} | "
            f"name={best['name_score']:.1f} | "
            f"location={best['location_score']:.1f}"
        )

        if best["blocked"]:
            result["status"] = "LOW_CONFIDENCE"
            result["error"] = (
                f"Name/locality verification failed: name={best['name_score']:.1f}, "
                f"location={best['location_score']:.1f}, total={best['total']:.1f}. "
                "Exact name tokens and locality (or strong street-address evidence) are required."
            )
            return result

        photos = place.get("photos") or []
        if not photos:
            result["status"] = "NO_PHOTOS"
            result["error"] = "Matched Google place has no photos."
            return result

        folder.mkdir(parents=True, exist_ok=True)
        used_photo_ids = set()
        photo_errors = []

        for photo_number, photo in enumerate(photos[:MAX_IMAGES], start=1):
            photo_name = clean_text(photo.get("name", ""))
            if not photo_name:
                continue
            if not photo_name.startswith(f"places/{place_id}/photos/"):
                photo_errors.append("Photo resource does not belong to the matched Google place.")
                continue

            photo_id = photo_identifier(photo_name)
            if photo_id in used_photo_ids:
                continue
            used_photo_ids.add(photo_id)

            # Google may redirect to the actual image. We use .jpg by default;
            # the API response is validated as image/* before saving.
            resource_hash = hashlib.sha256(photo_name.encode()).hexdigest()[:20]
            destination = folder / f"{sanitize_filename(restaurant['name'])}_{resource_hash}.jpg"

            try:
                client.download_photo(photo_name, destination)
                result["photo_ids"].append(photo_id)
                result["photo_files"].append(destination.name)
                result["number_of_images"] += 1

            except Exception as exc:
                photo_errors.append(f"Photo {photo_number}: {exc}")
                LOGGER.warning(
                    f"[{index}] Photo {photo_number} failed: {exc}"
                )

        if photo_errors:
            result["status"] = "DOWNLOAD_ERROR"
            result["error"] = "; ".join(photo_errors)
        elif result["number_of_images"] == 0:
            result["status"] = "DOWNLOAD_ERROR"
            result["error"] = "Photos were available but none could be downloaded."
        else:
            result["status"] = "SUCCESS"

        return result

    except Exception as exc:
        result["status"] = "API_ERROR"
        result["error"] = str(exc)
        return result


# ============================================================
# REPORTS
# ============================================================

REPORT_COLUMNS = [
    "Row Number",
    "Restaurant Name",
    "Address",
    "City",
    "Area",
    "Google Place ID",
    "Google Restaurant Name",
    "Google Address",
    "Match Confidence",
    "Number of Images",
    "Folder Path",
    "Status",
    "Error",
]


def result_to_report_row(result: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "Row Number": result.get("row_number", ""),
        "Restaurant Name": result.get("restaurant_name", ""),
        "Address": result.get("address", ""),
        "City": result.get("city", ""),
        "Area": result.get("area", ""),
        "Google Place ID": result.get("google_place_id", ""),
        "Google Restaurant Name": result.get("google_restaurant_name", ""),
        "Google Address": result.get("google_address", ""),
        "Match Confidence": result.get("match_confidence", ""),
        "Number of Images": result.get("number_of_images", 0),
        "Folder Path": result.get("folder_path", ""),
        "Status": result.get("status", ""),
        "Error": result.get("error", ""),
    }


def write_reports(progress: ProgressStore) -> Tuple[Path, Path]:
    from report_utils import save_excel_report
    Path(REPORT_FILE).parent.mkdir(parents=True, exist_ok=True)

    rows = [
        result_to_report_row(item)
        for item in progress.data.values()
    ]

    rows.sort(key=lambda x: int(x["Row Number"]) if str(x["Row Number"]).isdigit() else 0)

    report_df = pd.DataFrame(rows, columns=REPORT_COLUMNS)
    saved_report = save_excel_report(report_df, REPORT_FILE)

    failed_statuses = {
        "NOT_FOUND",
        "NO_PHOTOS",
        "LOW_CONFIDENCE",
        "API_ERROR",
        "DOWNLOAD_ERROR",
    }

    failed_df = report_df[
        report_df["Status"].isin(failed_statuses)
    ].copy()

    saved_failed = save_excel_report(failed_df, FAILED_FILE)
    return saved_report, saved_failed


# ============================================================
# MAIN
# ============================================================

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download Google Places restaurant photos from an Excel file."
    )
    parser.add_argument("--input", default=INPUT_EXCEL, help="Input Excel file.")
    parser.add_argument("--select-only", action="store_true", help="Select 2 seating + 1 food, with food fallback, from existing downloads without Google requests.")
    parser.add_argument(
        "--max-images",
        type=int,
        default=MAX_IMAGES,
        help="Maximum candidate photos per restaurant (final selection: 2 ambience + 1 food).",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=MAX_WORKERS,
        help="Number of concurrent workers.",
    )
    parser.add_argument(
        "--min-score",
        type=float,
        default=MIN_MATCH_SCORE,
        help="Minimum match score before downloading.",
    )
    parser.add_argument(
        "--reset-progress",
        action="store_true",
        help="Delete existing progress and process everything again.",
    )
    return parser.parse_args()


def main() -> None:
    global MAX_IMAGES, MAX_WORKERS, MIN_MATCH_SCORE

    args = parse_args()
    if args.select_only:
        from select_photos import select_all
        select_all(ProgressStore(PROGRESS_FILE))
        return
    MAX_IMAGES = max(1, min(args.max_images, 10))
    MAX_WORKERS = max(1, min(args.workers, 25))
    MIN_MATCH_SCORE = max(0.0, min(args.min_score, 100.0))

    load_dotenv(BASE_DIR / ".env")

    api_key = clean_text(os.getenv("GOOGLE_API_KEY"))
    if not api_key or api_key == "YOUR_GOOGLE_API_KEY_HERE":
        raise SystemExit(
            "GOOGLE_API_KEY is missing. Put your key in .env and run again."
        )

    Path(OUTPUT_FOLDER).mkdir(parents=True, exist_ok=True)
    Path(REPORT_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(PROGRESS_FILE).parent.mkdir(parents=True, exist_ok=True)

    progress = ProgressStore(PROGRESS_FILE)

    if args.reset_progress:
        progress.data = {}
        progress.save()
        LOGGER.info("Progress reset.")

    df, columns = load_restaurants(args.input)

    LOGGER.info("=" * 60)
    LOGGER.info("GOOGLE RESTAURANT IMAGE DOWNLOADER")
    LOGGER.info("=" * 60)
    LOGGER.info(f"Input file: {args.input}")
    LOGGER.info(f"Total restaurants: {len(df)}")
    LOGGER.info(f"Workers: {MAX_WORKERS}")
    LOGGER.info(f"Images per restaurant: {MAX_IMAGES}")
    LOGGER.info(f"Minimum match score: {MIN_MATCH_SCORE:.1f}")
    LOGGER.info(
        "Detected columns: "
        + ", ".join(
            f"{key}={value}" for key, value in columns.items() if value
        )
    )
    LOGGER.info("=" * 60)

    # Assign stable folder names before concurrency starts.
    used_folder_names: set[str] = set()
    jobs = []

    for zero_index, (_, row) in enumerate(df.iterrows(), start=0):
        row_number = zero_index + 2  # Excel header is row 1.
        restaurant = row_to_restaurant(row, columns)
        key = str(row_number)

        previous = progress.get(key)
        if previous.get("status") == "SUCCESS":
            # Keep the existing folder assignment for resume consistency.
            folder_name = Path(
                previous.get("folder_path", "")
            ).name or unique_folder_name(
                restaurant["name"], row_number, used_folder_names
            )
            used_folder_names.add(folder_name.lower())
        else:
            folder_name = unique_folder_name(
                restaurant["name"], row_number, used_folder_names
            )

        if (previous.get("status") == "SUCCESS"
                and previous.get("match_policy") == MATCH_POLICY
                and previous.get("input_fingerprint") == restaurant_fingerprint(restaurant)
                and previous.get("photo_files")
                and all((Path(previous.get("folder_path", "")) / name).is_file() for name in previous["photo_files"])):
            continue

        # PROCESSING is deliberately not treated as complete. If the machine
        # crashed, this row will be picked up again on the next run.
        progress.update(
            key,
            {
                "row_number": row_number,
                "restaurant_name": restaurant["name"],
                "address": restaurant["address"],
                "city": restaurant["city"],
                "area": restaurant["area"],
                "folder_path": str(Path(OUTPUT_FOLDER) / folder_name),
                "status": "PENDING",
            },
            save=False,
        )

        jobs.append(
            (
                zero_index + 1,
                row_number,
                restaurant,
                folder_name,
            )
        )

    progress.save()

    LOGGER.info(f"Pending restaurants: {len(jobs)}")

    if not jobs:
        write_reports(progress)
        from select_photos import select_all
        select_all(progress)
        LOGGER.info("Nothing new to process. Reports refreshed.")
        return

    client = GooglePlacesClient(api_key)
    completed = 0

    # Keep API calls concurrent, but write progress/report data centrally
    # from the main thread to avoid corrupting the JSON file.
    with ThreadPoolExecutor(
        max_workers=MAX_WORKERS,
        thread_name_prefix="worker",
    ) as executor:

        future_map = {}
        for index, row_number, restaurant, folder_name in jobs:
            key = str(row_number)
            progress.update(key, {"status": "PROCESSING"}, save=False)

            future = executor.submit(
                process_restaurant,
                index,
                row_number,
                restaurant,
                folder_name,
                client,
            )
            future_map[future] = key

        progress.save()

        for future in as_completed(future_map):
            key = future_map[future]
            completed += 1

            try:
                result = future.result()
            except Exception as exc:
                previous = progress.get(key)
                result = {
                    "row_number": previous.get("row_number", key),
                    "restaurant_name": previous.get("restaurant_name", ""),
                    "address": previous.get("address", ""),
                    "city": previous.get("city", ""),
                    "area": previous.get("area", ""),
                    "google_place_id": "",
                    "google_restaurant_name": "",
                    "google_address": "",
                    "match_confidence": "",
                    "number_of_images": 0,
                    "folder_path": previous.get("folder_path", ""),
                    "status": "API_ERROR",
                    "error": str(exc),
                    "photo_ids": [],
                }

            progress.update(key, result, save=True)

            LOGGER.info(
                f"[{completed}/{len(jobs)}] "
                f"{result.get('restaurant_name', '')} -> "
                f"{result.get('status', '')} "
                f"({result.get('number_of_images', 0)} images)"
            )

    saved_report, saved_failed = write_reports(progress)

    # Summary
    statuses = [
        item.get("status", "")
        for item in progress.data.values()
    ]
    total_images = sum(
        int(item.get("number_of_images", 0) or 0)
        for item in progress.data.values()
    )

    LOGGER.info("=" * 60)
    LOGGER.info("COMPLETED")
    LOGGER.info("=" * 60)
    LOGGER.info(f"Total restaurants : {len(df)}")
    LOGGER.info(f"Successful        : {statuses.count('SUCCESS')}")
    LOGGER.info(f"Not found         : {statuses.count('NOT_FOUND')}")
    LOGGER.info(f"No photos         : {statuses.count('NO_PHOTOS')}")
    LOGGER.info(f"Low confidence    : {statuses.count('LOW_CONFIDENCE')}")
    LOGGER.info(
        "Errors            : "
        + str(
            statuses.count("API_ERROR")
            + statuses.count("DOWNLOAD_ERROR")
        )
    )
    LOGGER.info(f"Total images downloaded: {total_images}")
    LOGGER.info(f"Report: {saved_report}")
    LOGGER.info(f"Failed: {saved_failed}")
    LOGGER.info(f"Progress: {PROGRESS_FILE}")
    LOGGER.info("=" * 60)
    from select_photos import select_all
    select_all(progress)


if __name__ == "__main__":
    main()
