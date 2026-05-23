from __future__ import annotations

from http.server import BaseHTTPRequestHandler

from api._utils import og_image_payload, send_json


class handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        send_json(self, og_image_payload(self.path.split("?", 1)[1] if "?" in self.path else ""))

    def log_message(self, format: str, *args: object) -> None:
        return
