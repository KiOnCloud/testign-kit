"""Backlog REST helper and the multi-page wiki commands against a local stub server. No real Backlog calls."""

import json
import os
import subprocess
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from testign import backlog_wiki

REPO = Path(__file__).resolve().parent.parent
KEY = "test-key-SHOULD-NOT-LEAK-123"
PREFIX = "QA/Decisions"

ORDER = """# Decisions — DEMO / order-confirm

## DEMO-12 · 注文確定

### D-DEMO-12-001 · Q1
- Date: 2026-11-14
- Question: 確認ダイアログを表示するか
- Decision: Có hiển thị.
- Quote:
  > 表示してください。
- Source: https://demo.backlog.com/view/DEMO-12#comment-1001
- Decided by: BrSE (Tanaka)
- Approved by: Asher
- Report: DEMO-12-survey-r1.md
- Status: active
"""

INDEX = """# Decisions index — DEMO

| ID | Page | Ticket | Q | Anchors | Date | Status |
|---|---|---|---|---|---|---|
| D-DEMO-12-001 | order-confirm | DEMO-12 | Q1 | 注文確定; 「確定」 | 2026-11-14 | active |
"""


class Stub:
    def __init__(self):
        self.pages = {
            77: {"id": 77, "name": f"{PREFIX}/order-confirm", "content": ORDER, "updated": "2026-11-14T00:00:00Z"},
            78: {"id": 78, "name": f"{PREFIX}/index", "content": INDEX, "updated": "2026-11-14T00:00:00Z"},
            90: {"id": 90, "name": "Other/page", "content": "x", "updated": "2026-11-01T00:00:00Z"},
        }
        self.requests = []
        self.next_id = 100
        self.comments = {"5": {"id": 5, "content": "ポイントは  使えます。\n詳細は後日お知らせします。"}}

    def writes(self):
        return [r for r in self.requests if r[0] in ("PATCH", "POST")]

    def handler(self):
        stub = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _send(self, code, payload):
                body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _start(self, method):
                parsed = urllib.parse.urlparse(self.path)
                query = urllib.parse.parse_qs(parsed.query)
                form = None
                if method in ("PATCH", "POST"):
                    length = int(self.headers.get("Content-Length", 0))
                    form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
                stub.requests.append((method, parsed.path, query, form))
                return parsed.path, query, form, query.get("apiKey") == [KEY]

            def do_GET(self):
                path, query, _, ok = self._start("GET")
                if not ok:
                    return self._send(401, {"errors": [{"message": "Authentication failure."}]})
                if path == "/api/v2/wikis":
                    kw = query.get("keyword", [""])[0]
                    return self._send(200, [{k: v for k, v in p.items() if k != "content"}
                                            for p in stub.pages.values() if kw in p["name"]])
                if path.startswith("/api/v2/wikis/"):
                    page = stub.pages.get(int(path.rsplit("/", 1)[1]))
                    return self._send(200, page) if page else self._send(404, {"errors": [{"message": "No wiki."}]})
                if path.startswith("/api/v2/issues/") and "/comments/" in path:
                    comment = stub.comments.get(path.rsplit("/", 1)[1])
                    return self._send(200, comment) if comment else self._send(404, {"errors": [{"message": "No comment."}]})
                if path == "/api/v2/projects/DEMO":
                    return self._send(200, {"id": 4242, "projectKey": "DEMO"})
                return self._send(404, {"errors": [{"message": "Not found."}]})

            def do_PATCH(self):
                path, _, form, ok = self._start("PATCH")
                if not ok:
                    return self._send(401, {"errors": [{"message": "Authentication failure."}]})
                page = stub.pages[int(path.rsplit("/", 1)[1])]
                page.update(content=form["content"][0], updated="2026-11-15T00:00:00Z")
                return self._send(200, page)

            def do_POST(self):
                _, _, form, ok = self._start("POST")
                if not ok:
                    return self._send(401, {"errors": [{"message": "Authentication failure."}]})
                assert form["projectId"] == ["4242"]
                stub.next_id += 1
                page = {"id": stub.next_id, "name": form["name"][0], "content": form["content"][0],
                        "updated": "2026-11-15T00:00:00Z"}
                stub.pages[page["id"]] = page
                return self._send(201, page)

        return Handler


@pytest.fixture
def server(monkeypatch):
    stub = Stub()
    httpd = HTTPServer(("127.0.0.1", 0), stub.handler())
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    monkeypatch.setenv("BACKLOG_DOMAIN", f"http://127.0.0.1:{httpd.server_port}")
    monkeypatch.setenv("BACKLOG_API_KEY", KEY)
    yield stub
    httpd.shutdown()


