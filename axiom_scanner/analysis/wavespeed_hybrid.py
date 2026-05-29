from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from io import BytesIO
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote_to_bytes, urlparse
from urllib.request import Request, urlopen


WAVESPEED_BASE_URL = "https://api.wavespeed.ai/api/v3"
WAVESPEED_UPLOAD_URL = f"{WAVESPEED_BASE_URL}/media/upload/binary"
WAVESPEED_PRIMARY_MODEL = "bytedance/seedream-v4.5/edit"
WAVESPEED_FALLBACK_MODEL = "bytedance/seedream-v4/edit"

MAX_IMAGE_BYTES = 20 * 1024 * 1024
MAX_REQUEST_BYTES = 45 * 1024 * 1024
ALLOWED_IMAGE_TYPES = {
    "image/bmp",
    "image/gif",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/webp",
}
NORMALIZED_IMAGE_CONTENT_TYPE = "image/png"
NORMALIZED_IMAGE_MIN_SIDE = 512
NORMALIZED_IMAGE_MAX_SIDE = 1536
DEFAULT_POLL_INTERVAL_SECONDS = 1.0
DEFAULT_PROMPT = (
    "Combine the two reference images into one coherent hybrid character or emblem. "
    "Preserve recognizable visual traits from both inputs, match lighting and "
    "perspective naturally, and make the result feel like one polished sticker-style artwork."
)
SAFE_PROVIDER_PROMPT = (
    "Create one polished family-friendly sticker-style character or emblem from the two "
    "reference images. Combine the most recognizable colors, shapes, silhouettes, and "
    "visual details from both references into a single original design. Use a centered "
    "composition, clean background, crisp edges, soft studio lighting, no text, no logos, "
    "no UI, no watermark."
)
PROMPT_BLOCKLIST = (
    "crypto",
    "coin",
    "token",
    "ticker",
    "solana",
    "degen",
    "raid",
    "raids",
    "trump",
    "political",
    "weapon",
    "blood",
    "nsfw",
)


