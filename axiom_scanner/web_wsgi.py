"""Fail closed at production startup if the shared state or origin is missing."""

from axiom_scanner.web_security import public_origin
from axiom_scanner.web_store import get_store
from axiom_scanner.webapp import WEB_ROOT, wsgi_app

public_origin({"host": "127.0.0.1:8080"})
get_store().ping()
if not (WEB_ROOT / "dist" / "launcher.js").is_file():
    raise RuntimeError(
        "Build the browser bundle with npm ci && npm run build before starting the server"
    )
app = wsgi_app
