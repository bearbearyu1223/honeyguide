"""The click-through page for Han's human eval chores: ``uv run python eval/human/serve.py`` (port 8797).

Same guard as ``honeyguide serve`` (src/honeyguide/server.py): binds 127.0.0.1 only, refuses any Host but
127.0.0.1:<port> / localhost:<port>, every API call carries the token from the URL's fragment (``#t=...``; a fresh one per start, so a page
left open across a restart asks for the new URL),
POSTs need a JSON content type and, when the browser sends an Origin, this server's own. The page is files only
(no inline script or style) under a strict CSP; nothing is fetched from the network.

Every change is saved at once to eval/human/answers/ (see chores.py); ``eval/human/check.py`` prints the summary.
"""

from __future__ import annotations

import argparse
import json
import secrets
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import chores  # noqa: E402

PORT = 8797
MAX_BODY = 200_000
TOKEN_HEADER = "X-Honeyguide-Token"
PAGE_DIR = Path(__file__).resolve().parent / "page"
FAVICON = chores.ROOT / "src" / "honeyguide" / "page" / "favicon.svg"   # read only: the product's own mark
PAGE_FILES = {"/page.css": (PAGE_DIR / "page.css", "text/css; charset=utf-8"),
              "/page.js": (PAGE_DIR / "page.js", "text/javascript; charset=utf-8"),
              "/boot.js": (PAGE_DIR / "boot.js", "text/javascript; charset=utf-8"),
              "/favicon.svg": (FAVICON, "image/svg+xml")}
PAGE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


class Handler(BaseHTTPRequestHandler):
    server_version = "HoneyguideEvalHuman/1"
    answers: chores.Answers
    token: str

    def log_message(self, *args) -> None:
        pass

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _api_ok(self, post: bool) -> str | None:
        if not secrets.compare_digest(self.headers.get(TOKEN_HEADER, ""), self.token):
            return "missing or wrong token"
        origin = self.headers.get("Origin")
        if origin is not None and origin != f"http://{self.headers.get('Host', '')}":
            return "cross-origin request"
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return "cross-site request"
        if post and not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return "POST bodies must be application/json"
        return None

    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if ctype.startswith("text/html"):
            self.send_header("Content-Security-Policy", PAGE_CSP)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def json(self, code: int, data) -> None:
        self.send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def do_GET(self) -> None:
        if not self._host_ok():
            return self.send(403, b"forbidden host", "text/plain")
        path = urlparse(self.path).path
        if path in ("/", "/index.html"):
            # no token in the page: it reads it from the URL fragment the server printed (never sent, never logged)
            return self.send(200, (PAGE_DIR / "index.html").read_bytes(), "text/html; charset=utf-8")
        if path in PAGE_FILES:
            file, ctype = PAGE_FILES[path]
            return self.send(200, file.read_bytes(), ctype)
        if not path.startswith("/api/"):
            return self.send(404, b"not found", "text/plain")
        why = self._api_ok(post=False)
        if why:
            return self.json(403, {"ok": False, "error": why})
        if path == "/api/state":
            return self.json(200, {"ok": True, **self.answers.state()})
        if path == "/api/summary":
            s = chores.summarize(self.answers.dir, self.answers.questions_dir)
            return self.json(200, {"ok": True, "summary": s, "text": chores.summary_text(s)})
        return self.json(404, {"ok": False, "error": "no such endpoint"})

    def do_POST(self) -> None:
        if not self._host_ok():
            return self.send(403, b"forbidden host", "text/plain")
        why = self._api_ok(post=True)
        if why:
            return self.json(403, {"ok": False, "error": why})
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ValueError("request too large")
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError("expected a JSON object")
            a, path = self.answers, urlparse(self.path).path
            if path == "/api/hop":
                a.set_hop(body.get("repo"), body.get("qid"), body.get("index"), body.get("mark"))
                return self.json(200, {"ok": True})
            if path == "/api/dispute":
                a.set_dispute(body.get("repo"), body.get("qid"), body.get("index"), body.get("decision"),
                              body.get("note", ""))
                return self.json(200, {"ok": True})
            if path == "/api/whyhow":
                return self.json(200, {"ok": True, "questions": a.save_whyhow(body.get("repo"), body.get("questions"))})
            if path == "/api/whyhow/add":
                return self.json(200, {"ok": True, "question": a.add_whyhow(body.get("repo"))})
            return self.json(404, {"ok": False, "error": "no such endpoint"})
        except json.JSONDecodeError:
            return self.json(400, {"ok": False, "error": "body is not JSON"})
        except (ValueError, TypeError, KeyError) as exc:
            return self.json(400, {"ok": False, "error": str(exc)})


def make_server(answers: chores.Answers, port: int = PORT, token: str | None = None) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1 (``port=0`` picks a free port)."""
    handler = type("BoundHandler", (Handler,), {"answers": answers, "token": token or secrets.token_hex(16)})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=PORT)
    ap.add_argument("--answers", default=str(chores.ANSWERS), help="where answers are saved")
    args = ap.parse_args(argv)
    bad = chores.verify_manifest()
    if bad:
        print("frozen question sets differ from MANIFEST.txt: " + ", ".join(bad) +
              "\n(cd eval/questions && shasum -a 256 -c MANIFEST.txt); not serving", file=sys.stderr)
        return 2
    answers = chores.Answers(Path(args.answers))
    server = make_server(answers, args.port)
    url = f"http://127.0.0.1:{server.server_address[1]}/#t={server.RequestHandlerClass.token}"
    print(url, flush=True)
    print(f"eval/human: serving {url} (answers in {answers.dir}; Ctrl-C to stop)", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
