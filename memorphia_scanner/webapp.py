"""One HTTP application for local development, Gunicorn and Vercel."""

from __future__ import annotations

import hashlib
import json
import logging
import mimetypes
import os
import threading
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from memorphia_scanner.analysis.narratives import (
    generate_narratives,
    load_og_memecoins,
    normalize_og_memecoins,
)
from memorphia_scanner.launch import launch_config, publish_metadata, rpc_request
from memorphia_scanner.safe_images import download_image, normalize_image
from memorphia_scanner.web_runtime import (
    ROOT,
    enqueue_generation,
    generation_features,
    public_job,
    runtime_config,
    scan_payload,
)
from memorphia_scanner.web_security import (
    ApiError,
    capacity_gate,
    check_origin,
    client_identity,
    create_challenge,
    public_origin,
    rate_limit,
    require_session,
    session_key,
    verify_challenge,
)
from memorphia_scanner.web_store import get_store

WEB_ROOT = ROOT / "web"
MAX_BODY = (
    4_400_000  # Fits Vercel's 4.5 MB request limit, including multipart overhead.
)
logger = logging.getLogger(__name__)
SECURITY_HEADERS = {
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' https: data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
}


@dataclass
class Request:
    method: str
    target: str
    headers: dict
    body: bytes = b""
    remote: str = "127.0.0.1"


@dataclass
class Response:
    status: int
    body: bytes = b""
    headers: dict = field(default_factory=dict)


def json_response(payload, status=200, **headers):
    return Response(
        status,
        json.dumps(payload, ensure_ascii=False).encode(),
        {
            "Content-Type": "application/json; charset=utf-8",
            "Cache-Control": "no-store",
            **headers,
        },
    )


def read_payload(request, maximum=256_000):
    if len(request.body) > maximum:
        raise ApiError("Request is too large.", "request_too_large", 413)
    if request.headers.get("content-type", "").split(";")[0] != "application/json":
        raise ApiError(
            "Expected an application/json request.", "unsupported_media_type", 415
        )
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeError):
        raise ApiError("Request contains invalid JSON.")
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object.")
    return payload


def bounded_int(value, default, maximum):
    try:
        return min(max(int(value), 1), maximum)
    except (ValueError, TypeError):
        return default


def static_response(path, headers):
    path = "index.html" if path in {"", "/"} else unquote(path).lstrip("/")
    full_path = (WEB_ROOT / path).resolve()
    try:
        full_path.relative_to(WEB_ROOT.resolve())
    except ValueError:
        raise ApiError("Not found.", "not_found", 404)
    if not full_path.is_file() or any(
        part.startswith(".") for part in Path(path).parts
    ):
        raise ApiError("Not found.", "not_found", 404)
    # Never serve source maps, environment files or arbitrary file types.
    if full_path.suffix not in {
        ".html",
        ".css",
        ".js",
        ".svg",
        ".png",
        ".webp",
        ".jpg",
        ".ico",
    }:
        raise ApiError("Not found.", "not_found", 404)
    encoding = None
    accepted = headers.get("accept-encoding", "")
    if path.startswith("dist/"):
        for token, extension in (("br", ".br"), ("gzip", ".gz")):
            compressed = full_path.with_name(full_path.name + extension)
            if token in accepted and compressed.is_file():
                full_path, encoding = compressed, token
                break
    body = full_path.read_bytes()
    etag = '"' + hashlib.sha256(body).hexdigest()[:24] + '"'
    response_headers = {
        "Content-Type": mimetypes.guess_type(path)[0] or "application/octet-stream",
        "Cache-Control": "no-cache"
        if path == "index.html" or path in {"app.js", "styles.css", "dist/launcher.js"}
        else "public, max-age=3600, must-revalidate",
        "ETag": etag,
    }
    if path.startswith("dist/"):
        response_headers["Vary"] = "Accept-Encoding"
    if encoding:
        response_headers["Content-Encoding"] = encoding
    if headers.get("if-none-match") == etag:
        return Response(304, headers=response_headers)
    return Response(200, body, response_headers)


