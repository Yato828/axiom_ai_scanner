from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from axiom_scanner.analysis.wavespeed_hybrid import HybridImageError
from api._utils import hybrid_image_payload, send_bad_request, send_hybrid_error, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            send_json(self, hybrid_image_payload(self))
        except HybridImageError as exc:
            send_hybrid_error(self, exc)
        except (ValueError, TypeError) as exc:
            send_bad_request(self, exc)

    def log_message(self, format: str, *args: object) -> None:
        return
