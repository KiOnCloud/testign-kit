import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from console_helpers import InProcessServer, call  # noqa: E402
from make_report import write_report  # noqa: E402

from testign import cache, config, gitscope, templates, xlsx  # noqa: E402
from testign.console import lifecycle, readapi  # noqa: E402
from testign.console import server as srv  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
SHIPPED_SAMPLE = REPO / "templates" / "testcase-template-sample.xlsx"
CASES = [
    {"item": "Tổng tiền trừ giảm giá", "steps": "...", "expected": "...", "trace": ["B2"]},
    {"item": "Làm tròn", "steps": "...", "expected": "...", "trace": ["B3"], "waiting_on": ["Q1"]},
    {"item": "請求書", "steps": "...", "expected": "...", "trace": ["R1"]},
]


def make_state(home: Path) -> srv.ConsoleState:
    state = srv.ConsoleState(version="t", agent_token="agent", home=home)
    srv.install_base_routes(state)
    lifecycle.install_routes(state)
    return state


@pytest.fixture
def home(tmp_path):
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    return home


@pytest.fixture
def console(home):
    server = InProcessServer(make_state(home))
    server.headers = {srv.SESSION_HEADER: server.session()}
    yield server
    server.close()


def get(console, path):
    return call(console.port, "GET", path, headers=console.headers)


def out_dir(home):
    return home / "Downloads"


def seed_tickets(home, repo_path, head="d" * 40, base="b" * 40):
    out = out_dir(home)
    write_report(out / "DEMO-1", repo_path, head, base, revision=1)
    write_report(out / "DEMO-1", repo_path, head, base, revision=2)
    planted = write_report(out / "DEMO-1" / "tmp", repo_path, head, base, revision=9, ticket="DEMO-9")
    planted.rename(out / "DEMO-1" / "DEMO-1-survey-r9.md")
    (out / "DEMO-1" / "tmp").rmdir()
    write_report(out / "DEMO-2", repo_path, head, base, lang="ja", ticket="DEMO-2")
    write_report(out / "DEMO-3", repo_path, head, base, ticket="DEMO-3")
    (out / "DEMO-3" / "DEMO-3-survey-r2.md").write_bytes(b"\xff\xfe not a report")
    (out / "DEMO-4").mkdir()
    (out / "notes").mkdir()
    write_report(out / "notes", repo_path, head, base, ticket="notes")


def test_tickets_listing(console, home, tmp_path):
    seed_tickets(home, tmp_path)
    status, _, data = get(console, "/api/tickets")
    assert status == 200
    by_id = {t["id"]: t for t in data["tickets"]}
    assert sorted(by_id) == ["DEMO-1", "DEMO-2", "DEMO-3"]
    one = by_id["DEMO-1"]
    assert one["latest"] == "DEMO-1-survey-r2.md" and one["revision"] == 2
    assert one["inconsistent"] == ["DEMO-1-survey-r9.md"]
    assert one["conclusion"] == "open" and one["lang"] == "vi"
    assert one["questions"] == 1 and one["block_count"] == 0
    assert one["severity"] == {"blocking": 0, "major": 1, "minor": 0}
    assert one["blocks"]["partial"] == 1
    assert one["title"] == "[DEMO-1] Survey report — 注文確定"
    assert one["coverage"] is None
    assert by_id["DEMO-2"]["conclusion"] == "needs-qa" and by_id["DEMO-2"]["lang"] == "ja"
    assert by_id["DEMO-3"]["error"] == "unreadable" and by_id["DEMO-3"]["latest"] == "DEMO-3-survey-r2.md"


