"""Password-protected persistent hosting entry point."""
import hmac
import json
import os
import threading
from flask import Response, request
from waitress import serve
import web_app


def configure():
    username = os.environ.get("APP_USERNAME", "owner")
    password = os.environ.get("APP_PASSWORD", "")
    if len(password) < 16:
        raise RuntimeError("Set APP_PASSWORD to at least 16 characters before hosting.")
    if not os.environ.get("GOOGLE_API_KEY"):
        raise RuntimeError("Set GOOGLE_API_KEY in the hosting dashboard.")
    app = web_app.app

    def authentication():
        if request.path == "/healthz" and request.method == "GET":
            return Response("ok", mimetype="text/plain")
        credentials = request.authorization
        if (not credentials or credentials.type != "basic"
                or not hmac.compare_digest((credentials.username or "").encode(), username.encode())
                or not hmac.compare_digest((credentials.password or "").encode(), password.encode())):
            return Response("Sign in to Image Finder.", 401,
                            {"WWW-Authenticate": 'Basic realm="Image Finder", charset="UTF-8"'})
    app.before_request_funcs.setdefault(None, []).insert(0, authentication)

    @app.after_request
    def private(response):
        response.headers["Cache-Control"] = "no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return app


def recover_jobs():
    for status_file in sorted(web_app.JOBS.glob("*/status.json")):
        state = json.loads(status_file.read_text(encoding="utf-8"))
        if state.get("state") in {"running", "queued"}:
            web_app.LOCK.acquire()
            options = status_file.parent / "options.json"
            wide = json.loads(options.read_text()).get("wide", True) if options.exists() else True
            web_app.process_job(status_file.parent, wide)


if __name__ == "__main__":
    application = configure()
    threading.Thread(target=recover_jobs, daemon=True).start()
    serve(application, host="0.0.0.0", port=int(os.environ.get("PORT", "10000")), threads=8)