def route(request):
    parsed = urlsplit(request.target)
    path, query = parsed.path, parse_qs(parsed.query)
    headers = request.headers
    if request.method in {"GET", "HEAD"} and not path.startswith("/api/"):
        return static_response(path, headers)
    identity = client_identity(request.remote, headers)
    rate_limit(identity, "api", 240)
    if request.method in {"GET", "HEAD"}:
        if path == "/api/health":
            get_store().ping()
            return json_response(
                {
                    "status": "ok",
                    "worker_ready": bool(get_store().get("worker:features")),
                }
            )
        if path == "/api/config":
            public_origin(headers)
            return json_response(
                {
                    "launch": launch_config(),
                    "max_image_bytes": 3 * 1024 * 1024,
                    "generation_ready": bool(generation_features().get("hybrid")),
                }
            )
        if path == "/api/session":
            session = require_session(headers, csrf=False)
            return json_response({"wallet": session["wallet"], "csrf": session["csrf"]})
        if path == "/api/scan":
            payload, status = scan_payload(
                bounded_int(query.get("limit", [100])[0], 100, 200)
            )
            response = json_response(payload, status)
            response.headers["Retry-After"] = "3" if status == 202 else "45"
            return response
        if path == "/api/og":
            config = runtime_config()
            return json_response(
                {"og_memecoins": load_og_memecoins(ROOT, config.og_memecoins_path)}
            )
        if path == "/api/og-image":
            # OG icons are shipped with the page. No per-visitor provider searches.
            symbol = str(query.get("symbol", [""])[0]).upper()
            icon = WEB_ROOT / "assets" / "tokens" / (symbol + ".svg")
            image = (
                "/assets/tokens/" + symbol + ".svg"
                if symbol.isalnum() and icon.is_file()
                else ""
            )
            return json_response({"symbol": symbol, "image_url": image})
        if path.startswith("/api/jobs/"):
            session = require_session(headers, csrf=False)
            return json_response(public_job(path.rsplit("/", 1)[1], session["wallet"]))
    elif request.method == "POST":
        origin = check_origin(headers)
        rate_limit(identity, "write", 60)
        if path == "/api/auth/challenge":
            rate_limit(identity, "signin", 10)
            return json_response(
                create_challenge(read_payload(request, 2048).get("wallet"), origin)
            )
        if path == "/api/auth/verify":
            rate_limit(identity, "verify", 15)
            session, cookie = verify_challenge(read_payload(request, 4096), origin)
            return json_response(
                {"wallet": session["wallet"], "csrf": session["csrf"]},
                **{"Set-Cookie": cookie},
            )
        if path == "/api/narratives":
            payload = read_payload(request)
            tokens, og = payload.get("tokens", []), payload.get("og_memecoins", [])
            if (
                not isinstance(tokens, list)
                or not isinstance(og, list)
                or len(tokens) > 200
                or len(og) > 100
            ):
                raise ApiError("Use at most 200 tokens and 100 reference coins.")
            if any(not isinstance(item, dict) for item in tokens + og):
                raise ApiError("Token lists must contain objects.")
            return json_response(
                {
                    "narratives": generate_narratives(
                        tokens,
                        normalize_og_memecoins(og),
                        bounded_int(payload.get("limit"), 12, 30),
                    )
                }
            )
        session = require_session(headers)
        wallet = session["wallet"]
        if path == "/api/auth/logout":
            get_store().take(session_key(headers))
            return json_response(
                {"ok": True},
                **{
                    "Set-Cookie": "dm_session=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"
                },
            )
        if path == "/api/rpc":
            rate_limit(wallet, "rpc", 120)
            return json_response(rpc_request(read_payload(request, 128_000)))
        if path == "/api/images/import":
            rate_limit(wallet, "image_import", 10)
            url = read_payload(request, 4096).get("url", "")
            if not isinstance(url, str):
                raise ApiError("Image URL must be text.")
            data, _ = download_image(url)
            return Response(
                200,
                normalize_image(data),
                {"Content-Type": "image/png", "Cache-Control": "no-store"},
            )
        if path == "/api/launch/metadata":
            if not launch_config()["enabled"]:
                raise ApiError(
                    "Launch hosting and Solana RPC must be configured first.",
                    "launch_unavailable",
                    503,
                )
            rate_limit(wallet, "metadata", 3, 300)
            from memorphia_scanner.analysis.wavespeed_hybrid import parse_multipart

            fields, files = parse_multipart(
                headers.get("content-type", ""), request.body
            )
            image = files.get("image")
            if image is None:
                raise ApiError("Upload the token image.")
            cache_key = (
                "metadata:"
                + hashlib.sha256(
                    wallet.encode()
                    + json.dumps(fields, sort_keys=True).encode()
                    + image.data
                ).hexdigest()
            )
            cached = get_store().get(cache_key)
            if cached:
                return json_response(json.loads(cached))
            with capacity_gate("metadata", 4):
                result = publish_metadata(fields, image.data)
                get_store().set(cache_key, json.dumps(result), 86400)
            return json_response(result)
        if path in {"/api/hybrid-image", "/api/generate-image"}:
            if path.endswith("hybrid-image") and not generation_features().get(
                "hybrid"
            ):
                raise ApiError(
                    "Image generation is not configured yet.",
                    "generation_unavailable",
                    503,
                )
            if path.endswith("generate-image") and not generation_features().get(
                "image"
            ):
                raise ApiError(
                    "Image generation is not configured yet.",
                    "generation_unavailable",
                    503,
                )
            rate_limit(wallet, "generation", 3, 300)
            rate_limit(identity, "generation_ip", 5, 300)
            rate_limit(wallet, "generation_day", 10, 86400)
            rate_limit(
                "global",
                "generation_budget",
                int(os.getenv("MEMORPHIA_GENERATION_HOURLY_LIMIT", "100")),
                3600,
            )
            kind = "hybrid" if path.endswith("hybrid-image") else "image"
            job = enqueue_generation(
                kind,
                request.body,
                headers.get("content-type", ""),
                wallet,
                headers.get("idempotency-key", ""),
            )
            return json_response(job, 202)
    else:
        raise ApiError("Method not allowed.", "method_not_allowed", 405)
    raise ApiError("Not found.", "not_found", 404)


