"""Fetch public HTTPS images without redirects into private networks or DNS rebinding."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import ssl
import warnings
from io import BytesIO
from urllib.parse import urljoin, urlsplit

from memorphia_scanner.web_security import ApiError

MAX_IMAGE_BYTES = 3 * 1024 * 1024
MAX_PIXELS = 16_000_000


def public_addresses(host):
    try:
        addresses = list(
            dict.fromkeys(
                item[4][0]
                for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            )
        )
    except OSError as exc:
        raise ApiError(
            "Image host could not be reached.", "image_unavailable", 422
        ) from exc
    if not addresses or any(
        not ipaddress.ip_address(address).is_global for address in addresses
    ):
        raise ApiError("Only public image hosts are allowed.", "unsafe_image_url", 422)
    return addresses


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, address):
        super().__init__(host, timeout=15, context=ssl.create_default_context())
        self.address = address

    def connect(self):
        sock = socket.create_connection((self.address, 443), self.timeout)
        try:
            self.sock = self._context.wrap_socket(sock, server_hostname=self.host)
        except BaseException:
            sock.close()
            raise


def download_image(url, max_bytes=MAX_IMAGE_BYTES):
    for _ in range(4):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ApiError("Invalid image URL.", "unsafe_image_url", 422) from exc
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or port not in (None, 443)
            or len(url) > 2048
            or "\\" in url
        ):
            raise ApiError("Use a public HTTPS image URL.", "unsafe_image_url", 422)
        host = parsed.hostname.encode("idna").decode("ascii")
        address = public_addresses(host)[0]
        connection = PinnedHTTPSConnection(host, address)
        try:
            connection.request(
                "GET",
                parsed.path + ("?" + parsed.query if parsed.query else "") or "/",
                headers={"User-Agent": "Memorphia/1.0", "Accept": "image/*"},
            )
            response = connection.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                url = urljoin(url, response.getheader("Location", ""))
                continue
            if response.status != 200:
                raise ApiError(
                    "Image host rejected the request. Upload the image file instead.",
                    "image_unavailable",
                    422,
                )
            data = response.read(max_bytes + 1)
            if len(data) > max_bytes:
                raise ApiError(
                    "Image must be smaller than 3 MB.", "image_too_large", 413
                )
            return data, response.getheader(
                "Content-Type", "application/octet-stream"
            ).split(";")[0]
        except (OSError, http.client.HTTPException) as exc:
            raise ApiError(
                "Image host is unavailable. Upload the file instead.",
                "image_unavailable",
                422,
            ) from exc
        finally:
            connection.close()
    raise ApiError("Image URL redirects too many times.", "image_unavailable", 422)


def normalize_image(data):
    from PIL import Image, ImageOps, UnidentifiedImageError

    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ApiError(
            "Upload a PNG, JPEG or WebP image smaller than 3 MB.", "invalid_image", 422
        )
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(data)) as image:
                if image.format not in {"PNG", "JPEG", "WEBP"}:
                    raise ApiError(
                        "Use a PNG, JPEG or WebP image.", "invalid_image", 422
                    )
                if image.width * image.height > MAX_PIXELS or min(image.size) < 32:
                    raise ApiError(
                        "Image dimensions must be at least 32 px and at most 16 megapixels.",
                        "invalid_image",
                        422,
                    )
                normalized = ImageOps.exif_transpose(image).convert("RGBA")
                normalized.thumbnail((1024, 1024), Image.Resampling.LANCZOS)
                output = BytesIO()
                normalized.save(output, "PNG")
                result = output.getvalue()
                if len(result) > MAX_IMAGE_BYTES:
                    raise ApiError(
                        "Normalized image is too large.", "image_too_large", 413
                    )
                return result
    except (
        UnidentifiedImageError,
        OSError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ApiError(
            "Image could not be decoded safely.", "invalid_image", 422
        ) from exc
