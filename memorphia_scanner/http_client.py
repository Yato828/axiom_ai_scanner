from __future__ import annotations

import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class HttpClient:
    def __init__(self, timeout_seconds: int = 12, retries: int = 2) -> None:
        self.timeout_seconds = timeout_seconds
        self.retries = retries

    def get_json(self, url: str) -> Any:
        last_error: Exception | None = None

        for attempt in range(self.retries + 1):
            try:
                request = Request(
                    url,
                    headers={
                        "Accept": "application/json",
                        "User-Agent": "memorphia/0.1",
                    },
                )
                with urlopen(request, timeout=self.timeout_seconds) as response:
                    body = response.read().decode("utf-8")
                    return json.loads(body)
            except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                # Dex-style public APIs can rate limit briefly; a tiny backoff helps.
                if attempt < self.retries:
                    time.sleep(0.6 * (attempt + 1))

        raise RuntimeError(f"GET failed for {url}: {last_error}") from last_error
