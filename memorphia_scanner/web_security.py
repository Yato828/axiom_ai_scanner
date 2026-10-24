from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import os
import secrets
from contextlib import contextmanager
from http.cookies import CookieError, SimpleCookie
from urllib.parse import urlsplit

from memorphia_scanner.web_store import get_store, production


class ApiError(Exception):
    def __init__(self, message, code="bad_request", status=400):
        super().__init__(message)
        self.code, self.status = code, status


BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"


def decode_address(value):
    if not isinstance(value, str) or not 32 <= len(value) <= 44:
        raise ApiError("Invalid Solana wallet address.")
    number = 0
    try:
        for char in value:
            number = number * 58 + BASE58.index(char)
    except ValueError:
        raise ApiError("Invalid Solana wallet address.")
    result = b"\0" * (len(value) - len(value.lstrip("1")))
    result += number.to_bytes((number.bit_length() + 7) // 8, "big")
    if len(result) != 32 or result == bytes(32):
        raise ApiError("Invalid Solana wallet address.")
    return result


def public_origin(headers):
    configured = os.getenv("MEMORPHIA_PUBLIC_ORIGIN", "").rstrip("/")
    if configured:
        parsed = urlsplit(configured)
        if parsed.scheme != "https" and not (
            not production() and parsed.hostname in {"localhost", "127.0.0.1"}
        ):
            raise RuntimeError("MEMORPHIA_PUBLIC_ORIGIN must be HTTPS in production")
        if (
            parsed.path
            or parsed.query
            or parsed.fragment
            or parsed.username
            or not parsed.hostname
        ):
            raise RuntimeError("MEMORPHIA_PUBLIC_ORIGIN must contain only an origin")
        return configured
    if production():
        raise RuntimeError("MEMORPHIA_PUBLIC_ORIGIN is required in production")
    host = headers.get("host", "127.0.0.1:8080")
    parsed = urlsplit("http://" + host)
    if (
        parsed.hostname not in {"localhost", "127.0.0.1", "[::1]", "::1"}
        or parsed.username
        or parsed.path
    ):
        raise ApiError("Unrecognized site origin.", "bad_origin", 403)
    return "http://" + host


def check_origin(headers):
    origin = public_origin(headers)
    if headers.get("origin") != origin or headers.get("sec-fetch-site") == "cross-site":
        raise ApiError("Requests must come from this website.", "bad_origin", 403)
    return origin


def rate_limit(identity, scope, limit=120, seconds=60):
    key = hashlib.sha256(identity.encode()).hexdigest()
    if not get_store().rate(f"rate:{scope}:{key}", limit, seconds):
        raise ApiError(
            "Too many requests. Please try again shortly.", "rate_limited", 429
        )


@contextmanager
def capacity_gate(scope, capacity, ttl=90):
    store, token, chosen = get_store(), secrets.token_hex(16), None
    for slot in range(capacity):
        key = f"capacity:{scope}:{slot}"
        if store.set(key, token, ttl, nx=True):
            chosen = key
            break
    if chosen is None:
        raise ApiError(
            "This service is busy. Please try again shortly.", "service_busy", 503
        )
    try:
        yield
    finally:
        store.release(chosen, token)


def client_identity(remote, headers):
    # Enable only behind a proxy that overwrites X-Forwarded-For.
    if os.getenv("MEMORPHIA_TRUST_PROXY") == "1":
        candidate = headers.get("x-forwarded-for", "").split(",")[0].strip()
        try:
            return str(ipaddress.ip_address(candidate))
        except ValueError:
            pass
    return remote


def create_challenge(address, origin):
    decode_address(address)
    challenge_id = secrets.token_urlsafe(24)
    nonce = secrets.token_hex(16)
    message = (
        f"Memorphia sign in\nSite: {origin}\nWallet: {address}\n"
        f"Nonce: {nonce}\nExpires in: 5 minutes\n\n"
        "This proves wallet ownership. It does not authorize a transaction or transfer funds."
    )
    get_store().set(
        "challenge:" + challenge_id,
        json.dumps({"address": address, "origin": origin, "message": message}),
        300,
    )
    return {"challenge_id": challenge_id, "message": message}


def verify_challenge(payload, origin):
    challenge_id = payload.get("challenge_id", "")
    if not isinstance(challenge_id, str) or len(challenge_id) > 80:
        raise ApiError("Invalid sign-in challenge.")
    raw = get_store().get("challenge:" + challenge_id)
    if not raw:
        raise ApiError(
            "Sign-in expired. Please reconnect your wallet.", "challenge_expired", 401
        )
    challenge = json.loads(raw)
    if challenge["origin"] != origin:
        raise ApiError("Sign-in origin does not match.", "bad_origin", 403)
    try:
        from nacl.exceptions import BadSignatureError
        from nacl.signing import VerifyKey

        signature = base64.b64decode(payload.get("signature", ""), validate=True)
        if len(signature) != 64:
            raise ValueError("Invalid signature length")
        VerifyKey(decode_address(challenge["address"])).verify(
            challenge["message"].encode(), signature
        )
    except (ValueError, TypeError, BadSignatureError):
        raise ApiError(
            "Wallet signature could not be verified.", "invalid_signature", 401
        )
    if get_store().take("challenge:" + challenge_id) != raw:
        raise ApiError("This sign-in has already been used.", "challenge_used", 401)
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    session = {"wallet": challenge["address"], "csrf": csrf, "origin": origin}
    get_store().set(
        "session:" + hashlib.sha256(token.encode()).hexdigest(),
        json.dumps(session),
        86400,
    )
    cookie = f"dm_session={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400"
    if origin.startswith("https:"):
        cookie += "; Secure"
    return session, cookie


def session_key(headers):
    cookie = SimpleCookie()
    try:
        cookie.load(headers.get("cookie", ""))
        token = cookie["dm_session"].value
    except (KeyError, ValueError, CookieError):
        raise ApiError("Connect and verify your wallet first.", "wallet_required", 401)
    if len(token) > 100:
        raise ApiError("Invalid session.", "wallet_required", 401)
    return "session:" + hashlib.sha256(token.encode()).hexdigest()


def require_session(headers, csrf=True):
    raw = get_store().get(session_key(headers))
    if not raw:
        raise ApiError(
            "Session expired. Reconnect your wallet.", "wallet_required", 401
        )
    session = json.loads(raw)
    if session["origin"] != public_origin(headers):
        raise ApiError("Session belongs to another site.", "bad_origin", 403)
    if csrf and not hmac.compare_digest(
        headers.get("x-csrf-token", ""), session["csrf"]
    ):
        raise ApiError(
            "Session verification failed. Reconnect your wallet.", "invalid_csrf", 403
        )
    return session
