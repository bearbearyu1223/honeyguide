"""``honeyguide serve``: the local map page and its JSON API, for one checkout.

Laptop only: binds 127.0.0.1, refuses any Host but 127.0.0.1:<port> / localhost:<port> (DNS rebinding), and every
API call must carry the token embedded in the served page, so another site open in the browser can neither read
nor post. POSTs also need a JSON content type (a cross-site form can't send one without a preflight, which is never
answered) and, when the browser sends an Origin, this server's own.

The page never starts Claude: questions land in the inbox and the session's ``honeyguide watch`` wakes the Guide.
"""

from __future__ import annotations

import html
import json
import os
import re
import secrets
import sys
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import activity, inbox
from .contract import ContractError, load_side
from .gitio import GitError, Repo
from .preview import preview
from .store import Store, StoreError, all_claims

MAX_BODY = 1_000_000
TOKEN_HEADER = "X-Honeyguide-Token"
PAGE_DIR = Path(__file__).parent / "page"
# The map page's own files (T7.3), served by name only: nothing else on disk is reachable.
PAGE_FILES = {"/page.css": "text/css; charset=utf-8", "/page.js": "text/javascript; charset=utf-8",
              "/boot.js": "text/javascript; charset=utf-8", "/favicon.svg": "image/svg+xml"}
# Scripts, styles and fetches from this server only; no frames, no forms posting elsewhere.
PAGE_CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            "connect-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")