class HybridImageError(RuntimeError):
    def __init__(self, message: str, code: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass
class HybridImage:
    field_name: str
    filename: str
    content_type: str
    data: bytes
    source_url: str = ""


def generate_hybrid_image_request(
    content_type: str,
    body: bytes,
    web_root: Path,
) -> dict[str, Any]:
    api_keys = get_wavespeed_api_keys()
    if not api_keys:
        raise HybridImageError(
            "WAVESPEED_API_KEY or WAVESPEED_API_KEYS is not set. Add it to .env and restart the web server.",
            code="missing_api_key",
            status=412,
        )

    fields, files = parse_request_body(content_type, body)
    prompt = (fields.get("prompt") or "").strip() or DEFAULT_PROMPT
    size = normalize_size(fields.get("size") or os.getenv("WAVESPEED_IMAGE_SIZE", "1024*1024"))

    image_a = resolve_input_image("image_a", fields, files, web_root)
    image_b = resolve_input_image("image_b", fields, files, web_root)
    normalized_images = normalize_images_for_provider([image_a, image_b])

    last_error: HybridImageError | None = None
    for key_index, api_key in enumerate(api_keys, start=1):
        try:
            return generate_hybrid_with_key(
                image_a=normalized_images[0],
                image_b=normalized_images[1],
                prompt=prompt,
                size=size,
                api_key=api_key,
                key_index=key_index,
            )
        except HybridImageError as exc:
            last_error = exc
            if not should_try_next_key(exc) or key_index == len(api_keys):
                raise

    if last_error:
        raise last_error
    raise HybridImageError("Hybrid generation failed.", "generation_failed", 502)


def generate_hybrid_with_key(
    image_a: HybridImage,
    image_b: HybridImage,
    prompt: str,
    size: str,
    api_key: str,
    key_index: int,
) -> dict[str, Any]:
    prompt = sanitize_provider_prompt(prompt)
    log_hybrid_event(
        "start",
        key_index=key_index,
        image_a=f"{image_a.content_type}:{len(image_a.data)}",
        image_b=f"{image_b.content_type}:{len(image_b.data)}",
        size=size,
    )
    image_urls = upload_images([image_a, image_b], api_key=api_key)
    log_hybrid_event("uploaded", key_index=key_index, count=len(image_urls))

    attempts = [
        (WAVESPEED_PRIMARY_MODEL, prompt),
        (WAVESPEED_PRIMARY_MODEL, SAFE_PROVIDER_PROMPT),
        (WAVESPEED_FALLBACK_MODEL, SAFE_PROVIDER_PROMPT),
    ]
    last_error: HybridImageError | None = None
    for attempt_index, (model, attempt_prompt) in enumerate(attempts, start=1):
        try:
            return run_generation_attempt(
                image_urls=image_urls,
                image_a=image_a,
                image_b=image_b,
                prompt=attempt_prompt,
                size=size,
                api_key=api_key,
                key_index=key_index,
                attempt_index=attempt_index,
                model=model,
            )
        except HybridImageError as exc:
            last_error = exc
            if exc.code != "provider_rejected" or attempt_index == len(attempts):
                raise

    if last_error:
        raise last_error
    raise HybridImageError("Hybrid generation failed.", "generation_failed", 502)


def run_generation_attempt(
    image_urls: list[str],
    image_a: HybridImage,
    image_b: HybridImage,
    prompt: str,
    size: str,
    api_key: str,
    key_index: int,
    attempt_index: int,
    model: str,
) -> dict[str, Any]:
    submitted = submit_seedream_edit(
        image_urls=image_urls,
        prompt=prompt,
        size=size,
        api_key=api_key,
        model=model,
    )
    request_id = str((submitted.get("data") or {}).get("id") or "")
    submitted_data = submitted.get("data") or {}
    log_hybrid_event(
        "submitted",
        key_index=key_index,
        attempt=attempt_index,
        model=model,
        request_id=request_id or "-",
        status=str(submitted_data.get("status") or "-"),
    )
    if not request_id:
        raise HybridImageError(
            "WaveSpeed did not return a prediction id.",
            code="missing_prediction_id",
            status=502,
        )

    result = submitted if submitted_data.get("status") in {"completed", "failed"} else poll_prediction(
        request_id,
        api_key=api_key,
    )
    data = result.get("data") or {}
    outputs = data.get("outputs") or []
    if data.get("status") != "completed" or not outputs:
        message = str(data.get("error") or "WaveSpeed did not return an output image.")
        log_hybrid_event(
            "failed",
            key_index=key_index,
            attempt=attempt_index,
            model=model,
            request_id=request_id,
            status=str(data.get("status") or "-"),
            error=message,
        )
        raise HybridImageError(
            f"{message} Request id: {request_id}",
            code="provider_rejected",
            status=502,
        )
    log_hybrid_event(
        "completed",
        key_index=key_index,
        attempt=attempt_index,
        model=model,
        request_id=request_id,
    )

    return {
        "request_id": request_id,
        "status": data.get("status"),
        "output_url": outputs[0],
        "outputs": outputs,
        "source_urls": [image_a.source_url, image_b.source_url],
        "size": size,
        "api_key_index": key_index,
        "model": model,
        "attempt": attempt_index,
    }


def get_wavespeed_api_keys() -> list[str]:
    raw_keys = os.getenv("WAVESPEED_API_KEYS", "").strip()
    if raw_keys:
        keys = re.split(r"[\s,;]+", raw_keys)
    else:
        keys = [os.getenv("WAVESPEED_API_KEY", "").strip()]

    seen: set[str] = set()
    result: list[str] = []
    for key in keys:
        clean_key = key.strip()
        if clean_key and clean_key not in seen:
            result.append(clean_key)
            seen.add(clean_key)
    return result


def should_try_next_key(exc: HybridImageError) -> bool:
    if exc.code not in {"wavespeed_error", "provider_rejected"}:
        return False

    message = str(exc).lower()
    retry_markers = {
        "balance",
        "credit",
        "insufficient",
        "payment",
        "quota",
        "rate",
        "limit",
        "top-up",
        "top up",
        "unauthorized",
        "forbidden",
        "suspended",
    }
    return any(marker in message for marker in retry_markers)


def parse_request_body(
    content_type: str,
    body: bytes,
) -> tuple[dict[str, str], dict[str, HybridImage]]:
    if "multipart/form-data" in content_type:
        return parse_multipart(content_type, body)
    if "application/json" in content_type:
        try:
            payload = json.loads(body.decode("utf-8") or "{}")
        except json.JSONDecodeError as exc:
            raise HybridImageError("Invalid JSON body.", "bad_json") from exc
        if not isinstance(payload, dict):
            raise HybridImageError("JSON body must be an object.", "bad_json")
        return {key: str(value) for key, value in payload.items() if value is not None}, {}
    raise HybridImageError("Expected multipart/form-data or application/json.", "bad_content_type")


def parse_multipart(
    content_type: str,
    body: bytes,
) -> tuple[dict[str, str], dict[str, HybridImage]]:
    raw_message = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + body
    )
    message = BytesParser(policy=policy.default).parsebytes(raw_message)
    if not message.is_multipart():
        raise HybridImageError("Malformed multipart body.", "bad_multipart")

    fields: dict[str, str] = {}
    files: dict[str, HybridImage] = {}
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if not name:
            continue

        payload = part.get_payload(decode=True) or b""
        filename = part.get_param("filename", header="content-disposition")
        if filename and payload:
            files[name] = HybridImage(
                field_name=name,
                filename=safe_filename(filename),
                content_type=part.get_content_type(),
                data=payload,
            )
        else:
            charset = part.get_content_charset("utf-8")
            fields[name] = payload.decode(charset, errors="replace")

    return fields, files


