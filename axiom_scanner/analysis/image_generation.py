from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class ImageGenerationError(RuntimeError):
    def __init__(self, message: str, code: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


def generate_meme_image(
    payload: dict[str, Any],
    resolve_og_image: Callable[[str, str], str],
) -> dict[str, Any]:
    api_keys = get_openai_api_keys()
    if not api_keys:
        raise ImageGenerationError(
            "OPENAI_API_KEY or OPENAI_API_KEYS is not set. Add it to your environment to generate images.",
            code="missing_api_key",
            status=412,
        )

    narrative = payload.get("narrative") or {}
    token = payload.get("token") or {}
    og = payload.get("og") or {}
    if not isinstance(narrative, dict) or not isinstance(token, dict) or not isinstance(og, dict):
        raise ImageGenerationError("narrative, token, and og must be objects.", "bad_request")

    trend_image_url = str(
        payload.get("trend_image_url")
        or narrative.get("trend_image_url")
        or token.get("image_url")
        or ""
    )
    og_name = str(og.get("name") or narrative.get("og_name") or "")
    og_symbol = str(og.get("symbol") or narrative.get("og_token") or "")
    og_image_url = str(
        payload.get("og_image_url")
        or narrative.get("og_image_url")
        or og.get("image_url")
        or resolve_og_image(og_name, og_symbol)
        or ""
    )

    if not trend_image_url:
        raise ImageGenerationError(
            "The trend token has no reference image, so the model cannot preserve its identity.",
            code="missing_trend_image",
            status=422,
        )

    prompt = _build_prompt(narrative, token, og)
    content: list[dict[str, str]] = [{"type": "input_text", "text": prompt}]
    content.append({"type": "input_image", "image_url": trend_image_url})
    if og_image_url:
        content.append({"type": "input_image", "image_url": og_image_url})

    request_payload = {
        "model": os.getenv("OPENAI_RESPONSES_MODEL", "gpt-5.5"),
        "input": [{"role": "user", "content": content}],
        "tools": [
            {
                "type": "image_generation",
                "size": os.getenv("OPENAI_IMAGE_SIZE", "1024x1024"),
                "quality": os.getenv("OPENAI_IMAGE_QUALITY", "medium"),
            }
        ],
        "tool_choice": {"type": "image_generation"},
    }
    last_error: ImageGenerationError | None = None
    for key_index, api_key in enumerate(api_keys, start=1):
        try:
            response = _post_json(
                "https://api.openai.com/v1/responses",
                request_payload,
                api_key=api_key,
                timeout_seconds=int(os.getenv("OPENAI_IMAGE_TIMEOUT", "120")),
            )
            break
        except ImageGenerationError as exc:
            last_error = exc
            if not should_try_next_openai_key(exc) or key_index == len(api_keys):
                raise
    else:
        if last_error:
            raise last_error
        raise ImageGenerationError("The image request failed.", "openai_error", 502)

    image_base64 = _extract_image_base64(response)
    if not image_base64:
        raise ImageGenerationError(
            "The image model did not return an image.",
            code="no_image_returned",
            status=502,
        )

    return {
        "image_data_url": f"data:image/png;base64,{image_base64}",
        "trend_image_url": trend_image_url,
        "og_image_url": og_image_url,
        "prompt": prompt,
        "api_key_index": key_index,
    }


def get_openai_api_keys() -> list[str]:
    raw_keys = os.getenv("OPENAI_API_KEYS", "").strip()
    if raw_keys:
        keys = re.split(r"[\s,;]+", raw_keys)
    else:
        keys = [os.getenv("OPENAI_API_KEY", "").strip()]

    seen: set[str] = set()
    result: list[str] = []
    for key in keys:
        clean_key = key.strip()
        if clean_key and clean_key not in seen:
            result.append(clean_key)
            seen.add(clean_key)
    return result


def should_try_next_openai_key(exc: ImageGenerationError) -> bool:
    if exc.code not in {"openai_error", "network_error"}:
        return False

    message = str(exc).lower()
    retry_markers = {
        "billing",
        "credit",
        "insufficient",
        "payment",
        "quota",
        "rate",
        "limit",
        "unauthorized",
        "forbidden",
        "invalid api key",
        "api key",
        "temporarily",
        "timeout",
        "timed out",
        "connection",
    }
    return exc.status in {401, 403, 408, 409, 429, 500, 502, 503, 504} or any(
        marker in message for marker in retry_markers
    )


def _build_prompt(narrative: dict[str, Any], token: dict[str, Any], og: dict[str, Any]) -> str:
    trend_label = f"{token.get('token') or narrative.get('trend_token') or 'the trend token'}"
    if token.get("name"):
        trend_label += f" ({token.get('name')})"
    og_label = f"{og.get('name') or narrative.get('og_name') or 'the OG meme coin'}"
    og_symbol = og.get("symbol") or narrative.get("og_token")
    if og_symbol:
        og_label += f" (${og_symbol})"
    modifiers = narrative.get("visual_modifiers") or []
    if isinstance(modifiers, list):
        modifier_text = ", ".join(str(item) for item in modifiers if item)
    else:
        modifier_text = str(modifiers)

    return (
        "Create one square crypto meme artwork from the supplied reference images. "
        f"The FIRST image is the main subject: keep {trend_label} recognizable and keep its "
        "core silhouette, face, pose, and identity. The SECOND image is only a style and "
        f"accessory reference from {og_label}. Do not replace the first subject with the "
        "second subject. Add the second coin's elements as accessories, atmosphere, props, "
        f"and background details: {modifier_text}. "
        f"Visual brief: {narrative.get('visual_brief') or narrative.get('image_prompt') or ''} "
        "Use bold meme-coin composition, crisp sticker-like rendering, high contrast, and "
        "readable focal point. Avoid tiny text, fake UI, clutter, and unrelated mascots."
    )


def _post_json(url: str, payload: dict[str, Any], api_key: str, timeout_seconds: int) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw).get("error", {}).get("message", raw)
        except json.JSONDecodeError:
            detail = raw
        raise ImageGenerationError(str(detail), "openai_error", exc.code) from exc
    except (TimeoutError, URLError, json.JSONDecodeError) as exc:
        raise ImageGenerationError(str(exc), "network_error", 502) from exc


def _extract_image_base64(response: dict[str, Any]) -> str:
    for output in response.get("output", []):
        if not isinstance(output, dict):
            continue
        if output.get("type") == "image_generation_call" and output.get("result"):
            return str(output["result"])
        for content in output.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_image", "image"}:
                if content.get("image_base64"):
                    return str(content["image_base64"])
                if content.get("b64_json"):
                    return str(content["b64_json"])
    return ""


def url_to_data_url(url: str, timeout_seconds: int = 15) -> str:
    request = Request(url, headers={"User-Agent": "axiom-ai-scanner/0.1"})
    with urlopen(request, timeout=timeout_seconds) as response:
        body = response.read()
        content_type = response.headers.get_content_type()
    if not content_type or content_type == "application/octet-stream":
        content_type = mimetypes.guess_type(url)[0] or "image/png"
    encoded = base64.b64encode(body).decode("ascii")
    return f"data:{content_type};base64,{encoded}"
