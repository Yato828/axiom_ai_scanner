from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from axiom_scanner.analysis.image_generation import ImageGenerationError
from axiom_scanner.analysis.wavespeed_hybrid import HybridImageError
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
        if parsed.path == "/api/scan":
            send_json(self, scan_payload(parsed.query))
            return
        if parsed.path == "/api/og-image":
            send_json(self, og_image_payload(parsed.query))
            return
        send_json(self, {"error": "Not found", "code": "not_found"}, status=404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            if parsed.path == "/api/narratives":
                send_json(self, narratives_payload(self))
                return
            if parsed.path == "/api/generate-image":
                send_json(self, generated_image_payload(self))
                return
            if parsed.path == "/api/hybrid-image":
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
