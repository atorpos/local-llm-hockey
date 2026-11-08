"""Tiny local HTTP servers that imitate Ollama, SearXNG and websites, for offline tests."""
from __future__ import annotations

import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from tests.fixtures import LLM_ANSWERS, PAGES


def _serve(handler_cls) -> tuple[ThreadingHTTPServer, str]:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


class OllamaHandler(BaseHTTPRequestHandler):
    calls: list[dict] = []

    def log_message(self, *a):
        pass

    def _send(self, obj, code=200):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send({"models": [{"name": "qwen3:8b"}]})
        else:
            self._send({"error": "not found"}, 404)

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        OllamaHandler.calls.append(req)
        assert req["format"]["type"] == "object", "schema must be passed as format"
        assert req["options"]["num_ctx"] > 0
        user = req["messages"][1]["content"]
        url = re.search(r"^Page: (\S+)", user, re.M).group(1)
        ans = LLM_ANSWERS.get(url, {"page_is_about_player": False, "bio": {}, "contracts": [], "trades": []})
        self._send({"message": {"role": "assistant", "content": json.dumps(ans)}, "done": True,
                    "prompt_eval_count": len(user) // 4, "eval_count": 300})


class SearxHandler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        q = parse_qs(urlparse(self.path).query)
        query = q.get("q", [""])[0]
        assert q.get("format") == ["json"]
        results = []
        if "kadri" in query.lower():
            results = [{"url": u, "title": "Nazem Kadri " + u.split("/")[2], "content": "Kadri contract trade"}
                       for u in PAGES]
            results.append({"url": "https://www.hockey-reference.com/players/k/kadrina01.html",
                            "title": "Nazem Kadri Stats", "content": "Kadri"})       # must be blocked
            results.append({"url": "https://www.amazon.com/kadri-jersey", "title": "Kadri jersey", "content": ""})
        else:
            results = [{"url": "https://example.com/hockey", "title": "Hockey", "content": "generic result"}]
        body = json.dumps({"results": results}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)


class SiteHandler(BaseHTTPRequestHandler):
    """A website with robots.txt that disallows /private/."""
    hits: list[str] = []

    def log_message(self, *a):
        pass

    def do_GET(self):
        SiteHandler.hits.append(self.path)
        if self.path == "/robots.txt":
            body, ctype = b"User-agent: *\nDisallow: /private/\n", "text/plain"
        elif self.path.startswith("/slow-down"):
            self.send_response(429)
            self.end_headers()
            return
        elif self.path.startswith("/nocharset"):
            # no charset in the header and non-UTF-8 bytes: the case that crashed the first real run
            body, ctype = "<html><body><p>Montréal – Kadri café</p></body></html>".encode("cp1252"), "text/html"
        elif self.path.startswith("/file.pdf"):
            body, ctype = b"%PDF-1.4", "application/pdf"
        else:
            body, ctype = f"<html><body><p>page {self.path}</p></body></html>".encode(), "text/html; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def start_ollama():
    return _serve(OllamaHandler)


def start_searxng():
    return _serve(SearxHandler)


def start_site():
    return _serve(SiteHandler)


class OpenAIHandler(BaseHTTPRequestHandler):
    """Imitates LM Studio's OpenAI-compatible server. First answer is broken JSON to test the retry."""
    calls: list[dict] = []

    def log_message(self, *a):
        pass

    def _send(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._send({"data": [{"id": "qwen3-8b-mlx"}]})

    def do_POST(self):
        req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        OpenAIHandler.calls.append(req)
        assert req["response_format"]["type"] == "json_schema"
        content = '{"page_is_about_player": tru' if len(OpenAIHandler.calls) == 1 else \
            '```json\n{"page_is_about_player": false, "bio": {}, "contracts": [], "trades": []}\n```'
        self._send({"choices": [{"message": {"content": content}}],
                    "usage": {"prompt_tokens": 100, "completion_tokens": 20}})


def start_openai():
    return _serve(OpenAIHandler)