def resolve_input_image(
    field_name: str,
    fields: dict[str, str],
    files: dict[str, HybridImage],
    web_root: Path,
) -> HybridImage:
    file = files.get(field_name)
    if file and file.data:
        return validate_image(file, field_name)

    url = (fields.get(f"{field_name}_url") or "").strip()
    if not url:
        raise HybridImageError(f"{field_name} is required.", code="missing_image")
    return load_image_from_url(url, field_name, web_root)


def validate_image(image: HybridImage, field_name: str) -> HybridImage:
    if not image.data:
        raise HybridImageError(f"{field_name} is empty.", code="missing_image")
    if len(image.data) > MAX_IMAGE_BYTES:
        raise HybridImageError(f"{field_name} is too large.", code="image_too_large", status=413)
    if image.content_type not in ALLOWED_IMAGE_TYPES:
        raise HybridImageError(
            f"{field_name} must be JPG, PNG, WebP, GIF, BMP, or TIFF.",
            code="unsupported_image_type",
        )
    return image


def normalize_image_for_provider(image: HybridImage) -> HybridImage:
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError as exc:
        raise HybridImageError(
            "Pillow is required for image normalization. Run: python -m pip install -r requirements.txt",
            code="missing_pillow",
            status=500,
        ) from exc

    try:
        with Image.open(BytesIO(image.data)) as opened:
            normalized = ImageOps.exif_transpose(opened)
            normalized.load()
    except UnidentifiedImageError as exc:
        raise HybridImageError(
            f"{image.field_name} is not a readable raster image. Use PNG, JPG, or WebP.",
            code="invalid_image",
            status=422,
        ) from exc

    if normalized.mode in {"RGBA", "LA"} or (
        normalized.mode == "P" and "transparency" in normalized.info
    ):
        rgba = normalized.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        normalized = background.convert("RGB")
    else:
        normalized = normalized.convert("RGB")

    width, height = normalized.size
    if width <= 0 or height <= 0:
        raise HybridImageError(
            f"{image.field_name} has invalid dimensions.",
            code="invalid_image",
            status=422,
        )

    scale = 1.0
    shortest = min(width, height)
    longest = max(width, height)
    if shortest < NORMALIZED_IMAGE_MIN_SIDE:
        scale = NORMALIZED_IMAGE_MIN_SIDE / shortest
    if longest * scale > NORMALIZED_IMAGE_MAX_SIDE:
        scale = NORMALIZED_IMAGE_MAX_SIDE / longest

    if scale != 1.0:
        target_size = (
            max(1, round(width * scale)),
            max(1, round(height * scale)),
        )
        normalized = normalized.resize(target_size, Image.Resampling.LANCZOS)

    output = BytesIO()
    normalized.save(output, format="PNG", optimize=True)
    return HybridImage(
        field_name=image.field_name,
        filename=f"{Path(image.filename).stem or image.field_name}.png",
        content_type=NORMALIZED_IMAGE_CONTENT_TYPE,
        data=output.getvalue(),
        source_url=image.source_url,
    )


def normalize_images_for_provider(images: list[HybridImage]) -> list[HybridImage]:
    with ThreadPoolExecutor(max_workers=min(len(images), 2) or 1) as executor:
        return list(executor.map(normalize_image_for_provider, images))


def load_image_from_url(url: str, field_name: str, web_root: Path) -> HybridImage:
    if url.startswith("data:"):
        return validate_image(load_data_url(url, field_name), field_name)

    parsed = urlparse(url)
    if parsed.scheme in {"http", "https"}:
        return validate_image(load_remote_url(url, field_name), field_name)

    if url.startswith("/"):
        return validate_image(load_local_web_asset(url, field_name, web_root), field_name)

    raise HybridImageError(f"{field_name}_url is not a supported image URL.", "bad_image_url")


