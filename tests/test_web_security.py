from __future__ import annotations

import base64
import io
import json
import os
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from http.cookies import SimpleCookie
from unittest.mock import patch

from nacl.signing import SigningKey
from PIL import Image

from axiom_scanner.launch import validate_metadata
from axiom_scanner.safe_images import download_image, normalize_image
from axiom_scanner.web_runtime import (
    enqueue_generation,
    public_job,
    refresh_scan,
    scan_payload,
)
from axiom_scanner.web_security import BASE58, ApiError, decode_address
from axiom_scanner.web_store import MemoryStore, get_store
from axiom_scanner.webapp import MAX_BODY, Request, application


def base58(data):
    number, result = int.from_bytes(data, "big"), ""
    while number:
        number, remainder = divmod(number, 58)
        result = BASE58[remainder] + result
    return "1" * (len(data) - len(data.lstrip(b"\0"))) + result


class WebSecurityTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {
                "AXIOM_ENV": "development",
                "REDIS_URL": "",
                "AXIOM_PUBLIC_ORIGIN": "",
                "AXIOM_TRUST_PROXY": "0",
            },
        )
        self.env.start()
        get_store.cache_clear()
        self.signer = SigningKey.generate()
        self.address = base58(bytes(self.signer.verify_key))
        self.headers = {
            "Host": "127.0.0.1:8080",
            "Origin": "http://127.0.0.1:8080",
            "Content-Type": "application/json",
        }

    def tearDown(self):
        get_store.cache_clear()
        self.env.stop()

    def request(self, path, payload=None, headers=None, method="POST"):
        body = json.dumps(payload).encode() if payload is not None else b""
        return application(
            Request(method, path, {**self.headers, **(headers or {})}, body)
        )

    def sign_in(self):
        challenge = json.loads(
            self.request("/api/auth/challenge", {"wallet": self.address}).body
        )
        signature = self.signer.sign(challenge["message"].encode()).signature
        payload = {
            "challenge_id": challenge["challenge_id"],
            "signature": base64.b64encode(signature).decode(),
        }
        response = self.request("/api/auth/verify", payload)
        self.assertEqual(response.status, 200, response.body)
        cookie = SimpleCookie()
        cookie.load(response.headers["Set-Cookie"])
        return payload, {
            "Cookie": "dm_session=" + cookie["dm_session"].value,
            "X-CSRF-Token": json.loads(response.body)["csrf"],
        }

    def test_signature_proves_wallet_and_challenge_is_single_use(self):
        payload, headers = self.sign_in()
        response = self.request("/api/session", headers=headers, method="GET")
        self.assertEqual(json.loads(response.body)["wallet"], self.address)
        self.assertEqual(self.request("/api/auth/verify", payload).status, 401)

    def test_forged_signature_and_cross_origin_requests_are_rejected(self):
        challenge = json.loads(
            self.request("/api/auth/challenge", {"wallet": self.address}).body
        )
        self.assertEqual(
            self.request(
                "/api/auth/verify",
                {
                    "challenge_id": challenge["challenge_id"],
                    "signature": base64.b64encode(bytes(64)).decode(),
                },
            ).status,
            401,
        )
        self.assertEqual(
            self.request(
                "/api/auth/challenge",
                {"wallet": self.address},
                {"Origin": "https://attacker.example"},
            ).status,
            403,
        )

    def test_csrf_required_and_session_revoked_on_logout(self):
        _, headers = self.sign_in()
        forged = {"Cookie": headers["Cookie"]}
        self.assertEqual(self.request("/api/auth/logout", headers=forged).status, 403)
        self.assertEqual(self.request("/api/auth/logout", headers=headers).status, 200)
        self.assertEqual(
            self.request("/api/session", headers=headers, method="GET").status, 401
        )

    def test_paid_actions_require_a_verified_wallet(self):
        for path in (
            "/api/hybrid-image",
            "/api/launch/metadata",
            "/api/rpc",
            "/api/images/import",
        ):
            self.assertEqual(self.request(path, {}).status, 401)

    def test_rpc_does_not_allow_arbitrary_methods(self):
        _, headers = self.sign_in()
        with patch("axiom_scanner.launch.urlopen") as upstream:
            response = self.request(
                "/api/rpc", {"method": "getProgramAccounts", "params": []}, headers
            )
            self.assertEqual(response.status, 403)
            upstream.assert_not_called()

    def test_static_paths_cannot_escape_web_root_and_csp_blocks_inline_script(self):
        response = self.request("/", method="GET")
        self.assertEqual(response.status, 200)
        self.assertIn("script-src 'self'", response.headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", response.headers["Content-Security-Policy"])
        self.assertEqual(self.request("/%2e%2e/README.md", method="GET").status, 404)
        cached = self.request(
            "/", headers={"If-None-Match": response.headers["ETag"]}, method="GET"
        )
        self.assertEqual(cached.status, 304)

    def test_json_shape_and_size_are_validated(self):
        self.assertEqual(self.request("/api/narratives", []).status, 400)
        self.assertEqual(
            self.request("/api/narratives", {"tokens": ["bad"]}).status, 400
        )
        response = application(
            Request("POST", "/api/narratives", self.headers, b"x" * (MAX_BODY + 1))
        )
        self.assertEqual(response.status, 413)

    def test_shared_rate_limits_apply_atomically_under_concurrency(self):
        store = MemoryStore()
        with ThreadPoolExecutor(max_workers=20) as pool:
            accepted = list(pool.map(lambda _: store.rate("test", 10, 60), range(100)))
        self.assertEqual(sum(accepted), 10)

    def test_user_cannot_bypass_rate_limit_using_forwarded_header(self):
        for index in range(10):
            self.assertEqual(
                self.request(
                    "/api/auth/challenge",
                    {"wallet": self.address},
                    {"X-Forwarded-For": str(index)},
                ).status,
                200,
            )
        self.assertEqual(
            self.request(
                "/api/auth/challenge",
                {"wallet": self.address},
                {"X-Forwarded-For": "1.2.3.4"},
            ).status,
            429,
        )

    def test_production_requires_shared_state(self):
        get_store.cache_clear()
        with patch.dict(os.environ, {"AXIOM_ENV": "production", "REDIS_URL": ""}):
            with self.assertRaises(RuntimeError):
                get_store()

    def test_invalid_wallet_is_not_accepted(self):
        self.assertEqual(decode_address(self.address), bytes(self.signer.verify_key))
        for value in (None, "0" * 44, "1" * 32, "abc"):
            with self.assertRaises(ApiError):
                decode_address(value)

    def test_error_response_does_not_leak_upstream_credentials(self):
        _, headers = self.sign_in()
        with (
            patch.dict(os.environ, {"SOLANA_RPC_URL": "https://rpc.example/SECRET"}),
            patch(
                "axiom_scanner.launch.urlopen", side_effect=OSError("secret failure")
            ),
        ):
            with self.assertLogs("axiom_scanner.webapp", level="ERROR"):
                response = self.request(
                    "/api/rpc", {"method": "getGenesisHash", "params": []}, headers
                )
            self.assertEqual(response.status, 503)
            self.assertNotIn(b"SECRET", response.body)
            self.assertNotIn(b"secret failure", response.body)

    @patch("axiom_scanner.web_runtime.ensure_local_workers")
    def test_authenticated_generation_runs_as_a_private_job(self, workers):
        _, headers = self.sign_in()
        with patch.dict(os.environ, {"WAVESPEED_API_KEY": "test-only-not-a-real-key"}):
            response = self.request(
                "/api/hybrid-image",
                {"prompt": "test"},
                {**headers, "Idempotency-Key": "job-request"},
            )
        self.assertEqual(response.status, 202, response.body)
        job_id = json.loads(response.body)["job_id"]
        with patch(
            "axiom_scanner.analysis.wavespeed_hybrid.generate_hybrid_image_request",
            return_value={"output_url": "https://example.com/image.png"},
        ):
            from axiom_scanner.web_runtime import execute_job

            execute_job(job_id)
        response = self.request("/api/jobs/" + job_id, headers=headers, method="GET")
        self.assertEqual(json.loads(response.body)["state"], "completed")
        self.signer = SigningKey.generate()
        self.address = base58(bytes(self.signer.verify_key))
        _, other_headers = self.sign_in()
        self.assertEqual(
            self.request(
                "/api/jobs/" + job_id, headers=other_headers, method="GET"
            ).status,
            404,
        )


class ImageAndMetadataTests(unittest.TestCase):
    def test_internal_and_mixed_dns_destinations_are_rejected(self):
        for addresses in (
            ["127.0.0.1"],
            ["169.254.169.254"],
            ["::1"],
            ["93.184.216.34", "10.0.0.1"],
        ):
            records = [(2, 1, 6, "", (address, 443)) for address in addresses]
            with (
                patch("socket.getaddrinfo", return_value=records),
                patch("axiom_scanner.safe_images.PinnedHTTPSConnection") as connection,
            ):
                with self.assertRaises(ApiError):
                    download_image("https://example.com/image.png")
                connection.assert_not_called()

    def test_non_https_and_credential_urls_are_rejected(self):
        for url in (
            "http://example.com/i.png",
            "file:///etc/passwd",
            "https://user:pass@example.com/i.png",
            "https://example.com:8080/i.png",
        ):
            with self.assertRaises(ApiError):
                download_image(url)

    def test_redirect_to_private_address_is_rejected(self):
        response = unittest.mock.Mock(status=302)
        response.getheader.return_value = "https://127.0.0.1/image.png"
        with (
            patch(
                "axiom_scanner.safe_images.public_addresses",
                side_effect=[["93.184.216.34"], ApiError("private")],
            ),
            patch("axiom_scanner.safe_images.PinnedHTTPSConnection") as connection,
        ):
            connection.return_value.getresponse.return_value = response
            with self.assertRaises(ApiError):
                download_image("https://public.example/image.png")
            self.assertEqual(connection.call_count, 1)

    def test_image_is_decoded_and_metadata_stripped(self):
        output = io.BytesIO()
        Image.new("RGB", (64, 64), "purple").save(
            output, "JPEG", exif=b"Exif\x00\x00private"
        )
        normalized = normalize_image(output.getvalue())
        with Image.open(io.BytesIO(normalized)) as image:
            self.assertEqual(image.format, "PNG")
            self.assertNotIn("exif", image.info)
        with self.assertRaises(ApiError):
            normalize_image(b"<svg onload='attack()'/>")

    def test_metadata_uses_utf8_byte_limits_and_safe_links(self):
        result = validate_metadata(
            {"name": "My token", "symbol": "test", "website": "https://example.com"}
        )
        self.assertEqual(result["symbol"], "TEST")
        for payload in (
            {"name": "🚀" * 9, "symbol": "TEST"},
            {"name": "Token", "symbol": "LONGSYMBOL123456"},
            {"name": "Token", "symbol": "TEST", "website": "javascript:alert(1)"},
            {"name": "Token", "symbol": "TEST", "telegram": "https://fake.example"},
        ):
            with self.assertRaises(ApiError):
                validate_metadata(payload)


class RuntimeConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"AXIOM_ENV": "development", "REDIS_URL": "", "AXIOM_CONFIG_PATH": ""},
        )
        self.env.start()
        get_store.cache_clear()

    def tearDown(self):
        get_store.cache_clear()
        self.env.stop()

    @patch("axiom_scanner.web_runtime.ensure_local_workers")
    def test_scans_with_different_limits_share_one_snapshot(self, workers):
        get_store().set(
            "scan:result",
            json.dumps(
                {"timestamp": time.time(), "tokens": [1, 2, 3], "updated_at": "same"}
            ),
        )
        self.assertEqual(scan_payload(1)[0]["tokens"], [1])
        self.assertEqual(scan_payload(3)[0]["tokens"], [1, 2, 3])

    def test_only_one_market_refresh_runs_at_once(self):
        started, release = threading.Event(), threading.Event()

        def scan(*args, **kwargs):
            started.set()
            release.wait(3)
            return []

        with patch("axiom_dashboard.scan_once", side_effect=scan) as scanner:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(refresh_scan)
                self.assertTrue(started.wait(1))
                second = pool.submit(refresh_scan)
                second.result(timeout=1)
                release.set()
                first.result(timeout=3)
            self.assertEqual(scanner.call_count, 1)

    @patch("axiom_scanner.web_runtime.ensure_local_workers")
    def test_duplicate_generation_is_queued_once_and_owned_by_wallet(self, workers):
        with ThreadPoolExecutor(max_workers=10) as pool:
            jobs = list(
                pool.map(
                    lambda _: enqueue_generation(
                        "hybrid", b"same", "application/json", "wallet-a", "request-1"
                    ),
                    range(20),
                )
            )
        self.assertEqual(len({job["job_id"] for job in jobs}), 1)
        self.assertIsNotNone(get_store().dequeue())
        self.assertIsNone(get_store().dequeue())
        with self.assertRaises(ApiError):
            public_job(jobs[0]["job_id"], "wallet-b")
        with self.assertRaises(ApiError):
            enqueue_generation(
                "hybrid", b"different", "application/json", "wallet-a", "request-1"
            )

    def test_queue_is_bounded(self):
        store = MemoryStore()
        self.assertTrue(store.enqueue("one", {"test": 1}, limit=1))
        self.assertFalse(store.enqueue("two", {"test": 2}, limit=1))


if __name__ == "__main__":
    unittest.main()