def by_name(stub, name):
    return next((p for p in stub.pages.values() if p["name"] == name), None)


def test_get_list_and_find(server):
    assert backlog_wiki.get(77)["content"] == ORDER
    listing = backlog_wiki.list_pages("DEMO", PREFIX)
    assert sorted(listing) == [f"{PREFIX}/index", f"{PREFIX}/order-confirm"]
    assert backlog_wiki.find("DEMO", f"{PREFIX}/index") == 78
    with pytest.raises(backlog_wiki.BacklogError, match="not found"):
        backlog_wiki.find("DEMO", "missing")


def test_update_sends_full_content_without_mail(server):
    new = ORDER + "\n## DEMO-15\n"
    saved = backlog_wiki.update(77, new, "2026-11-14T00:00:00Z", expected_content=ORDER)
    assert saved["updated"] == "2026-11-15T00:00:00Z"
    method, path, _, form = server.requests[-1]
    assert (method, path) == ("PATCH", "/api/v2/wikis/77")
    assert form["content"] == [new] and form["mailNotify"] == ["false"]


def test_update_refused_when_page_changed(server):
    server.pages[77]["updated"] = "2026-11-14T09:00:00Z"
    with pytest.raises(backlog_wiki.ConflictError):
        backlog_wiki.update(77, ORDER + "x", "2026-11-14T00:00:00Z")
    assert server.writes() == []


def test_create_uses_project_id_and_refuses_existing_name(server):
    saved = backlog_wiki.create("DEMO", f"{PREFIX}/point", "# Decisions — point\n")
    assert by_name(server, f"{PREFIX}/point")["content"] == "# Decisions — point\n"
    assert saved["name"] == f"{PREFIX}/point"
    with pytest.raises(backlog_wiki.ConflictError, match="created by someone else"):
        backlog_wiki.create("DEMO", f"{PREFIX}/point", "again")


def test_errors_never_contain_the_key(server, monkeypatch):
    monkeypatch.setenv("BACKLOG_API_KEY", KEY + "-wrong")
    with pytest.raises(backlog_wiki.BacklogError) as err:
        backlog_wiki.get(77)
    assert "401" in str(err.value) and KEY not in str(err.value)


def test_missing_env_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("BACKLOG_DOMAIN", raising=False)
    monkeypatch.delenv("BACKLOG_API_KEY", raising=False)
    with pytest.raises(backlog_wiki.BacklogError, match="BACKLOG_DOMAIN"):
        backlog_wiki.get(1)


def test_unexpected_errors_are_redacted(monkeypatch):
    monkeypatch.setenv("BACKLOG_DOMAIN", "https://demo.backlog.com")
    monkeypatch.setenv("BACKLOG_API_KEY", KEY)

    def boom(req, timeout):
        raise RuntimeError(f"failed for {req.full_url}")

    monkeypatch.setattr(backlog_wiki.urllib.request, "urlopen", boom)
    with pytest.raises(backlog_wiki.BacklogError) as err:
        backlog_wiki.get(77)
    assert KEY not in str(err.value) and "[redacted]" in str(err.value)


def test_plain_http_domain_is_refused(monkeypatch):
    monkeypatch.setenv("BACKLOG_DOMAIN", "http://demo.backlog.com")
    monkeypatch.setenv("BACKLOG_API_KEY", KEY)
    with pytest.raises(backlog_wiki.BacklogError, match="https"):
        backlog_wiki.get(77)


@pytest.mark.parametrize("bad_id", ["12 34", "12\n34", "../wikis", "77?x=1"])
def test_malformed_wiki_id_is_refused_before_any_request(server, bad_id):
    with pytest.raises(backlog_wiki.BacklogError, match="must be a number") as err:
        backlog_wiki.get(bad_id)
    assert KEY not in str(err.value)
    assert server.requests == []


# --- CLI: lookup, preview and update across feature pages, common and the index