PLACEHOLDER = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>Honeyguide</title>
<meta name="honeyguide-token" content="__TOKEN__">
<style>body{font:16px/1.7 system-ui,sans-serif;margin:2rem auto;max-width:720px;color:#2b2621}
code{font:13px ui-monospace,monospace}</style></head>
<body><h1>Honeyguide</h1>
<p>Placeholder page (the map page arrives in T7.3). Memory for <code>__REPO__</code>.</p>
<pre id="state">loading...</pre>
<script>
const token = document.querySelector('meta[name="honeyguide-token"]').content;
fetch('/api/state', {headers: {'X-Honeyguide-Token': token}})
  .then(r => r.json()).then(s => { document.getElementById('state').textContent = JSON.stringify(s, null, 1); });
fetch('/api/visit', {method: 'POST', headers: {'X-Honeyguide-Token': token, 'Content-Type': 'application/json'},
  body: '{}'});
</script></body></html>
"""


def server_token(store: Store) -> str:
    """Kept in the memory dir (never in the checkout, never exported), so an open page survives a restart."""
    path = store.dir / "server-token"
    try:
        token = path.read_text().strip()
        if re.fullmatch(r"[0-9a-f]{32}", token):
            return token
    except OSError:
        pass
    token = secrets.token_hex(16)
    store.dir.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as out:
        out.write(token)
    return token


def state(repo: Repo, store: Store) -> dict:
    map_layer, answers = store.load("map"), store.load("answers")
    claims = [c for _, c in all_claims(map_layer, answers)]
    session = load_side(store, "session")
    since = session.get("previous_visit")
    threads = inbox.threads(store)["questions"]
    return {
        "repo_id": store.repo_id, "head": repo.rev("HEAD"), "map_commit": map_layer.get("commit"),
        "dirty": repo.dirty(),
        "claims": len(claims), "freshness": dict(Counter(c["freshness"] for c in claims)),
        "checks": dict(Counter(c["check"] for c in claims)),
        "questions": dict(Counter(q["status"] for q in threads)),
        "previous_visit": since, "last_visit": session.get("last_visit"),
        "rechecked_since_visit": sum(1 for c in claims if since and (c.get("checked_at") or "") > since),
        "refresh_log": session["refresh_log"][-20:],
    }


def page_html(token: str, repo_id: str) -> str:
    """The map page with this server's token and the repo id filled in (the placeholder if it isn't installed)."""
    try:
        page = (PAGE_DIR / "index.html").read_text(encoding="utf-8")
    except OSError:
        page = PLACEHOLDER
    return page.replace("__TOKEN__", token).replace("__REPO__", html.escape(repo_id, quote=True))


class Handler(BaseHTTPRequestHandler):
    server_version = "Honeyguide/1"
    repo: Repo
    store: Store
    token: str

    def log_message(self, *args) -> None:  # quiet; stdout belongs to results
        pass

    # -- checks --------------------------------------------------------------------------

    def _origin_self(self) -> str:
        return f"http://{self.headers.get('Host', '')}"

    def _host_ok(self) -> bool:
        port = self.server.server_address[1]
        return self.headers.get("Host", "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _api_ok(self, post: bool) -> str | None:
        """None if the request may proceed, else why not."""
        if not secrets.compare_digest(self.headers.get(TOKEN_HEADER, ""), self.token):
            return "missing or wrong token"
        origin = self.headers.get("Origin")
        if origin is not None and origin != self._origin_self():
            return "cross-origin request"
        site = self.headers.get("Sec-Fetch-Site")
        if site is not None and site not in ("same-origin", "none"):
            return "cross-site request"
        if post and not (self.headers.get("Content-Type") or "").startswith("application/json"):
            return "POST bodies must be application/json"
        return None

    # -- responses -----------------------------------------------------------------------

    def send(self, code: int, body: bytes, ctype: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if ctype.startswith("text/html") and (PAGE_DIR / "index.html").exists():
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

    def error(self, exc: Exception) -> None:
        if isinstance(exc, ContractError):
            status = {"not_found": 404, "invalid_transition": 409, "secret_refused": 403,
                      "lock_timeout": 503}.get(exc.code, 400)
            return self.json(status, exc.to_dict())
        code = "lock_timeout" if "lock" in str(exc) else "store_error"
        return self.json(503 if code == "lock_timeout" else 500,
                         ContractError(code, str(exc)).to_dict())

    # -- routes --------------------------------------------------------------------------

    def do_GET(self) -> None:
        if not self._host_ok():
            return self.send(403, b"forbidden host", "text/plain")
        url = urlparse(self.path)
        if url.path in ("/", "/index.html"):
            page = page_html(self.token, self.store.repo_id)
            return self.send(200, page.encode("utf-8"), "text/html; charset=utf-8")
        if url.path in PAGE_FILES:
            try:
                body = (PAGE_DIR / url.path.lstrip("/")).read_bytes()
            except OSError:
                return self.send(404, b"not found", "text/plain")
            return self.send(200, body, PAGE_FILES[url.path])
        if not url.path.startswith("/api/"):
            return self.send(404, b"not found", "text/plain")
        why = self._api_ok(post=False)
        if why:
            return self.json(403, ContractError("forbidden", why).to_dict())
        query = {k: v[-1] for k, v in parse_qs(url.query).items()}
        routes = {
            "/api/state": lambda: state(self.repo, self.store),
            "/api/map": lambda: self.store.load("map"),
            "/api/threads": lambda: inbox.threads(self.store),
            "/api/notes": lambda: self.store.load("notes"),
            "/api/activity": lambda: activity.listing(self.store),
            "/api/preview": lambda: preview(self.repo, self.store, query),
        }
        route = routes.get(url.path)
        if route is None:
            return self.json(404, ContractError("not_found", "no such endpoint").to_dict())
        try:
            return self.json(200, {"ok": True, **route()})
        except (ContractError, StoreError, GitError) as exc:
            return self.error(exc)

    def do_POST(self) -> None:
        if not self._host_ok():
            return self.send(403, b"forbidden host", "text/plain")
        why = self._api_ok(post=True)
        if why:
            return self.json(403, ContractError("forbidden", why).to_dict())
        routes = {
            "/api/question": lambda b: {"question": inbox.post_question(self.store, self._no_parent(b))},
            "/api/follow-up": lambda b: {"question": inbox.post_question(self.store, self._parent(b))},
            "/api/note": lambda b: {"note": inbox.post_note(self.store, b)},
            "/api/question/retry": lambda b: {"question": inbox.reopen(self.store, b)},
            "/api/visit": lambda b: activity.visit(self.store),
        }
        route = routes.get(urlparse(self.path).path)
        if route is None:
            return self.json(404, ContractError("not_found", "no such endpoint").to_dict())
        try:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise ContractError("bad_input", "request too large")
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError:
                raise ContractError("bad_input", "body is not JSON") from None
            if not isinstance(body, dict):
                raise ContractError("bad_input", "expected a JSON object")
            return self.json(200, {"ok": True, **route(body)})
        except (ContractError, StoreError, GitError) as exc:
            return self.error(exc)

    @staticmethod
    def _no_parent(body: dict) -> dict:
        if body.get("parent_response") is not None:
            raise ContractError("bad_input", "post follow-ups to /api/follow-up")
        return body

    @staticmethod
    def _parent(body: dict) -> dict:
        if not isinstance(body.get("parent_response"), str):
            raise ContractError("bad_input", "a follow-up needs parent_response")
        return body


def make_server(repo: Repo, store: Store, port: int = 8780) -> ThreadingHTTPServer:
    """A server bound to 127.0.0.1 (``port=0`` picks a free port)."""
    token = server_token(store)
    handler = type("BoundHandler", (Handler,), {"repo": repo, "store": store, "token": token})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    server.daemon_threads = True
    return server


def serve(repo: Repo, store: Store, port: int = 8780) -> int:
    server = make_server(repo, store, port)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(json.dumps({"ok": True, "url": url, "memory": str(Path(store.dir))}), flush=True)
    print(f"honeyguide: serving {url} (Ctrl-C to stop)", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