def test_ticket_detail_and_revisions(console, home, tmp_path):
    seed_tickets(home, tmp_path)
    status, _, data = get(console, "/api/tickets/DEMO-1")
    assert status == 200
    states = {r["name"]: r["state"] for r in data["revisions"]}
    assert states == {"DEMO-1-survey-r1.md": "ok", "DEMO-1-survey-r2.md": "ok", "DEMO-1-survey-r9.md": "inconsistent"}
    latest = data["latest"]
    assert latest["name"] == "DEMO-1-survey-r2.md"
    assert [s["number"] for s in latest["sections"]] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert latest["questions"][0]["id"] == "Q1"
    assert [b["id"] for b in latest["behaviors"]] == ["B1", "B2", "B3"]
    assert latest["behaviors"][2]["needs_case"] is True and latest["behaviors"][0]["needs_case"] is False
    assert [r["id"] for r in latest["regressions"]] == ["R1", "R2"]
    assert "Q1" in latest["findings"] and latest["findings"]["Q1"]["lines"]
    sec2 = next(s for s in latest["sections"] if s["number"] == 2)
    assert sec2["tables"][0]["header"][0] == "ID" and sec2["tables"][0]["rows"][0][0] == "Q1"
    assert not any("<!--" in line for s in latest["sections"] for line in s["lines"])

    status, _, rev = get(console, "/api/tickets/DEMO-1/revisions/DEMO-1-survey-r1.md")
    assert status == 200 and rev["frontmatter"]["revision"] == 1 and rev["state"] == "ok"
    status, _, rev = get(console, "/api/tickets/DEMO-1/revisions/DEMO-1-survey-r9.md")
    assert status == 200 and rev["state"] == "inconsistent"
    assert get(console, "/api/tickets/DEMO-3/revisions/DEMO-3-survey-r2.md")[0] == 422
    status, _, three = get(console, "/api/tickets/DEMO-3")
    assert status == 200 and three["error"] == "unreadable" and three["latest"] is None


@pytest.mark.parametrize("path", [
    "/api/tickets/..%2F..%2Fetc",
    "/api/tickets/%2E%2E",
    "/api/tickets/DEMO-1/revisions/..%2F..%2Fconfig.json",
    "/api/tickets/DEMO-1/revisions/%2Fetc%2Fpasswd",
    "/api/tickets/DEMO-1/revisions/C%3A%5CWindows%5Cwin.ini",
    "/api/tickets/DEMO-1/revisions/DEMO-1-survey-r7.md",
    "/api/tickets/DEMO-4",
    "/api/tickets/notes",
    "/api/tickets/DEMO-1/trace?workbook=..%2F..%2Fx.xlsx",
    "/api/templates/..%2Findex.json/preview",
])
def test_unknown_or_traversing_names_get_404(console, home, tmp_path, path):
    seed_tickets(home, tmp_path)
    assert get(console, path)[0] == 404


def test_hash_check(console, home, demo_repo, tmp_path):
    repo = str(demo_repo.path)
    head = gitscope.resolve_ref(repo, "develop")
    base = gitscope.merge_base(repo, "master", "develop")
    write_report(out_dir(home) / "DEMO-1", demo_repo.path, head, base)
    status, _, data = get(console, "/api/tickets/DEMO-1/hash")
    assert status == 200 and data["status"] == "same" and data["revision"] == "DEMO-1-survey-r1.md"
    assert "report" not in data

    plain = tmp_path / "plain"
    plain.mkdir()
    write_report(out_dir(home) / "DEMO-2", plain, head, base, ticket="DEMO-2")
    write_report(out_dir(home) / "DEMO-3", tmp_path / "missing", head, base, ticket="DEMO-3")
    assert get(console, "/api/tickets/DEMO-2/hash")[2] == {"revision": "DEMO-2-survey-r1.md", "status": "unknown",
                                                           "reason": "repo-not-found"}
    assert get(console, "/api/tickets/DEMO-3/hash")[2]["reason"] == "repo-not-found"


def test_usable_repo_accepts_worktrees_and_refuses_relative_paths(demo_repo, tmp_path):
    wt = tmp_path / "wt"
    demo_repo.git("worktree", "add", "-q", str(wt), "develop")
    assert readapi.usable_repo(str(wt)) == wt
    assert readapi.usable_repo("demo-legacy") is None
    assert readapi.usable_repo(None) is None


def _fill(home, entry, name="DEMO-1-tc.xlsx"):
    folder = out_dir(home) / "DEMO-1"
    xlsx.fill_copy(Path(entry["path"]), entry, CASES, folder / name)
    return name


def english_template(path: Path) -> Path:
    """Same sheet name and header row as the sample, other headers and columns."""
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "テストケース"
    for c, h in enumerate(["No", "Test item", "Steps", "Expected", "Remarks"], start=1):
        ws.cell(row=4, column=c, value=h)
    wb.save(path)
    return path