def application(request):
    request.headers = {key.lower(): value for key, value in request.headers.items()}
    try:
        if len(request.body) > MAX_BODY:
            raise ApiError("Request is too large.", "request_too_large", 413)
        response = route(request)
    except ApiError as exc:
        response = json_response({"error": str(exc), "code": exc.code}, exc.status)
        if exc.status in {429, 503}:
            response.headers["Retry-After"] = "30"
    except Exception as exc:
        from memorphia_scanner.analysis.wavespeed_hybrid import HybridImageError

        if isinstance(exc, HybridImageError):
            response = json_response({"error": str(exc), "code": exc.code}, exc.status)
        else:
            logger.exception(
                "HTTP request failed: %s %s",
                request.method,
                urlsplit(request.target).path,
            )
            response = json_response(
                {
                    "error": "Service is temporarily unavailable.",
                    "code": "service_unavailable",
                },
                503,
            )
    response.headers.update(SECURITY_HEADERS)
    if os.getenv("MEMORPHIA_PUBLIC_ORIGIN", "").startswith("https:"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000"
    return response


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "Memorphia"
    sys_version = ""

    def setup(self):
        super().setup()
        self.connection.settimeout(20)

    def _dispatch(self):
        try:
            raw_length = self.headers.get("Content-Length", "0")
            if (
                not raw_length.isdecimal()
                or self.headers.get("Transfer-Encoding")
                or len(self.headers.get_all("Content-Length", [])) > 1
            ):
                raise ApiError("Invalid request length.")
            size = int(raw_length)
            if size > MAX_BODY:
                raise ApiError("Request is too large.", "request_too_large", 413)
            if self.command == "POST" and not size:
                # Logout has no payload but still uses origin + CSRF checks.
                if urlsplit(self.path).path != "/api/auth/logout":
                    raise ApiError("Request body is empty.")
            body = self.rfile.read(size)
            if len(body) != size:
                raise ApiError("Request body is incomplete.")
            response = application(
                Request(
                    self.command,
                    self.path,
                    dict(self.headers),
                    body,
                    self.client_address[0],
                )
            )
        except ApiError as exc:
            response = json_response({"error": str(exc), "code": exc.code}, exc.status)
            response.headers.update(SECURITY_HEADERS)
        self.send_response(response.status)
        for key, value in response.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(response.body)))
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(response.body)
            except (BrokenPipeError, ConnectionResetError):
                pass

    do_GET = do_POST = do_HEAD = do_OPTIONS = _dispatch

    def log_message(self, *_):
        pass


class BoundedHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, *args, **kwargs):
        self.slots = threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, client_address):
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(
                    b"HTTP/1.1 503 Service Unavailable\r\nRetry-After: 3\r\nContent-Length: 0\r\nConnection: close\r\n\r\n"
                )
            finally:
                self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except BaseException:
            self.slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self.slots.release()


def wsgi_app(environ, start_response):
    headers = {
        key[5:].lower().replace("_", "-"): value
        for key, value in environ.items()
        if key.startswith("HTTP_")
    }
    headers["content-type"] = environ.get("CONTENT_TYPE", "")
    length = environ.get("CONTENT_LENGTH", "") or "0"
    if not length.isdecimal() or int(length) > MAX_BODY:
        response = json_response(
            {"error": "Invalid request size.", "code": "request_too_large"}, 413
        )
        response.headers.update(SECURITY_HEADERS)
    else:
        target = environ.get("PATH_INFO", "/")
        if environ.get("QUERY_STRING"):
            target += "?" + environ["QUERY_STRING"]
        response = application(
            Request(
                environ.get("REQUEST_METHOD", "GET"),
                target,
                headers,
                environ["wsgi.input"].read(int(length)),
                environ.get("REMOTE_ADDR", "unknown"),
            )
        )
    start_response(
        f"{response.status} {HTTPStatus(response.status).phrase}",
        [
            *response.headers.items(),
            ("Content-Length", str(len(response.body))),
        ],
    )
    return [b"" if environ.get("REQUEST_METHOD") == "HEAD" else response.body]
