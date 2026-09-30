# Google Restaurant Image Downloader

## Use the webpage

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe web_app.py
```

Open http://127.0.0.1:5000 in your browser. Upload an `.xlsx` workbook,
choose widescreen or original proportions, and click **Find & enhance photos**.
Keep the server terminal open. When processing finishes, use **Download images
& reports ZIP**. The page includes previews and an activity log.

The app uses the existing `GOOGLE_API_KEY` in `.env`, processes one workbook at
a time, and stores each upload and its results separately under `web_jobs`.
Widescreen output is 2560x1440 with padding. The first classification run may
download model files; subsequent jobs reuse the model cache. This is a local
app, available only on this computer. Restart interrupted uploads after a server restart.

A Windows-friendly Python project that reads restaurant details from Excel, searches the official **Google Places API (New)**, checks multiple candidate places, downloads Place Photos, and creates one folder per restaurant.

It is designed for large files such as 1,000, 5,000, 7,000, or 10,000+ restaurant records.

## What it does

1. Reads your `restaurants.xlsx`.
2. Automatically detects common column names.
3. Searches Google Places Text Search (New).
4. Compares:
   - Restaurant name
   - Address
   - City
   - Area/location
5. Avoids blindly taking the first Google result.
6. Marks weak matches as `LOW_CONFIDENCE`.
7. Downloads up to 10 candidate photos, then selects 2 ambience photos and 1 food photo into `Selected_Restaurant_Images`.
8. Creates a separate restaurant folder.
9. Saves progress in `progress/progress.json`.
10. Resumes after interruption.
11. Creates:
    - `output/image_download_report.xlsx`
    - `output/failed_restaurants.xlsx`
12. Writes detailed logs to `logs/downloader.log`.

## Important Google API note

This project uses the official Places API (New) HTTP endpoints. Google requires a field mask for Text Search (New), and `places.photos` must be requested if you want photo resources. Place Photos (New) then uses those photo resource names to retrieve the images.

Google's current documentation says Text Search (New) can return place photos when `places.photos` is included in the field mask, and Place Photos (New) accepts the photo resource name plus maximum width/height parameters.

Official documentation:
- Text Search (New): https://developers.google.com/maps/documentation/places/web-service/text-search
- Place Photos (New): https://developers.google.com/maps/documentation/places/web-service/place-photos
- Places API setup: https://developers.google.com/maps/documentation/places/web-service/get-api-key
- API security: https://developers.google.com/maps/api-security-best-practices

## 1. Project structure

```text
restaurant_image_downloader/
│
├── download_images.py
├── requirements.txt
├── .env.example
├── .gitignore
├── README.md
├── restaurants.xlsx
│
├── Restaurant_Images/
├── logs/
├── output/
└── progress/
    └── progress.json