def load_data_url(url: str, field_name: str) -> HybridImage:
    header, _, raw_data = url.partition(",")
    if not raw_data or not header.startswith("data:"):
        raise HybridImageError(f"{field_name}_url is not a valid data URL.", "bad_image_url")

    metadata = header[5:]
    content_type = metadata.split(";", 1)[0] or "application/octet-stream"
    if ";base64" in metadata:
        data = base64.b64decode(raw_data, validate=True)
    else:
        data = unquote_to_bytes(raw_data)

    return HybridImage(
        field_name=field_name,
        filename=f"{field_name}{extension_for_type(content_type)}",
        content_type=content_type,
        data=data,
        source_url="data-url",
    )


def load_remote_url(url: str, field_name: str) -> HybridImage:
    request = Request(url, headers={"User-Agent": "axiom-ai-scanner/0.1"})
    try:
        with urlopen(request, timeout=20) as response:
            data = response.read(MAX_IMAGE_BYTES + 1)
            content_type = response.headers.get_content_type()
    except (HTTPError, URLError, TimeoutError) as exc:
        raise HybridImageError(
            f"Could not load {field_name}_url before uploading it to WaveSpeed.",
            code="image_url_unavailable",
            status=422,
        ) from exc

    if not content_type or content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(urlparse(url).path)[0] or "application/octet-stream"

    return HybridImage(
        field_name=field_name,
        filename=f"{field_name}{extension_for_type(content_type)}",
        content_type=content_type,
        data=data,
        source_url=url,
    )


def load_local_web_asset(url: str, field_name: str, web_root: Path) -> HybridImage:
    parsed = urlparse(url)
    full_path = (web_root / parsed.path.lstrip("/")).resolve()
    if not str(full_path).startswith(str(web_root.resolve())) or not full_path.is_file():
        raise HybridImageError(f"{field_name}_url does not point to a local web asset.", "bad_image_url")

    content_type = mimetypes.guess_type(str(full_path))[0] or "application/octet-stream"
    return HybridImage(
        field_name=field_name,
        filename=full_path.name,
        content_type=content_type,
        data=full_path.read_bytes(),
        source_url=url,
    )


def normalize_size(value: str) -> str:
    match = re.fullmatch(r"\s*(\d{3,4})\s*[*xX]\s*(\d{3,4})\s*", value or "")
    if not match:
        raise HybridImageError("Size must look like 1024*1024.", code="bad_size")

    width = int(match.group(1))
    height = int(match.group(2))
    if not (512 <= width <= 8192 and 512 <= height <= 8192):
        raise HybridImageError("Size dimensions must be between 512 and 8192.", code="bad_size")
    return f"{width}*{height}"


def upload_media(image: HybridImage, api_key: str) -> str:
    boundary = f"----wavespeed-upload-{uuid.uuid4().hex}"
    body = build_file_form_body(boundary, image)
    response = request_json(
        WAVESPEED_UPLOAD_URL,
        method="POST",
        body=body,
        api_key=api_key,
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout_seconds=60,
    )
    data = response.get("data") or {}
    download_url = str(data.get("download_url") or data.get("url") or "")
    if not download_url:
        raise HybridImageError("WaveSpeed upload did not return a file URL.", "upload_failed", 502)
    return download_url


def upload_images(images: list[HybridImage], api_key: str) -> list[str]:
    with ThreadPoolExecutor(max_workers=min(len(images), 2) or 1) as executor:
        return list(executor.map(lambda image: upload_media(image, api_key), images))


def submit_seedream_edit(
    image_urls: list[str],
    prompt: str,
    size: str,
    api_key: str,
    model: str,
) -> dict[str, Any]:
    payload = {
        "images": image_urls,
        "prompt": prompt,
        "size": size,
        "enable_sync_mode": wavespeed_sync_mode_enabled(),
        "enable_base64_output": False,
    }
    return request_json(
        f"{WAVESPEED_BASE_URL}/{model}",
        method="POST",
        json_payload=payload,
        api_key=api_key,
        timeout_seconds=submit_timeout_seconds(),
    )


