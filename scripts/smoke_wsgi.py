"""Exercise real Gunicorn HTTP parsing and wallet auth without external APIs."""

import base64
import http.cookiejar
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import HTTPCookieProcessor, Request, build_opener

from nacl.signing import SigningKey

ROOT = Path(__file__).resolve().parent.parent
ORIGIN = "http://127.0.0.1:8081"


def base58(data):
    alphabet, number, result = (
        "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz",
        int.from_bytes(data, "big"),
        "",
    )
    while number:
        number, remainder = divmod(number, 58)
        result = alphabet[remainder] + result
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + result


def main():
    runtime = os.environ.copy()
    runtime.update(MEMORPHIA_ENV="development", REDIS_URL="", MEMORPHIA_PUBLIC_ORIGIN=ORIGIN)
    process = subprocess.Popen(
        [
            str(Path(sys.executable).with_name("gunicorn")),
            "memorphia_scanner.web_wsgi:app",
            "--bind",
            "127.0.0.1:8081",
            "--workers",
            "1",
            "--threads",
            "2",
        ],
        cwd=ROOT,
        env=runtime,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    opener = build_opener(HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(path, payload=None, csrf=None):
        headers = {"Origin": ORIGIN}
        if csrf:
            headers["X-CSRF-Token"] = csrf
        if payload is not None:
            headers["Content-Type"] = "application/json"
        request = Request(
            ORIGIN + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers=headers,
        )
        with opener.open(request, timeout=3) as response:
            return json.load(response)

    try:
        for _ in range(30):
            try:
                request("/api/health")
                break
            except URLError:
                time.sleep(0.1)
        else:
            raise RuntimeError("Gunicorn did not start")
        signer = SigningKey.generate()
        wallet = base58(bytes(signer.verify_key))
        challenge = request("/api/auth/challenge", {"wallet": wallet})
        session = request(
            "/api/auth/verify",
            {
                "challenge_id": challenge["challenge_id"],
                "signature": base64.b64encode(
                    signer.sign(challenge["message"].encode()).signature
                ).decode(),
            },
        )
        assert request("/api/session")["wallet"] == wallet
        request("/api/auth/logout", {}, session["csrf"])
        print("Gunicorn HTTP + real Ed25519 challenge + session cookie + logout: OK")
    finally:
        process.terminate()
        process.wait(timeout=10)


if __name__ == "__main__":
    main()