```

The folders are already included in the project. Runtime files are generated when the program runs.

## 2. Google Cloud setup

You need a Google Cloud project with billing configured and the Places API (New) enabled.

### Enable Places API (New)

In Google Cloud Console:

1. Open your Google Cloud project.
2. Go to **APIs & Services**.
3. Open **Library**.
4. Search for **Places API (New)**.
5. Enable it.
6. Make sure billing is configured for the project.

Google's current setup documentation states that a billing account and the Places API enabled are prerequisites.

## 3. Create the API key

In Google Cloud Console:

1. Go to **APIs & Services > Credentials**.
2. Create an API key.
3. Copy the key.
4. Do not paste it into `download_images.py`.

### Recommended restrictions

Google strongly recommends restricting API keys.

For this project, at minimum use an **API restriction** that allows the Places API (New) needed by this application.

If you use an application restriction such as an IP restriction, remember that a desktop computer's public IP can change. A restriction that does not match your current network can cause requests to fail.

Never commit `.env` to GitHub.

## 4. Create `.env`

Copy:

```text
.env.example
```

to:

```text
.env
```

Then put your real key inside:

```env
GOOGLE_API_KEY=YOUR_REAL_GOOGLE_API_KEY
```

Do not put the key in:

- Python code
- Excel
- README
- GitHub
- log files

`.gitignore` already excludes `.env`.

## 5. Excel file

Put your Excel file here:

```text
restaurant_image_downloader/
└── restaurants.xlsx
```

The program can detect common column names.

### Recommended columns

```text
Restaurant Name
Address
City
Area
Location
Category
Website
Phone
```

At minimum, **Restaurant Name** should exist.

Example:

| Restaurant Name | Address | City | Area |
|---|---|---|---|
| Gunpowder | H.No. 6, Assagao | Goa | Assagao |
| Fisherman's Wharf | Cavelossim Road | Goa | Cavelossim |
| Burger Factory | Anjuna Road | Goa | Anjuna |

The program does not require all optional columns.

## 6. Install Python

Use Python 3.10+.

Check:

```cmd
python --version
```

## 7. Create the virtual environment

Open Command Prompt:

```cmd
cd C:\Users\James Kandikatte\Downloads\restaurant_image_downloader
```

Create the environment:

```cmd
python -m venv venv
```

Activate it:

```cmd
venv\Scripts\activate
```

Install packages:

```cmd
pip install -r requirements.txt
```

## 8. Run the project

Normal run:

```cmd
python download_images.py
```

You can also specify the Excel file:

```cmd
python download_images.py --input restaurants.xlsx
```

## 9. Change image count

At the top of `download_images.py`:

```python
MAX_IMAGES = 10
```

This controls candidate downloads, while final output stays at two ambience photos and one food photo. To use a smaller candidate pool, change to:

```python
MAX_IMAGES = 3
```

or:

```python
MAX_IMAGES = 10
```

The program caps this value at 10 because the current Place Photos documentation says a place can return up to 10 photos in the photo array.

## 10. Change workers

At the top:

```python
MAX_WORKERS = 10
```

For example:

```python
MAX_WORKERS = 5
```

or:

```python
MAX_WORKERS = 15
```

You can also use the command line:

```cmd
python download_images.py --workers 10
```

For a large dataset, do not automatically choose a very high number. Google API quotas, billing, network speed, and rate limits still apply.

## 11. Matching protection

The program does not simply download the first result.

For example, if your Excel contains:

```text
Spice Garden
Anjuna
Goa
```

and Google returns:

```text
Spice Garden - Mumbai
Spice Garden - Pune
Spice Garden - Anjuna
```

the program calculates scores using restaurant name, address, city, and area information.

A strong restaurant-name match plus location evidence is required for automatic downloading.

If the result is not reliable enough:

```text
LOW_CONFIDENCE
```

is recorded and the image is not downloaded.

You can make matching stricter by changing:

```python
MIN_MATCH_SCORE = 72.0
```

For example:

```python
MIN_MATCH_SCORE = 80.0
```

You can also use:

```cmd
python download_images.py --min-score 80
```

## 12. Output folders

After running:

```text
Restaurant_Images/
│
├── Gunpowder/
│   ├── Gunpowder_1.jpg
│   ├── Gunpowder_2.jpg
│   ├── Gunpowder_3.jpg
│   ├── Gunpowder_4.jpg
│   └── Gunpowder_5.jpg
│
├── Fishermans Wharf/
│   ├── Fishermans Wharf_1.jpg
│   └── Fishermans Wharf_2.jpg
│
└── Burger Factory/
    ├── Burger Factory_1.jpg
    └── Burger Factory_2.jpg
