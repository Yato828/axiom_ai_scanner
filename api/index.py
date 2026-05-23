from __future__ import annotations

import json
import mimetypes
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

from axiom_scanner.analysis.image_generation import ImageGenerationError
from axiom_scanner.analysis.wavespeed_hybrid import HybridImageError
from axiom_dashboard import WEB_ROOT
from api._utils import (
    generated_image_payload,
    hybrid_image_payload,
    narratives_payload,
    og_image_payload,
    scan_payload,
    send_bad_request,
    send_hybrid_error,
    send_image_error,
    send_json,
)


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        route_path, route_query = _route_from_request(parsed.path, parsed.query)
        if route_path == "/api/scan":
            send_json(self, scan_payload(route_query))
            return
        if route_path == "/api/og-image":
            send_json(self, og_image_payload(route_query))
            return
        self._send_static(route_path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route_path, _route_query = _route_from_request(parsed.path, parsed.query)
        try:
            if route_path == "/api/narratives":
                send_json(self, narratives_payload(self))
                return
            if route_path == "/api/generate-image":
                send_json(self, generated_image_payload(self))
                return
            if route_path == "/api/hybrid-image":
                send_json(self, hybrid_image_payload(self))
                return
            send_json(self, {"error": "Not found", "code": "not_found"}, status=404)
        except ImageGenerationError as exc:
            send_image_error(self, exc)
        except HybridImageError as exc:
            send_hybrid_error(self, exc)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            send_bad_request(self, exc)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_static(self, request_path: str) -> None:
        path = "index.html" if request_path in ("", "/") else request_path.lstrip("/")
        if path not in {"app.js", "styles.css"} and not path.startswith("assets/"):
            path = "index.html"

        full_path = (WEB_ROOT / path).resolve()
        web_root = WEB_ROOT.resolve()
        if not _is_inside(full_path, web_root) or not full_path.is_file():
            send_json(self, {"error": "Not found", "code": "not_found"}, status=404)
            return

        body = full_path.read_bytes()
        content_type = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "public, max-age=0, must-revalidate")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def _is_inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _route_from_request(path: str, query: str) -> tuple[str, str]:
    pairs = parse_qsl(query, keep_blank_values=True)
    route = ""
    filtered_pairs = []
    for key, value in pairs:
        if key == "route" and not route:
            route = value
        else:
            filtered_pairs.append((key, value))

    route_path = path
    if path == "/api/index" and route:
        route_path = "/" + route.lstrip("/")
    return route_path, urlencode(filtered_pairs)
