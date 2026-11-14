"""Backlog REST helper against a local stub server. No real Backlog calls."""

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

PAGE = """# Decisions log — DEMO

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


class Stub:
    def __init__(self):
        self.page = {"id": 77, "name": "QA/Decisions log", "content": PAGE, "updated": "2026-11-14T00:00:00Z"}
        self.requests = []

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

            def _query(self):
                parsed = urllib.parse.urlparse(self.path)
                return parsed.path, urllib.parse.parse_qs(parsed.query)

            def do_GET(self):
                path, query = self._query()
                stub.requests.append(("GET", path, query, None))
                if query.get("apiKey") != [KEY]:
                    return self._send(401, {"errors": [{"message": "Authentication failure."}]})
                if path == "/api/v2/wikis/77":
                    return self._send(200, stub.page)
                if path == "/api/v2/wikis":
                    return self._send(200, [{"id": 5, "name": "Other"}, {"id": 77, "name": stub.page["name"]}])
                return self._send(404, {"errors": [{"message": "No wiki."}]})

            def do_PATCH(self):
                path, query = self._query()
                length = int(self.headers.get("Content-Length", 0))
                form = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
                stub.requests.append(("PATCH", path, query, form))
                if query.get("apiKey") != [KEY]:
                    return self._send(401, {"errors": [{"message": "Authentication failure."}]})
                stub.page = {**stub.page, "content": form["content"][0], "updated": "2026-11-15T00:00:00Z"}
                return self._send(200, stub.page)

        return Handler


@pytest.fixture
def server(monkeypatch):
    stub = Stub()
    httpd = HTTPServer(("127.0.0.1", 0), stub.handler())
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("BACKLOG_DOMAIN", f"http://127.0.0.1:{httpd.server_port}")
    monkeypatch.setenv("BACKLOG_API_KEY", KEY)
    yield stub
    httpd.shutdown()


def test_get_and_find(server):
    page = backlog_wiki.get(77)
    assert page["content"] == PAGE and page["updated"] == "2026-11-14T00:00:00Z"
    assert backlog_wiki.find("DEMO", "QA/Decisions log") == 77
    with pytest.raises(backlog_wiki.BacklogError, match="not found"):
        backlog_wiki.find("DEMO", "missing")


def test_update_sends_full_content_without_mail(server):
    new = PAGE + "\n## DEMO-15\n"
    saved = backlog_wiki.update(77, new, "2026-11-14T00:00:00Z", expected_content=PAGE)
    assert saved["updated"] == "2026-11-15T00:00:00Z"
    method, path, _, form = server.requests[-1]
    assert (method, path) == ("PATCH", "/api/v2/wikis/77")
    assert form["content"] == [new] and form["mailNotify"] == ["false"]


def test_update_refused_when_page_changed(server):
    server.page["updated"] = "2026-11-14T09:00:00Z"
    with pytest.raises(backlog_wiki.ConflictError):
        backlog_wiki.update(77, PAGE + "x", "2026-11-14T00:00:00Z")
    assert not [r for r in server.requests if r[0] == "PATCH"]


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


def run_cli(*args, home, extra_env):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), **extra_env)
    return subprocess.run([sys.executable, str(REPO / "scripts" / "run.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def rows_file(tmp_path, rows):
    path = tmp_path / "rows.json"
    path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    return path


ROWS = [
    {"ticket": "DEMO-12", "q": "Q2", "date": "2026-11-15", "question": "割引は？", "decision": "Có trừ.",
     "quote": "はい、適用してください。", "source": "https://demo.backlog.com/view/DEMO-12#comment-1010",
     "decided_by": "Customer", "approved_by": "Asher", "report": "DEMO-12-survey-r2.md"},
    {"ticket": "DEMO-12", "q": "Q1", "date": "2026-11-14", "question": "確認ダイアログを表示するか", "decision": "Có hiển thị.",
     "quote": "表示してください。", "source": "https://demo.backlog.com/view/DEMO-12#comment-1001",
     "decided_by": "BrSE (Tanaka)", "approved_by": "Asher", "report": "DEMO-12-survey-r1.md"},
]


def test_cli_preview_then_update_appends_only_new_rows(server, tmp_path):
    home = tmp_path / "home"
    env = {"BACKLOG_DOMAIN": os.environ["BACKLOG_DOMAIN"], "BACKLOG_API_KEY": KEY}
    rows = rows_file(tmp_path, ROWS)

    preview = run_cli("wiki-append-preview", "--rows", str(rows), "--wiki-id", "77", home=home, extra_env=env)
    assert preview.returncode == 0, preview.stderr
    shown = json.loads(preview.stdout)
    assert shown["added"] == ["D-DEMO-12-002"] and len(shown["skipped"]) == 1
    assert "+### D-DEMO-12-002 · Q2" in shown["diff"]
    assert KEY not in preview.stdout + preview.stderr
    assert not [r for r in server.requests if r[0] == "PATCH"]

    update = run_cli("wiki-update", "--rows", str(rows), "--wiki-id", "77", "--expected-updated", shown["updated"],
                     "--expected-hash", shown["new_sha256"], home=home, extra_env=env)
    assert update.returncode == 0, update.stderr
    assert json.loads(update.stdout)["written"] is True
    assert server.page["content"].startswith(PAGE)
    assert server.page["content"].count("### D-DEMO-12-") == 2

    again = run_cli("wiki-update", "--rows", str(rows), "--wiki-id", "77", "--expected-updated", shown["updated"],
                    "--expected-hash", shown["new_sha256"], home=home, extra_env=env)
    assert again.returncode == 2 and "changed since the diff was shown" in again.stderr


def test_cli_manual_mode_without_api(tmp_path):
    page = tmp_path / "page.md"
    page.write_text(PAGE, encoding="utf-8")
    res = run_cli("wiki-append-preview", "--rows", str(rows_file(tmp_path, ROWS[:1])), "--page-file", str(page),
                  home=tmp_path / "home", extra_env={"BACKLOG_DOMAIN": "", "BACKLOG_API_KEY": ""})
    assert res.returncode == 0, res.stderr
    out = json.loads(res.stdout)
    assert out["mode"] == "manual" and out["new_content"].startswith(PAGE)


def test_cli_refuses_backlog_notation(tmp_path):
    home = tmp_path / "home"
    (home / ".testign-kit").mkdir(parents=True)
    (home / ".testign-kit" / "config.json").write_text(json.dumps({"backlog": {"text_format": "backlog"}}), encoding="utf-8")
    page = tmp_path / "page.md"
    page.write_text(PAGE, encoding="utf-8")
    res = run_cli("decisions-parse", "--file", str(page), home=home, extra_env={})
    assert res.returncode == 2 and "Backlog notation" in res.stderr


def test_cli_update_refuses_content_other_than_the_approved_diff(server, tmp_path):
    home = tmp_path / "home"
    env = {"BACKLOG_DOMAIN": os.environ["BACKLOG_DOMAIN"], "BACKLOG_API_KEY": KEY}
    rows = rows_file(tmp_path, ROWS[:1])
    shown = json.loads(run_cli("wiki-append-preview", "--rows", str(rows), "--wiki-id", "77",
                               home=home, extra_env=env).stdout)
    changed = dict(ROWS[0], decision="Không trừ.")
    rows.write_text(json.dumps([changed], ensure_ascii=False), encoding="utf-8")
    res = run_cli("wiki-update", "--rows", str(rows), "--wiki-id", "77", "--expected-updated", shown["updated"],
                  "--expected-hash", shown["new_sha256"], home=home, extra_env=env)
    assert res.returncode == 2 and "differs from the diff the tester approved" in res.stderr
    assert not [r for r in server.requests if r[0] == "PATCH"]


@pytest.mark.parametrize("bad_id", ["12 34", "12\n34", "../wikis", "77?x=1"])
def test_malformed_wiki_id_is_refused_without_leaking_the_key(server, tmp_path, bad_id):
    env = {"BACKLOG_DOMAIN": os.environ["BACKLOG_DOMAIN"], "BACKLOG_API_KEY": KEY}
    res = run_cli("wiki-get", "--wiki-id", bad_id, home=tmp_path / "home", extra_env=env)
    assert res.returncode == 2
    assert "must be a number" in res.stderr
    assert KEY not in res.stdout + res.stderr and "Traceback" not in res.stderr
    assert server.requests == []


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
