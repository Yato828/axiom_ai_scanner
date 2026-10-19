from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlsplit

from axiom_scanner.webapp import DashboardHandler


class handler(DashboardHandler):
    def _dispatch(self):
        parsed = urlsplit(self.path)
        path, query = _route_from_request(parsed.path, parsed.query)
        self.path = path + ("?" + query if query else "")
        super()._dispatch()

    do_GET = do_POST = do_HEAD = do_OPTIONS = _dispatch


def _route_from_request(path: str, query: str) -> tuple[str, str]:
    pairs = parse_qsl(query, keep_blank_values=True)
    route = ""
    filtered_pairs = []
    for key, value in pairs:
        if key == "route" and not route:
            route = value
        else:
            filtered_pairs.append((key, value))
    route_path = "/" + route.lstrip("/") if path == "/api/index" and route else path
    return route_path, urlencode(filtered_pairs)