```

Windows-invalid filename characters are removed.

If the same restaurant name occurs multiple times, the program adds the Excel row number to prevent overwriting, for example:

```text
Restaurant/
Restaurant_row_17/
```

## 13. Resume support

The main resume file is:

```text
progress/progress.json
```

The program stores each restaurant's status.

Possible statuses:

```text
PENDING
PROCESSING
SUCCESS
NOT_FOUND
NO_PHOTOS
LOW_CONFIDENCE
API_ERROR
DOWNLOAD_ERROR
```

If your computer stops after 2,000 of 7,000 restaurants, run the same command again:

```cmd
python download_images.py
```

Completed `SUCCESS` rows are skipped.

Rows that were `PROCESSING` when the computer stopped are eligible to run again.

### Important

Do not delete:

```text
progress/progress.json
```

if you want to resume.

## 14. Reprocess everything

If you intentionally want to start all rows again:

```cmd
python download_images.py --reset-progress
```

Use this carefully.

## 15. Processing report

The program creates:

```text
output/image_download_report.xlsx
```

It contains:

```text
Row Number
Restaurant Name
Address
City
Area
Google Place ID
Google Restaurant Name
Google Address
Match Confidence
Number of Images
Folder Path
Status
Error
```

## 16. Failed restaurants

The program creates:

```text
output/failed_restaurants.xlsx
```

It contains restaurants with:

```text
NOT_FOUND
NO_PHOTOS
LOW_CONFIDENCE
API_ERROR
DOWNLOAD_ERROR
```

This gives you a separate list for manual checking or later reprocessing.

## 17. Logs

The log is:

```text
logs/downloader.log
```

The terminal also shows progress such as:

```text
============================================================
GOOGLE RESTAURANT IMAGE DOWNLOADER
============================================================
Total restaurants: 7000
Workers: 10
Images per restaurant: 5

[1] Gunpowder | Searching Google Places...
[1] Match: Gunpowder | score=94.2 | name=100.0 | location=100.0
[1/7000] Gunpowder -> SUCCESS (5 images)
```

## 18. Image resolution

The configuration uses:

```python
MAX_WIDTH = 1600
MAX_HEIGHT = 1600
```

The Google Place Photos request uses these as maximum dimensions.

This project does not artificially resize, enhance, generate, or modify the downloaded restaurant photos.

## 19. Required Python packages

The project uses:

```text
pandas
openpyxl
requests
python-dotenv
rapidfuzz
```

Why:

- `pandas` — reads Excel data and creates reports.
- `openpyxl` — Excel `.xlsx` support.
- `requests` — Google Places HTTP requests and photo downloads.
- `python-dotenv` — loads the API key from `.env`.
- `rapidfuzz` — fast restaurant/address similarity matching.

No Google-specific Python SDK is required because the project uses Google's official HTTP REST endpoints directly.

## 20. Common errors

### `GOOGLE_API_KEY is missing`

Check that:

```text
.env
```

exists in the project folder and contains:

```env
GOOGLE_API_KEY=YOUR_REAL_KEY
```

### `REQUEST_DENIED`

Check:

1. Places API (New) is enabled.
2. Billing is configured.
3. The API key is correct.
4. API restrictions allow the Places API.
5. An application restriction is not blocking your computer/network.

### HTTP 429

This usually means a rate/quota limit was encountered.

The program retries HTTP 429 with exponential backoff. If it continues, review your Google Cloud quotas and billing.

### `No Google Places result found`

Check:

- Restaurant name spelling.
- City.
- Area.
- Address.

Try the same restaurant manually in Google Maps to see whether it has a public Google place listing.

### `LOW_CONFIDENCE`

The program found candidates but did not consider the best match reliable enough.

This is intentional: it prevents the downloader from automatically attaching photos from a potentially different restaurant.

### `NO_PHOTOS`

Google found the place but the returned place did not contain photos.

### `DOWNLOAD_ERROR`

The place had photo resources, but the image request failed. Check the log file for details.

## 21. Important API and data-use considerations

This project uses Google Places API (New) and Place Photos (New), not Google Maps HTML scraping and not Google Image Search scraping.

Google's Places documentation notes that use of returned Places data is subject to applicable Google Maps Platform terms and policies, including attribution requirements. Make sure your intended use and storage/display workflow comply with Google's current terms.

## 22. Recommended first test

Before running 7,000 restaurants, test 5 rows.

For example:

```cmd
python download_images.py --input restaurants.xlsx --workers 3 --max-images 3
```

Check:

```text
Restaurant_Images/
output/image_download_report.xlsx
output/failed_restaurants.xlsx
logs/downloader.log
progress/progress.json
```

If the matches look correct, then run the larger dataset with your preferred settings.

## 23. Final normal workflow

```cmd
cd C:\Users\James Kandikatte\Downloads\restaurant_image_downloader

