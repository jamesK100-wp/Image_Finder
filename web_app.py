"""Local Excel-to-restaurant-photos web application."""
import json
import os
import re
import subprocess
import sys
import threading
import uuid
import zipfile
from pathlib import Path

from flask import Flask, abort, jsonify, render_template, request, send_file
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
JOBS = BASE / "web_jobs"
app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024
LOCK = threading.Lock()


def job_folder(job_id):
    if not re.fullmatch(r"[0-9a-f]{32}", job_id):
        abort(404)
    folder = JOBS / job_id
    if not (folder / "status.json").exists():
        abort(404)
    return folder


def save_status(folder, **values):
    target = folder / "status.json"
    temporary = target.with_suffix(".tmp")
    temporary.write_text(json.dumps(values), encoding="utf-8")
    temporary.replace(target)


def process_job(folder, wide):
    try:
        save_status(folder, state="running", message="Finding restaurant photos…")
        with (folder / "console.log").open("w", encoding="utf-8") as output:
            result = subprocess.run(
                [sys.executable, str(BASE / "web_worker.py"), str(folder), "wide" if wide else "original"],
                cwd=BASE, stdout=output, stderr=subprocess.STDOUT,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        if result.returncode:
            save_status(folder, state="failed", message="Processing stopped. Check the activity log below.")
            return
        image_root = folder / ("Enhanced_Restaurant_Images_16x9" if wide else "Enhanced_Restaurant_Images")
        images = sorted(image_root.glob("*/*.jpg"))
        with zipfile.ZipFile(folder / "restaurant_images.zip", "w", zipfile.ZIP_DEFLATED) as archive:
            for path in images:
                archive.write(path, "Images/" + path.relative_to(image_root).as_posix())
            for path in (folder / "output").glob("*.xlsx"):
                archive.write(path, "Reports/" + path.name)
        save_status(folder, state="complete", message=f"Ready: {len(images)} enhanced photos.",
                    count=len(images), images=[path.relative_to(folder).as_posix() for path in images])
    except Exception:
        app.logger.exception("Photo job failed")
        save_status(folder, state="failed", message="Unable to complete processing. Check the server terminal.")
    finally:
        LOCK.release()


@app.before_request
def local_only():
    # Browser requests to this local service must come from its own origin.
    hostname = request.host.split(":")[0]
    shared_host = app.config.get("PUBLIC_SHARE", False) and hostname.endswith(".trycloudflare.com")
    if hostname not in {"127.0.0.1", "localhost"} and not shared_host:
        abort(403)
    expected_origin = "https://" + request.host if shared_host else request.host_url.rstrip("/")
    if request.method == "POST" and request.headers.get("Origin") not in {None, expected_origin}:
        abort(403)


@app.get("/")
def home():
    return render_template("index.html")


@app.errorhandler(413)
def too_large(_):
    return jsonify(error="The Excel file must be smaller than 20 MB."), 413


@app.post("/api/jobs")
def create_job():
    load_dotenv(BASE / ".env")
    if not os.getenv("GOOGLE_API_KEY", "").strip():
        return jsonify(error="Set GOOGLE_API_KEY in the project's .env file first."), 400
    upload = request.files.get("file")
    if not upload or not upload.filename.lower().endswith(".xlsx"):
        return jsonify(error="Choose an Excel .xlsx file."), 400
    if not LOCK.acquire(blocking=False):
        return jsonify(error="Another workbook is processing. Please wait for it to finish."), 409
    try:
        folder = JOBS / uuid.uuid4().hex
        folder.mkdir(parents=True)
        upload.save(folder / "input.xlsx")
        from download_images import load_restaurants
        try:
            frame, _ = load_restaurants(str(folder / "input.xlsx"))
        except Exception:
            LOCK.release()
            return jsonify(error="Unable to read this workbook. Use a valid .xlsx with a Restaurant Name column and at least one row."), 400
        save_status(folder, state="queued", message=f"Queued {len(frame)} restaurants.")
        threading.Thread(target=process_job, args=(folder, request.form.get("format") == "wide"), daemon=True).start()
        return jsonify(id=folder.name), 202
    except Exception:
        LOCK.release()
        raise


@app.get("/api/jobs/<job_id>")
def status(job_id):
    folder = job_folder(job_id)
    data = json.loads((folder / "status.json").read_text(encoding="utf-8"))
    log = folder / "console.log"
    text = log.read_text(encoding="utf-8", errors="replace")[-16000:] if log.exists() else ""
    text = re.sub(r"AIza[\w-]+", "[API KEY REDACTED]", text)
    data["log"] = text
    return jsonify(data)


@app.get("/api/jobs/<job_id>/download")
def download(job_id):
    folder = job_folder(job_id)
    if json.loads((folder / "status.json").read_text())["state"] != "complete":
        abort(404)
    return send_file(folder / "restaurant_images.zip", as_attachment=True, download_name="restaurant_images.zip")


@app.get("/api/jobs/<job_id>/image/<path:name>")
def photo(job_id, name):
    folder = job_folder(job_id)
    data = json.loads((folder / "status.json").read_text())
    if name not in data.get("images", []):
        abort(404)
    return send_file(folder / name)


if __name__ == "__main__":
    for previous in JOBS.glob("*/status.json"):
        if json.loads(previous.read_text()).get("state") in {"running", "queued"}:
            save_status(previous.parent, state="failed", message="The server restarted during this job. Upload the workbook again.")
    app.run(host="127.0.0.1", port=5000, debug=False)
