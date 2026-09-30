"""Protected sharing server; expose port 5001 with a temporary tunnel."""
import hmac
import secrets
from pathlib import Path

from flask import abort, redirect, request, session
from werkzeug.middleware.proxy_fix import ProxyFix
from waitress import serve
import web_app

BASE = Path(__file__).resolve().parent
TOKEN_FILE = BASE / ".share_access"


def configure(token):
    app = web_app.app
    app.secret_key = secrets.token_hex(32)
    app.config.update(PUBLIC_SHARE=True, SESSION_COOKIE_SECURE=True,
                      SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)
    web_app.JOBS = BASE / "web_shared_jobs"

    def gate():
        supplied = request.args.get("access", "")
        if request.path == "/" and supplied and hmac.compare_digest(supplied, token):
            session["shared_access"] = True
            return redirect("/")
        if not session.get("shared_access"):
            abort(403, description="Open the private invitation link shared by the owner.")

    app.before_request_funcs.setdefault(None, []).insert(0, gate)

    @app.after_request
    def protect_response(response):
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Robots-Tag"] = "noindex, nofollow"
        return response
    return app


if __name__ == "__main__":
    token = secrets.token_urlsafe(32)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    serve(configure(token), host="127.0.0.1", port=5001, threads=4)