def test_trace_needs_a_template_and_reports_header_mismatch(console, home, tmp_path):
    write_report(out_dir(home) / "DEMO-1", tmp_path, "d" * 40, "b" * 40)
    (out_dir(home) / "DEMO-1" / "book.xlsx").write_bytes(SHIPPED_SAMPLE.read_bytes())
    status, _, data = get(console, "/api/tickets/DEMO-1/trace?workbook=book.xlsx")
    assert status == 200 and data == {"state": "no-template"}

    entry = templates.register(SHIPPED_SAMPLE, "mẫu", home=home)
    name = _fill(home, entry)
    status, _, data = get(console, f"/api/tickets/DEMO-1/trace?workbook={name}")
    assert status == 200 and data["state"] == "ok" and data["header_match"] is True
    assert data["template"] == "mẫu" and data["total_cases"] == 3
    assert data["gaps"] == ["R2"] and data["orphans"] == []
    assert data["cases"][1]["trace"] == ["B3"] and data["cases"][1]["questions"] == ["Q1"]
    assert all("status" not in c for c in data["cases"])

    templates.register(english_template(tmp_path / "en.xlsx"), "english", home=home)
    status, _, data = get(console, f"/api/tickets/DEMO-1/trace?workbook={name}&template=english")
    assert status == 200 and data["header_match"] is False
    assert data["template_headers"]["E"] == "Remarks" and data["workbook_headers"]["H"] == "備考"
    assert get(console, f"/api/tickets/DEMO-1/trace?workbook={name}&template=nope")[0] == 404


def test_trace_with_a_missing_sheet_is_a_template_error(console, home, tmp_path):
    write_report(out_dir(home) / "DEMO-1", tmp_path, "d" * 40, "b" * 40)
    wb = openpyxl.Workbook()
    wb.active.title = "Other"
    wb.save(out_dir(home) / "DEMO-1" / "other.xlsx")
    templates.register(SHIPPED_SAMPLE, "mẫu", home=home)
    status, _, data = get(console, "/api/tickets/DEMO-1/trace?workbook=other.xlsx")
    assert status == 400 and data["error"]["code"] == "template-error"
    with pytest.raises(templates.TemplateError):
        xlsx.read_trace(out_dir(home) / "DEMO-1" / "other.xlsx", templates.resolve("mẫu", home))


def test_coverage_after_trace_write_revision(console, home, tmp_path):
    from testign import report, trace

    rpt = write_report(out_dir(home) / "DEMO-1", tmp_path, "d" * 40, "b" * 40)
    entry = templates.register(SHIPPED_SAMPLE, "mẫu", home=home)
    name = _fill(home, entry)
    found = trace.trace_for(rpt, out_dir(home) / "DEMO-1" / name, entry)
    body = report.replace_section(found["body"], 7, trace.section7(found["summary"], name, found["sheet"]))
    report.write_revision(rpt, body)
    data = get(console, "/api/tickets")[2]["tickets"][0]
    assert data["coverage"]["total_cases"] == 3 and data["coverage"]["gaps"] == ["R2"]
    assert data["coverage"]["rows_with_case"] == 3 and data["coverage"]["rows_total"] == 5
    assert data["coverage"]["workbook"] == name
    assert data["workbooks"][0]["name"] == name


def test_config_projection(console, home):
    status, _, data = get(console, "/api/config")
    assert status == 200
    assert set(data) == {"output_dir", "lang", "report_langs", "master_ref", "develop_ref", "ticket_id_regex",
                         "console", "backlog"}
    assert set(data["console"]) == {"port", "idle_minutes"}
    assert data["report_langs"] == ["vi", "en", "ja"]  # reports keep Vietnamese; the console UI does not
    assert set(data["backlog"]) == {"space", "project_key", "decisions_log_prefix"}
    assert data["output_dir"] == str(home / "Downloads")


def test_cache_listing(console, home):
    folder = cache.entry_dir("r" * 40, "注文確定", home)
    folder.mkdir(parents=True)
    brief = "## 1. Brief\n| B1 | x | `src/a.cs@abcd1234` |\n"
    (folder / cache.BRIEF).write_bytes(brief.encode("utf-8"))
    manifest = {"feature": "注文確定", "root_commit": "r" * 40, "merge_base": "b" * 40, "anchors": ["確定"],
                "files": {"src/a.cs": "abcd1234"}, "rows": {"B1": ["src/a.cs"]}, "unread": [],
                "plugin_version": "0.2.0", "scout_model": "sonnet",
                "brief_sha256": hashlib.sha256(brief.encode()).hexdigest(),
                "reviewed_by": {"name": "Asher", "date": "2026-11-18"}, "created_at": "2026-11-18T10:00:00+07:00"}
    (folder / cache.MANIFEST).write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    broken = cache.entry_dir("r" * 40, "broken", home)
    broken.mkdir(parents=True)
    status, _, data = get(console, "/api/cache")
    assert status == 200
    entries = {e["feature"]: e for e in data["entries"]}
    good = entries["注文確定"]
    assert good["files"] == 1 and good["rows"] == ["B1"] and good["scout_model"] == "sonnet"
    assert good["reviewed_by"]["name"] == "Asher" and good["saved_at"].startswith("2026-11-18")
    assert "error" in entries["broken"]


