"""A made-up local site for the replay engine's browser tests: a sign-in form, a signed-in page,
a top page, a page that jumps to another host, and a data-changing form that counts its submits."""

from __future__ import annotations

import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

USER, PASSWORD = "tester01", "s3cret-Pass!"

PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>{title}</title></head><body>{body}</body></html>"""


class DemoSite:
    def __init__(self) -> None:
        self.label = "予約履歴"
        self.footer_link = True
        self.tokens: set[str] = set()
        self.submits = 0
        site = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):  # noqa: D401 - quiet
                pass

            def _send(self, status: int, body: str = "", headers: dict | None = None) -> None:
                data = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                for k, v in (headers or {}).items():
                    self.send_header(k, v)
                self.end_headers()
                self.wfile.write(data)

            def _signed_in(self) -> bool:
                cookie = self.headers.get("Cookie") or ""
                return any(part.strip() == f"sid={t}" for t in site.tokens for part in cookie.split(";"))

            def do_GET(self):  # noqa: N802
                path = self.path.split("?")[0]
                if path == "/login":
                    self._send(200, PAGE.format(title="Sign in", body=(
                        '<form method="post" action="/login"><label>User <input name="user"></label>'
                        '<label>Password <input name="password" type="password"></label>'
                        '<button type="submit">Sign in</button></form>')))
                elif path == "/mypage":
                    if not self._signed_in():
                        self._send(302, headers={"Location": "/login"})
                        return
                    self._send(200, PAGE.format(title="My Page", body=(
                        f'<header><a href="/history">{site.label}</a></header><h1>My Page</h1>'
                        '<form method="post" action="/subscribe"><button>Subscribe</button></form>'
                        '<p id="done"></p>')))
                elif path == "/":
                    footer = '<footer><a href="/help">Help</a></footer>' if site.footer_link else "<footer></footer>"
                    self._send(200, PAGE.format(title="Top", body=f"<h1>Top</h1>{footer}"))
                elif path == "/away":
                    self._send(200, PAGE.format(title="Away", body='<a href="http://other.invalid/">Partner</a>'))
                else:
                    self._send(404, PAGE.format(title="Not found", body="<h1>Not found</h1>"))

            def do_POST(self):  # noqa: N802
                length = int(self.headers.get("Content-Length") or 0)
                form = parse_qs(self.rfile.read(length).decode("utf-8"))
                if self.path == "/login":
                    if form.get("user") == [USER] and form.get("password") == [PASSWORD]:
                        token = secrets.token_hex(8)
                        site.tokens.add(token)
                        self._send(302, headers={"Location": "/mypage", "Set-Cookie": f"sid={token}; Path=/"})
                    else:
                        self._send(401, PAGE.format(title="Sign in", body="<p>Wrong user or password</p>"))
                elif self.path == "/subscribe":
                    site.submits += 1
                    self._send(200, PAGE.format(title="Done", body="<p>Subscribed</p>"))
                else:
                    self._send(404)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.port = self.httpd.server_address[1]
        self.base_url = f"http://localhost:{self.port}/"
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def sign_everyone_out(self) -> None:
        self.tokens.clear()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()
