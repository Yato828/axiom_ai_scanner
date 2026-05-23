from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler

from api._utils import narratives_payload, send_bad_request, send_json


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        try:
            send_json(self, narratives_payload(self))
        except (json.JSONDecodeError, ValueError) as exc:
            send_bad_request(self, exc)

    def log_message(self, format: str, *args: object) -> None:
        return