def _tree_hash(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*")):
        rel = path.relative_to(root).as_posix()
        h.update(rel.encode())
        if path.is_file():
            h.update(path.read_bytes())
    return h.hexdigest()


def test_no_route_writes_reports_repo_or_config(home, demo_repo, tmp_path):
    repo = str(demo_repo.path)
    head = gitscope.resolve_ref(repo, "develop")
    base = gitscope.merge_base(repo, "master", "develop")
    seed_tickets(home, demo_repo.path, head, base)
    entry_home = tmp_path / "other-home"
    entry = templates.register(SHIPPED_SAMPLE, "mẫu", home=entry_home)
    _fill(home, entry)
    server = InProcessServer(make_state(home))
    headers = {srv.SESSION_HEADER: server.session()}
    before = (_tree_hash(out_dir(home)), _tree_hash(demo_repo.path))
    try:
        for path in ("/api/config", "/api/tickets", "/api/tickets/DEMO-1", "/api/tickets/DEMO-2",
                     "/api/tickets/DEMO-1/revisions/DEMO-1-survey-r1.md", "/api/tickets/DEMO-1/hash",
                     "/api/tickets/DEMO-1/trace?workbook=DEMO-1-tc.xlsx", "/api/cache", "/api/templates"):
            assert call(server.port, "GET", path, headers=headers)[0] == 200, path
        upload = call(server.port, "POST", "/api/templates/uploads", body=SHIPPED_SAMPLE.read_bytes(),
                      headers={**headers, "Content-Type": "application/octet-stream",
                               "X-Filename": "UTF-8''sample.xlsx"})
        assert upload[0] == 200
        assert call(server.port, "POST", "/api/templates", headers=headers,
                    body={"upload": upload[2]["upload"], "name": "x"})[0] == 200
        assert call(server.port, "GET", "/api/tickets/DEMO-1/trace?workbook=DEMO-1-tc.xlsx",
                    headers=headers)[0] == 200
        assert call(server.port, "POST", "/api/templates/x/default", headers=headers, body={})[0] == 200
        assert call(server.port, "DELETE", "/api/templates/x", headers=headers)[0] == 200
    finally:
        server.close()
    assert (_tree_hash(out_dir(home)), _tree_hash(demo_repo.path)) == before
    assert not config.config_path(home).exists()
    written = {p.relative_to(home / ".testign-kit").parts[0] for p in (home / ".testign-kit").rglob("*")}
    assert written <= {"console", "templates", "webtest"}
    # the web test store holds only its empty owner-only folders until a tester acts on a run
    assert not [p for p in (home / ".testign-kit" / "webtest").rglob("*") if p.is_file()]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows creation flag")
def test_git_runs_without_a_window_on_windows(monkeypatch):
    seen = {}
    real = subprocess.run

    def spy(cmd, **kwargs):
        seen["flags"] = kwargs.get("creationflags")
        return real(cmd, **kwargs)

    monkeypatch.setattr(gitscope.subprocess, "run", spy)
    with pytest.raises(gitscope.GitError):
        gitscope._git(os.getcwd() + "\\does-not-exist", "rev-parse", "--git-dir")
    assert seen["flags"] == subprocess.CREATE_NO_WINDOW


def test_corrupt_workbook_in_the_ticket_folder_is_a_400(console, home, tmp_path):
    write_report(out_dir(home) / "DEMO-1", tmp_path, "d" * 40, "b" * 40)
    templates.register(SHIPPED_SAMPLE, "mẫu", home=home)
    (out_dir(home) / "DEMO-1" / "broken.xlsx").write_bytes(b"PK\x03\x04 not really a zip")
    status, _, data = get(console, "/api/tickets/DEMO-1/trace?workbook=broken.xlsx")
    assert status == 400 and data["error"]["code"] in ("workbook-unreadable", "template-error")