def poll_prediction(request_id: str, api_key: str) -> dict[str, Any]:
    timeout_seconds = parse_positive_int(os.getenv("WAVESPEED_TIMEOUT_SECONDS", "120")) or 120
    poll_interval = parse_float(
        os.getenv("WAVESPEED_POLL_INTERVAL_SECONDS", "1.0"),
        DEFAULT_POLL_INTERVAL_SECONDS,
    )
    poll_interval = min(max(poll_interval, 0.5), 5.0)
    deadline = time.monotonic() + max(timeout_seconds, 10)
    url = f"{WAVESPEED_BASE_URL}/predictions/{request_id}/result"

    while True:
        result = request_json(url, method="GET", api_key=api_key, timeout_seconds=30)
        data = result.get("data") or {}
        status = data.get("status")
        if status in {"completed", "failed"}:
            return result
        if time.monotonic() >= deadline:
            raise HybridImageError(
                f"Generation is still processing. Request id: {request_id}",
                code="generation_timeout",
                status=504,
            )
        time.sleep(poll_interval)


def request_json(
    url: str,
    method: str,
    api_key: str,
    timeout_seconds: int,
    json_payload: dict[str, Any] | None = None,
    body: bytes | None = None,
    content_type: str = "application/json",
) -> dict[str, Any]:
    if json_payload is not None:
        body = json.dumps(json_payload).encode("utf-8")

    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
    }
    if body is not None:
        headers["Content-Type"] = content_type
        headers["Content-Length"] = str(len(body))

    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw = response.read().decode("utf-8")
    except HTTPError as exc:
        raise wavespeed_error_from_http(exc) from exc
    except (TimeoutError, URLError) as exc:
        raise HybridImageError(
            f"Could not reach WaveSpeed: {exc}",
            code="wavespeed_unreachable",
            status=502,
        ) from exc

    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HybridImageError("WaveSpeed returned invalid JSON.", "bad_wavespeed_json", 502) from exc


def wavespeed_error_from_http(exc: HTTPError) -> HybridImageError:
    raw = exc.read().decode("utf-8", errors="replace")
    message = raw or str(exc.reason)
    try:
        payload = json.loads(raw)
        message = str(payload.get("message") or payload.get("error") or message)
    except json.JSONDecodeError:
        pass
    return HybridImageError(f"WaveSpeed API error: {message}", "wavespeed_error", 502)


def build_file_form_body(boundary: str, image: HybridImage) -> bytes:
    filename = safe_filename(image.filename or f"{image.field_name}.png")
    headers = [
        f"--{boundary}",
        f'Content-Disposition: form-data; name="file"; filename="{filename}"',
        f"Content-Type: {image.content_type}",
        "",
        "",
    ]
    footer = f"\r\n--{boundary}--\r\n"
    return "\r\n".join(headers).encode("utf-8") + image.data + footer.encode("utf-8")


def safe_filename(value: str) -> str:
    filename = Path(value).name.replace('"', "").replace("\r", "").replace("\n", "")
    return filename or "image"


def sanitize_provider_prompt(prompt: str) -> str:
    text = re.sub(r"\$[A-Za-z0-9_]+", "", prompt or "")
    for word in PROMPT_BLOCKLIST:
        text = re.sub(rf"\b{re.escape(word)}\b", "theme", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > 600:
        text = text[:600].rsplit(" ", 1)[0]

    if not text:
        return SAFE_PROVIDER_PROMPT

    return (
        "Create one polished family-friendly sticker-style character or emblem from the "
        "two reference images. Keep it original and non-realistic. No text, no logos, "
        "no UI, no watermark. Additional direction: "
        f"{text}"
    )


def extension_for_type(content_type: str) -> str:
    return mimetypes.guess_extension(content_type) or ".png"


def parse_positive_int(value: str | None) -> int:
    try:
        return max(int(str(value or "0")), 0)
    except ValueError:
        return 0


def parse_float(value: str | None, fallback: float) -> float:
    try:
        return float(str(value or "").strip())
    except ValueError:
        return fallback


def wavespeed_sync_mode_enabled() -> bool:
    raw = os.getenv("WAVESPEED_SYNC_MODE", "false").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def submit_timeout_seconds() -> int:
    if wavespeed_sync_mode_enabled():
        return max(parse_positive_int(os.getenv("WAVESPEED_TIMEOUT_SECONDS", "120")) or 120, 60)
    return 60


def log_hybrid_event(event: str, **fields: object) -> None:
    try:
        log_dir = Path(os.getenv("AXIOM_LOG_DIR", "logs"))
        log_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        safe_fields = " ".join(
            f"{key}={str(value).replace(chr(10), ' ')[:240]}"
            for key, value in fields.items()
        )
        with (log_dir / "hybrid.log").open("a", encoding="utf-8") as handle:
            handle.write(f"{timestamp} event={event} {safe_fields}\n")
    except OSError:
        return