python -m venv venv

venv\Scripts\activate

pip install -r requirements.txt

python download_images.py
```

Then your restaurant images will be inside:

```text
Restaurant_Images/
```

and the Excel reports will be inside:

```text
output/
```
# Photo selection: 2 ambience + 1 food

## Automatic photo enhancement

After selection, the downloader automatically saves enhanced copies in
`Enhanced_Restaurant_Images/<restaurant>/`. Original and selected photos remain
unchanged. Enhancement applies gentle contrast correction, sharpening, and
high-quality JPEG export. The default long edge is 2400 pixels, capped at 2x
enlargement; larger originals are not reduced. Upscaling uses interpolation
and does not recover missing detail or generate new objects.

To enhance existing selected photos without downloading or classifying again:

```powershell
.\.venv\Scripts\python.exe enhance_photos.py
```

To sharpen and correct contrast while keeping the original resolution:

```powershell
.\.venv\Scripts\python.exe enhance_photos.py --long-edge 0
```

Results and dimensions are recorded in `output/enhancement_report.json`.

For high-quality 2560x1440 (16:9) output:

```powershell
.\.venv\Scripts\python.exe enhance_photos.py --wide
```

Files go to `Enhanced_Restaurant_Images_16x9`. Dark padding preserves the full
photo without stretching or cropping. Photo enlargement is capped at 2x;
the output canvas is always exactly 2560x1440. This option overrides
`--long-edge` and keeps the original and previous enhanced copies intact.

## Selection rules

Restaurant identity is checked before photo classification. Distinctive name
tokens must match, and the supplied city and locality must both occur in the
matched address. Without a locality, a strong street-address match is required;
city alone is insufficient. Similar-scoring branches are sent for review.
Photo resource names must belong to the matched Google Place ID, and selection
uses only that run's recorded photo files. Older successes require revalidation.
These checks verify listing provenance, not the truth of user-uploaded Google
photos; review the matched name, address and selected photos before publishing.

The downloader now gathers up to 10 candidate photos and uses a local CLIP
classifier to select two seating-arrangement photos and one food photo.
Ambience means tables, chairs, booths, and dining seating only; exterior,
entrance, signboard, and decoration-only photos are excluded.
The final files are in `Selected_Restaurant_Images/<restaurant>/`:
`1_ambience.jpg`, `2_ambience.jpg`, and `3_food.jpg`.
If seating photos are missing, food photos fill those slots: one seating plus
two food photos, or three food photos if no seating is found. Fallback files
are named `1_food.jpg` or `2_food.jpg` as appropriate. If there are not enough
qualifying photos, remaining slots are left empty and listed in
`output/photo_selection_report.xlsx`. Automated classifications need review.
Original downloads remain in `Restaurant_Images`.

Install `requirements.txt` before running. The first selection run downloads
the model into `.model_cache`; later runs reuse it and cached classifications.
Model reference: https://huggingface.co/openai/clip-vit-base-patch32

To select from existing photos without new Google requests:

```powershell
.\.venv\Scripts\python.exe download_images.py --select-only
```

`--max-images` controls the candidate pool, not the final three selected slots.
Previously completed downloads are reused; `--reset-progress --max-images 10`
refreshes the search and collects more candidates when needed.