def home_with_config(tmp_path, **backlog):
    home = tmp_path / "home"
    (home / ".testign-kit").mkdir(parents=True)
    cfg = {"backlog": {"project_key": "DEMO", "decisions_log_prefix": PREFIX, **backlog}}
    (home / ".testign-kit" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
    return home


def run_cli(*args, home, extra_env=None):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), **(extra_env or {}))
    return subprocess.run([sys.executable, str(REPO / "scripts" / "run.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def write_json(tmp_path, name, data):
    path = tmp_path / name
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


ROW_POINT = {
    "ticket": "DEMO-15", "ticket_title": "ポイント利用", "q": "Q1", "feature": "point", "anchors": ["ポイント利用", "注文確定"],
    "date": "2026-11-15", "question": "ポイントは割引後に使えますか？", "decision": "Có, sau giảm giá.",
    "quote": "割引後に利用できます。", "source": "https://demo.backlog.com/view/DEMO-15#comment-5",
    "decided_by": "Customer", "approved_by": "Asher", "report": "DEMO-15-survey-r1.md",
}
ROW_DUP = {**ROW_POINT, "ticket": "DEMO-12", "ticket_title": "注文確定", "feature": "order-confirm",
           "question": "確認ダイアログを表示するか", "decision": "Có hiển thị.", "quote": "表示してください。",
           "source": "https://demo.backlog.com/view/DEMO-12#comment-1001", "anchors": ["「確定」"]}


def test_cli_lookup_opens_matching_pages_and_common(server, tmp_path):
    home = home_with_config(tmp_path)
    anchors = write_json(tmp_path, "a.json", {"anchors": ["「確定」ボタン"]})
    res = run_cli("decisions-lookup", "--anchors-file", str(anchors), "--ticket", "DEMO-99", "--feature", "point",
                  home=home)
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert [m["id"] for m in out["matched"]] == ["D-DEMO-12-001"]
    assert [(p["page"], p["exists"]) for p in out["pages"]] == [("order-confirm", True), ("common", False), ("point", False)]
    entries = out["pages"][0]["parsed"]["tickets"]["DEMO-12"]["entries"]
    assert entries[0]["id"] == "D-DEMO-12-001"


def test_cli_preview_then_update_creates_page_and_appends_index(server, tmp_path):
    home = home_with_config(tmp_path)
    rows = write_json(tmp_path, "rows.json", [ROW_POINT, ROW_DUP])

    preview = run_cli("wiki-append-preview", "--rows", str(rows), home=home)
    assert preview.returncode == 0, preview.stderr
    shown = json.loads(preview.stdout)
    assert shown["added"] == ["D-DEMO-15-001"] and shown["skipped"][0]["id"] == "D-DEMO-12-001"
    assert [p["name"] for p in shown["pages"]] == [f"{PREFIX}/point", f"{PREFIX}/index"]
    assert shown["pages"][0]["exists"] is False
    assert KEY not in preview.stdout + preview.stderr
    assert server.writes() == []

    update = run_cli("wiki-update", "--rows", str(rows), "--approval", shown["approval"], home=home)
    assert update.returncode == 0, update.stderr
    assert [w["name"] for w in json.loads(update.stdout)["written"]] == [f"{PREFIX}/point", f"{PREFIX}/index"]
    assert [r[0] for r in server.writes()] == ["POST", "PATCH"]
    assert "### D-DEMO-15-001 · Q1" in by_name(server, f"{PREFIX}/point")["content"]
    index = by_name(server, f"{PREFIX}/index")["content"]
    assert index.startswith(INDEX)
    assert "| D-DEMO-15-001 | point | DEMO-15 | Q1 | ポイント利用; 注文確定 | 2026-11-15 | active |" in index
    assert by_name(server, f"{PREFIX}/order-confirm")["content"] == ORDER

    again = run_cli("wiki-update", "--rows", str(rows), "--approval", shown["approval"], home=home)
    assert again.returncode == 2 and "differ from the diff the tester approved" in again.stderr


def test_cli_update_refuses_when_rows_change_after_preview(server, tmp_path):
    home = home_with_config(tmp_path)
    rows = write_json(tmp_path, "rows.json", [ROW_POINT])
    shown = json.loads(run_cli("wiki-append-preview", "--rows", str(rows), home=home).stdout)
    write_json(tmp_path, "rows.json", [{**ROW_POINT, "decision": "Không."}])
    res = run_cli("wiki-update", "--rows", str(rows), "--approval", shown["approval"], home=home)
    assert res.returncode == 2 and "differ from the diff the tester approved" in res.stderr
    assert server.writes() == []


def test_cli_update_refuses_when_a_page_changed_after_preview(server, tmp_path):
    home = home_with_config(tmp_path)
    rows = write_json(tmp_path, "rows.json", [ROW_POINT])
    shown = json.loads(run_cli("wiki-append-preview", "--rows", str(rows), home=home).stdout)
    server.pages[78].update(content=INDEX + "| hand edit |\n", updated="2026-11-14T10:00:00Z")
    res = run_cli("wiki-update", "--rows", str(rows), "--approval", shown["approval"], home=home)
    assert res.returncode == 2
    assert server.writes() == []


def test_cli_rerun_after_partial_write_repairs_the_index(server, tmp_path):
    home = home_with_config(tmp_path)
    rows = write_json(tmp_path, "rows.json", [ROW_POINT])
    shown = json.loads(run_cli("wiki-append-preview", "--rows", str(rows), home=home).stdout)
    run_cli("wiki-update", "--rows", str(rows), "--approval", shown["approval"], home=home)
    server.pages[78].update(content=INDEX)  # simulate the index write having failed

    shown = json.loads(run_cli("wiki-append-preview", "--rows", str(rows), home=home).stdout)
    assert shown["added"] == [] and shown["index_repaired"] == ["D-DEMO-15-001"]
    assert [p["name"] for p in shown["pages"]] == [f"{PREFIX}/index"]


def test_cli_manual_mode_with_saved_pages(tmp_path):
    home = home_with_config(tmp_path)
    pages = tmp_path / "pages"
    pages.mkdir()
    (pages / "index.md").write_text(INDEX, encoding="utf-8")
    (pages / "order-confirm.md").write_text(ORDER, encoding="utf-8")
    rows = write_json(tmp_path, "rows.json", [ROW_POINT])
    res = run_cli("wiki-append-preview", "--rows", str(rows), "--pages-dir", str(pages), home=home,
                  extra_env={"BACKLOG_DOMAIN": "", "BACKLOG_API_KEY": ""})
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["mode"] == "manual"
    by_page = {p["page"]: p for p in out["pages"]}
    assert by_page["point"]["exists"] is False and "D-DEMO-15-001" in by_page["point"]["new_content"]
    assert by_page["index"]["new_content"].startswith(INDEX)

    lookup = run_cli("decisions-lookup", "--anchors-file", str(write_json(tmp_path, "a.json", {"anchors": ["注文確定"]})),
                     "--index-file", str(pages / "index.md"), home=home)
    assert json.loads(lookup.stdout)["page_names"] == [f"{PREFIX}/order-confirm", f"{PREFIX}/common"]


def test_cli_refuses_backlog_notation(tmp_path):
    home = home_with_config(tmp_path, text_format="backlog")
    page = tmp_path / "page.md"
    page.write_text(ORDER, encoding="utf-8")
    res = run_cli("decisions-parse", "--file", str(page), home=home)
    assert res.returncode == 2 and "Backlog notation" in res.stderr


def test_api_preview_carries_page_contents_the_console_can_verify(server, tmp_path):
    from testign.console import client, jobs

    home = home_with_config(tmp_path)
    rows = write_json(tmp_path, "rows.json", [ROW_POINT])
    shown = json.loads(run_cli("wiki-append-preview", "--rows", str(rows), home=home).stdout)
    assert all({"old_content", "new_content", "diff"} <= set(p) for p in shown["pages"])
    ask = jobs.validate_ask(client.ask_from_preview(shown))
    assert ask["type"] == "confirm-diff" and ask["preview"]["approval"] == shown["approval"]
    assert [p["diff"] for p in ask["preview"]["pages"]] == [p["diff"] for p in shown["pages"]]


def _comment_row(server_port: int, quote: str, comment: str = "5") -> dict:
    return {**ROW_POINT, "quote": quote, "source": f"http://127.0.0.1:{server_port}/view/DEMO-15#comment-{comment}"}


def test_cli_preview_checks_a_quote_against_its_backlog_comment(server, tmp_path, monkeypatch):
    home = home_with_config(tmp_path)
    port = int(os.environ["BACKLOG_DOMAIN"].rsplit(":", 1)[1])
    rows = write_json(tmp_path, "rows.json", [_comment_row(port, "ポイントは使えます。 詳細は後日お知らせします。"), ROW_DUP])
    res = run_cli("wiki-append-preview", "--rows", str(rows), home=home)
    assert res.returncode == 0, res.stderr
    quotes = json.loads(res.stdout)["quotes"]
    assert [q["status"] for q in quotes] == ["verified", "unchecked"]

    rows = write_json(tmp_path, "rows.json", [_comment_row(port, "ポイントは使えません。")])
    res = run_cli("wiki-append-preview", "--rows", str(rows), home=home)
    assert res.returncode == 2 and "not in the linked comment" in res.stderr
    res = run_cli("wiki-update", "--rows", str(rows), "--approval", "x", home=home)
    assert res.returncode == 2 and "not in the linked comment" in res.stderr
    assert server.writes() == []

    rows = write_json(tmp_path, "rows.json", [_comment_row(port, "ポイントは使えます。", comment="404")])
    res = run_cli("wiki-append-preview", "--rows", str(rows), home=home)
    assert res.returncode == 2 and "does not exist" in res.stderr
