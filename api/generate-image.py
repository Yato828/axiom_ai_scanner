from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from axiom_scanner.analysis.image_generation import ImageGenerationError
from api._utils import generated_image_payload, send_bad_request, send_image_error, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            send_json(self, generated_image_payload(self))
        except ImageGenerationError as exc:
            send_image_error(self, exc)
        except (json.JSONDecodeError, ValueError, TypeError) as exc:
            send_bad_request(self, exc)

    def log_message(self, format: str, *args: object) -> None:
        return
