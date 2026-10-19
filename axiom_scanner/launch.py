"""Validate and pin public token metadata; wallet signing stays in the browser."""

from __future__ import annotations

import json
import os
import re
import unicodedata
import uuid
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from axiom_scanner.safe_images import normalize_image
from axiom_scanner.web_security import ApiError

PUMP_PROGRAM = "6EF8rrecthR5Dkzon8Nwu78hRvfCKubJ14M5uBEwF6P"
MAINNET_GENESIS = "5eykt4UsFv8P8NJdTREpY1vzqKqZKvdp"


def text_field(value, label, maximum, required=False):
    if not isinstance(value, str):
        raise ApiError(f"{label} must be text.")
    value = unicodedata.normalize("NFC", value.strip())
    if (required and not value) or len(value.encode("utf-8")) > maximum:
        raise ApiError(
            f"{label} must be between {1 if required else 0} and {maximum} UTF-8 bytes."
        )
    if any(
        unicodedata.category(char).startswith("C") and char not in "\n\t"
        for char in value
    ):
        raise ApiError(f"{label} contains unsupported control characters.")
    return value


def validate_metadata(payload):
    name = text_field(payload.get("name", ""), "Name", 32, True)
    symbol = (
        text_field(payload.get("symbol", ""), "Ticker", 13, True).upper().lstrip("$")
    )
    if not re.fullmatch(r"[A-Z0-9]{1,13}", symbol):
        raise ApiError("Ticker must contain 1–13 letters or numbers.")
    result = {
        "name": name,
        "symbol": symbol,
        "description": text_field(payload.get("description", ""), "Description", 1000),
        "showName": True,
    }
    for key in ("website", "twitter", "telegram"):
        value = text_field(payload.get(key, ""), key.title(), 256)
        if value:
            parsed = urlsplit(value)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.port not in (None, 443)
                or "\\" in value
            ):
                raise ApiError(f"{key.title()} must be an HTTPS link.")
            if key == "twitter" and parsed.hostname.lower() not in {
                "x.com",
                "www.x.com",
                "twitter.com",
                "www.twitter.com",
            }:
                raise ApiError("X link must use x.com or twitter.com.")
            if key == "telegram" and parsed.hostname.lower() not in {
                "t.me",
                "www.t.me",
            }:
                raise ApiError("Telegram link must use t.me.")
            result[key] = value
    return result


def launch_config():
    enabled = os.getenv("AXIOM_LAUNCH_ENABLED", "1") == "1"
    storage = bool(os.getenv("PINATA_JWT", "").strip())
    rpc = bool(os.getenv("SOLANA_RPC_URL", "").strip())
    return {
        "enabled": enabled and storage and rpc,
        "network": "mainnet-beta",
        "platform": "pump.fun",
        "program": PUMP_PROGRAM,
        "genesis_hash": MAINNET_GENESIS,
        "storage_ready": storage,
        "rpc_ready": rpc,
        "message": "Ready to launch on Solana mainnet."
        if enabled and storage and rpc
        else "Launch is being configured. You can prepare and download your token draft.",
    }


def pin_file(data, filename, content_type):
    jwt = os.getenv("PINATA_JWT", "").strip()
    if not jwt:
        raise ApiError(
            "Token image hosting is not configured yet.", "storage_unavailable", 503
        )
    boundary = "degenmixer-" + uuid.uuid4().hex
    body = (
        (
            f'--{boundary}\r\nContent-Disposition: form-data; name="network"\r\n\r\npublic\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        + data
        + f"\r\n--{boundary}--\r\n".encode()
    )
    request = Request(
        "https://uploads.pinata.cloud/v3/files",
        data=body,
        method="POST",
        headers={
            "Authorization": "Bearer " + jwt,
            "Content-Type": "multipart/form-data; boundary=" + boundary,
        },
    )
    try:
        with urlopen(request, timeout=25) as response:
            result = json.loads(response.read(64_000))
        cid = result["data"]["cid"]
        if not isinstance(cid, str) or not re.fullmatch(r"[A-Za-z0-9]{32,100}", cid):
            raise ValueError("Invalid storage CID")
        return "https://ipfs.io/ipfs/" + cid
    except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
        raise ApiError(
            "Token files could not be stored. No transaction was sent.",
            "storage_unavailable",
            502,
        ) from exc


def publish_metadata(fields, image_bytes):
    metadata = validate_metadata(fields)
    image = normalize_image(image_bytes)
    metadata["image"] = pin_file(image, "token.png", "image/png")
    uri = pin_file(
        json.dumps(metadata, ensure_ascii=False).encode(),
        "metadata.json",
        "application/json",
    )
    if len(uri.encode()) > 200:
        raise ApiError("Metadata URI is too long.", "storage_unavailable", 502)
    return {"metadata": metadata, "uri": uri, "network": "mainnet-beta"}


RPC_METHODS = {
    "getGenesisHash",
    "getLatestBlockhash",
    "getBalance",
    "getFeeForMessage",
    "getMinimumBalanceForRentExemption",
    "simulateTransaction",
    "sendTransaction",
    "getSignatureStatuses",
    "getBlockHeight",
}


def rpc_request(payload):
    if payload.get("method") not in RPC_METHODS or not isinstance(
        payload.get("params", []), list
    ):
        raise ApiError("Unsupported RPC request.", "rpc_method_not_allowed", 403)
    url = os.getenv("SOLANA_RPC_URL", "").strip()
    if not url or urlsplit(url).scheme != "https":
        raise ApiError(
            "Solana connection is not configured yet.", "rpc_unavailable", 503
        )
    request = Request(
        url,
        data=json.dumps(
            {
                "jsonrpc": "2.0",
                "id": payload.get("id", 1),
                "method": payload["method"],
                "params": payload.get("params", []),
            }
        ).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read(512_001)
        if len(raw) > 512_000:
            raise ValueError("RPC response exceeded limit")
        result = json.loads(raw)
        if "error" in result:
            # Do not expose provider credentials or upstream diagnostics to the browser.
            error = result["error"]
            code = error.get("code", -32000) if isinstance(error, dict) else -32000
            result["error"] = {
                "code": code,
                "message": "Solana rejected the request. Check balance, network and transaction status.",
            }
        return result
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        raise ApiError(
            "Solana is temporarily unavailable. Check the transaction status before retrying.",
            "rpc_unavailable",
            502,
        ) from exc
