from __future__ import annotations

import unittest


class VercelEntrypointTest(unittest.TestCase):
    def test_entrypoint_imports(self) -> None:
        from api.index import handler

        self.assertEqual(handler.__name__, "handler")

    def test_rewrite_route_keeps_api_query(self) -> None:
        from api.index import _route_from_request

        path, query = _route_from_request(
            "/api/index",
            "route=api/scan&limit=25",
        )

        self.assertEqual(path, "/api/scan")
        self.assertEqual(query, "limit=25")


if __name__ == "__main__":
    unittest.main()
