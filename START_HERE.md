# Image Finder

Upload an Excel workbook to find restaurant photos, select seating and food
images, enhance them, and download a ZIP with images and matching reports.

## Windows setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Edit `.env` locally and set `GOOGLE_API_KEY` to your own Google Places API key.
Google API usage requires a configured project and may incur charges.
Never commit API keys or share `.env`.

```powershell
.\.venv\Scripts\python.exe web_app.py
```

Open http://127.0.0.1:5000. Upload an `.xlsx` with a **Restaurant Name** column
and **City**, **Area**, and **Address** for strict location verification.
Choose widescreen (2560×1440 with padding) or original aspect ratio.
The first classification run downloads a local model; keep the terminal open.

No real restaurant workbook, downloaded photos, model weights, API keys, or
active invitation links are included in this repository.

## Matching and output

Name and locality checks reject uncertain or ambiguous matches. Each photo
resource must belong to the matched Google Place ID. Google user-uploaded
photos can still be incorrect: review results before publishing them.
Selection prefers two seating photos plus one food photo, with food filling
missing seating slots. Enhancement preserves original files and cannot recover
detail absent from the source. Each upload has separate results under `web_jobs`.

## Tests

```powershell
.\.venv\Scripts\python.exe -m unittest discover -v
```

## Sharing

`web_app.py` is local-only. `share_app.py` provides a separate protected server
on port 5001, intended for a temporary Cloudflare tunnel. Install cloudflared
separately, start the sharing server, and run:

```powershell
cloudflared tunnel --url http://127.0.0.1:5001 --no-autoupdate
```

Append `/?access=<value from .share_access>` to the generated HTTPS URL.
Treat the complete URL as a private invitation: holders can use your configured
Google API quota. Keep the computer awake and both processes running.
Restarting the sharing server changes the invitation token.
