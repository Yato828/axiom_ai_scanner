from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
from pathlib import Path

from axiom_scanner.analysis.narratives import generate_narratives, load_og_memecoins
from axiom_scanner.web_security import ApiError
from axiom_scanner.web_store import get_store, production

ROOT = Path(__file__).resolve().parent.parent
logger = logging.getLogger(__name__)
_local_started = False
_start_lock = threading.Lock()


def generation_features():
    if production() or os.getenv("REDIS_URL"):
        return json.loads(get_store().get("worker:features") or "{}")
    return {
        "hybrid": bool(
            os.getenv("WAVESPEED_API_KEY") or os.getenv("WAVESPEED_API_KEYS")
        ),
        "image": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEYS")),
    }


def heartbeat_loop(stop):
    while not stop.is_set():
        try:
            get_store().set(
                "worker:features",
                json.dumps(
                    {
                        "hybrid": bool(
                            os.getenv("WAVESPEED_API_KEY")
                            or os.getenv("WAVESPEED_API_KEYS")
                        ),
                        "image": bool(
                            os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEYS")
                        ),
                    }
                ),
                60,
            )
        except Exception:
            logger.exception("Worker heartbeat failed")
        stop.wait(15)


def runtime_config():
    from axiom_scanner.config import load_config

    configured = os.getenv("AXIOM_CONFIG_PATH", "")
    config = load_config(Path(configured) if configured else None)
    config.chains = ["solana"]
    return config


def refresh_scan():
    store, lease = get_store(), secrets.token_hex(16)
    if not store.set("scan:lock", lease, 180, nx=True):
        return
    try:
        from axiom_dashboard import scan_once

        config = runtime_config()
        rows = scan_once(config, limit=200)
        og = load_og_memecoins(ROOT, config.og_memecoins_path)
        store.set(
            "scan:result",
            json.dumps(
                {
                    "updated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                    "timestamp": time.time(),
                    "min_market_cap_usd": config.min_market_cap_usd,
                    "tokens": rows,
                    "og_memecoins": og,
                    "narratives": generate_narratives(rows, og, limit=12),
                }
            ),
            1800,
        )
        store.take("scan:error")
    except Exception:
        logger.exception("Market refresh failed")
        store.set(
            "scan:error",
            "Market data is temporarily unavailable. The last available feed will be kept.",
            120,
        )
    finally:
        store.release("scan:lock", lease)


def scan_payload(limit):
    ensure_local_workers()
    store = get_store()
    raw = store.get("scan:result")
    if not raw:
        error = store.get("scan:error")
        return {
            "status": "unavailable" if error else "loading",
            "message": error,
            "retry_after": 15 if error else 3,
            "tokens": [],
            "count": 0,
        }, 202
    payload = json.loads(raw)
    timestamp = payload.pop("timestamp")
    payload["tokens"] = payload["tokens"][:limit]
    payload["count"] = len(payload["tokens"])
    payload["stale"] = (
        time.time() - timestamp
        > max(int(os.getenv("AXIOM_SCAN_CACHE_SECONDS", "45")), 15) * 2
    )
    payload["status"] = "ready"
    if store.get("scan:error"):
        payload["warning"] = store.get("scan:error")
    return payload, 200


def enqueue_generation(kind, body, content_type, wallet, idempotency_key):
    if not idempotency_key or len(idempotency_key) > 100:
        raise ApiError("A request ID is required.")
    job_id = hashlib.sha256(
        (wallet + ":" + kind + ":" + idempotency_key).encode()
    ).hexdigest()
    fingerprint = hashlib.sha256(content_type.encode() + body).hexdigest()
    store = get_store()
    existing = store.get("job:" + job_id)
    if existing:
        record = json.loads(existing)
        if record["fingerprint"] != fingerprint:
            raise ApiError(
                "Request ID was already used for another image.",
                "idempotency_conflict",
                409,
            )
        return public_job(job_id, wallet)
    record = {
        "wallet": wallet,
        "kind": kind,
        "state": "queued",
        "created_at": time.time(),
        "body": base64.b64encode(body).decode(),
        "content_type": content_type,
        "fingerprint": fingerprint,
    }
    if not store.enqueue(job_id, record, int(os.getenv("AXIOM_QUEUE_CAPACITY", "16"))):
        raise ApiError(
            "The image queue is full. Please try again shortly.", "queue_full", 503
        )
    accepted = json.loads(store.get("job:" + job_id))
    if accepted["fingerprint"] != fingerprint:
        raise ApiError(
            "Request ID was already used for another image.",
            "idempotency_conflict",
            409,
        )
    ensure_local_workers()
    return public_job(job_id, wallet)


def public_job(job_id, wallet):
    if len(job_id) != 64 or any(char not in "0123456789abcdef" for char in job_id):
        raise ApiError("Job was not found.", "not_found", 404)
    raw = get_store().get("job:" + job_id)
    if not raw or json.loads(raw)["wallet"] != wallet:
        raise ApiError("Job was not found.", "not_found", 404)
    record = json.loads(raw)
    state = record["state"]
    if state in {"queued", "running"} and time.time() - record["created_at"] > 900:
        state = "failed"
        record["error"] = (
            "Generation did not finish in time. Check your previous request before retrying."
        )
    return {
        "job_id": job_id,
        "state": state,
        "result": record.get("result"),
        "error": record.get("error"),
    }


def execute_job(job_id):
    store = get_store()
    raw = store.get("job:" + job_id)
    if not raw:
        return
    record = json.loads(raw)
    if record["state"] != "queued":
        return
    record["state"] = "running"
    store.set("job:" + job_id, json.dumps(record), 3600)
    try:
        body = base64.b64decode(record.pop("body"))
        if record["kind"] == "hybrid":
            from axiom_scanner.analysis.wavespeed_hybrid import (
                generate_hybrid_image_request,
            )

            result = generate_hybrid_image_request(
                record["content_type"], body, ROOT / "web"
            )
        else:
            from axiom_scanner.analysis.image_generation import generate_meme_image

            result = generate_meme_image(
                json.loads(body), resolve_og_image=lambda name, symbol: ""
            )
        result.pop("api_key_index", None)
        record.update(state="completed", result=result)
    except Exception:
        logger.exception("Image generation failed for job %s", job_id)
        record.pop("body", None)
        record.update(
            state="failed",
            error="Image generation failed. Please check the inputs or try again later.",
        )
    store.set("job:" + job_id, json.dumps(record), 3600)


def generation_loop(stop):
    while not stop.is_set():
        try:
            job_id = get_store().dequeue()
            if job_id:
                execute_job(job_id)
                continue
        except Exception:
            logger.exception("Image queue worker failed")
        stop.wait(1)


def market_loop(stop):
    while not stop.is_set():
        try:
            refresh_scan()
        except Exception:
            logger.exception("Market worker failed")
        stop.wait(max(int(os.getenv("AXIOM_SCAN_CACHE_SECONDS", "45")), 15))


def ensure_local_workers():
    global _local_started
    if production() or os.getenv("REDIS_URL"):
        return
    with _start_lock:
        if _local_started:
            return
        _local_started = True
        stop = threading.Event()
        threading.Thread(target=market_loop, args=(stop,), daemon=True).start()
        for _ in range(2):
            threading.Thread(target=generation_loop, args=(stop,), daemon=True).start()
