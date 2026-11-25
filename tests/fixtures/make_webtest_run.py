"""A made-up 8-row web test run that covers every row kind, plus a fake console for the commands.

Nothing here is customer data: the hosts are reserved ``.test`` names and the texts are invented.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

HOSTS = ["dev.example.test"]
BASE_URL = "https://dev.example.test/"

STAGED = [
    {"row": "r01", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "row_node": "1:2",
                              "target_node": "I10:1;2:3", "no": "1"},
     "type": "Modified", "content": "予約確認 → 予約履歴 on the header link", "creator": "designer_a"},
    {"row": "r02", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "no": "2"},
     "type": "Added", "content": "A help link is added to the footer", "creator": "designer_a"},
    {"row": "r03", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "no": "3"},
     "type": "Modified", "content": "New logo in the header", "creator": "designer_b"},
    {"row": "r04", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "no": "4"},
     "type": "Modified", "content": "The news list opens in a new tab", "creator": "designer_b"},
    {"row": "r05", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "no": "5"},
     "type": "Modified", "content": "Cancel button shows only for reservations not yet confirmed",
     "creator": "designer_a"},
    {"row": "r06", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "no": "6"},
     "type": "Modified", "content": "Hero image fades in", "creator": "designer_b"},
    {"row": "r07", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "no": "7"},
     "type": "Added", "content": "Button variant: ghost", "creator": "designer_b"},
    {"row": "r08", "source": {"kind": "figma", "file": "FILEKEY", "table_node": "1:1", "no": "8"},
     "type": "Modified", "content": "Menu label 料金 → プラン", "creator": "designer_a"},
]

TRIAGE = {
    "r01": {"kind": "label", "class": "sure", "reason": "text change on a visible link", "runner": "agent",
            "scenario": "member", "screen": {"url": "/mypage", "name": "My Page", "confidence": "high"},
            "steps": "1. Open My Page", "expected": "The header link reads 予約履歴"},
    "r02": {"kind": "element", "class": "sure", "reason": "a link is added", "runner": "agent",
            "scenario": "none", "screen": {"url": "/", "name": "Top", "confidence": "low"},
            "steps": "1. Open the top page", "expected": "The footer has a help link"},
    "r03": {"kind": "visual", "class": "sure", "reason": "logo compared with the capture", "runner": "agent",
            "scenario": "member", "screen": {"url": "/mypage", "name": "My Page", "confidence": "high"},
            "steps": "1. Open My Page", "expected": "The header logo matches the capture"},
    "r04": {"kind": "behaviour", "class": "sure", "reason": "navigation, no data written", "runner": "agent",
            "scenario": "member", "screen": {"url": "/news", "name": "News", "confidence": "low"},
            "steps": "1. Open News\n2. Click the first item", "expected": "The item opens in a new tab"},
    "r05": {"kind": "data-rule", "class": "choice", "reason": "depends on a reservation's status",
            "scenario": "member", "screen": {"url": "/reservations", "name": "Reservations", "confidence": "low"},
            "steps": "1. Open a confirmed reservation", "expected": "No cancel button"},
    "r06": {"kind": "motion", "class": "not-web", "reason": "animation", "runner": "none"},
    "r07": {"kind": "design-only", "class": "not-web", "reason": "component variant without a page",
            "runner": "none"},
    "r08": {"kind": "label", "class": "sure", "reason": "label replaced", "runner": "tester", "viewport": "mobile",
            "scenario": "member", "screen": {"url": "/menu", "name": "Menu", "confidence": "low"},
            "steps": "1. Open the menu", "expected": "The menu reads プラン"},
}


class FakeConsole:
    """The server side the commands read, kept in memory."""

    def __init__(self) -> None:
        self.jobs: dict[str, dict] = {}
        self.reviews: dict[str, dict] = {}
        self.sign_ins: dict[str, dict] = {}
        self.answers: dict[str, dict] = {}
        self.results: dict[str, dict] = {}
        self.finish = False
        self.done_ids: set[str] = set()

    def add_job(self, job: str, kind: str, session: str = "s-test0001", **params) -> None:
        self.jobs[job] = {"id": job, "kind": kind, "state": "running", "session": session, "params": params,
                          "report_lang": "en", "ui_lang": "en", "run": params.get("run")}

    def end_job(self, job: str) -> None:
        self.jobs[job]["state"] = "done"

    # the reader interface -------------------------------------------------------------------
    def job(self, job, session):
        found = self.jobs.get(job)
        if found is None or found["session"] != session:
            raise ValueError("not this session's job")
        return dict(found)

    def attach_run(self, job, session, run):
        self.jobs[job]["run"] = run
        return {"ok": True}

    def review(self, job, session):
        return self.reviews.get(job)

    def job_open(self, job):
        return self.jobs.get(job, {}).get("state") in ("offered", "running", "needs-input")

    def signed_in(self, job, session):
        return self.sign_ins.get(job)

    def pending(self, run, job, session, wait):
        return {"answers": {k: v for k, v in self.answers.items() if k not in self.done_ids},
                "results": {k: v for k, v in self.results.items() if k not in self.done_ids},
                "finish": self.finish}

    def applied(self, run, job, session, ids):
        self.done_ids.update(ids)
        return {"ok": True}


def write_json(path: Path, data) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


COLUMNS = {"template": "sample", "columns": [{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "F"}],
           "verdict_labels": {"pass": "OK", "fail": "NG"}}


def eight_cases(rows_answer: dict | None = None) -> list[dict]:
    """The eight made-up rows as suite cases, with the tester's edits of ``rows_answer`` applied."""
    cases = []
    for staged in STAGED:
        source = {k: v for k, v in staged["source"].items() if k not in ("kind", "file")}
        case = {"source": source, "type": staged["type"], "content": staged["content"], "creator": staged["creator"],
                **TRIAGE[staged["row"]]}
        for key, value in ((rows_answer or {}).get(staged["row"]) or {}).items():
            if key == "screen":
                case["screen"] = value or None
            else:
                case[key] = value
        cases.append({k: v for k, v in case.items() if v is not None})
    return cases


def build(root: Path, server: FakeConsole | None = None, *, rows_answer: dict | None = None,
          when: datetime | None = None, tester: str = "Asher") -> str:
    """The eight-row run W20261119-1000-header-update, copied from a ready Figma suite."""
    from testign import webtest, webtest_suite  # noqa: PLC0415

    folder = ready_suite(root, kind="figma", cases=eight_cases(rows_answer))
    made = webtest.new_run_from_suite(
        root, webtest_suite.load(folder), folder, name=None, tester=tester, columns_for=lambda run: dict(COLUMNS),
        target={"base_url": BASE_URL, "project": "demo", "hosts": list(HOSTS), "template": "sample"},
        when=when or datetime(2026, 11, 19, 10, 0))
    return made["run"]


SUITE_CASES = [
    {"content": "予約確認 → 予約履歴 on the header link", "kind": "label", "class": "sure", "runner": "agent",
     "scenario": "member", "screen": "/mypage", "steps": "1. Open My Page", "expected": "The header link reads 予約履歴",
     "trace": ["B4", "R1"]},
    {"content": "A help link is added to the footer", "kind": "element", "class": "sure", "runner": "agent",
     "scenario": "none", "screen": "/", "steps": "1. Open the top page", "expected": "The footer has a help link",
     "trace": ["B2"]},
    {"content": "Cancel button only for unconfirmed reservations", "kind": "data-rule", "class": "choice",
     "runner": "tester", "scenario": "member", "screen": "/reservations", "trace": ["B5"]},
    {"content": "Totals are written by the nightly batch", "kind": "data-rule", "class": "not-web", "trace": ["R2"]},
]


def ready_suite(root: Path, *, kind: str = "manual", cases: list[dict] | None = None, name: str = "Header update",
                project: str = "demo", when: datetime | None = None) -> Path:
    """A confirmed suite with made-up cases, for runs made from suites. ``kind`` only labels its source."""
    from testign import webtest_suite  # noqa: PLC0415

    folder = webtest_suite.suites_root(root) / webtest_suite.new_suite_id(name, [], when or datetime(2026, 11, 25, 9, 0))
    folder.mkdir(parents=True)
    (folder / "source").mkdir()
    source = {"manual": {"kind": "manual"},
              "backlog": {"kind": "backlog", "ticket": "DEMO-1", "report": "DEMO-1-survey-r2.md", "revision": 2},
              "figma": {"kind": "figma", "url": "https://www.figma.com/design/FILEKEY/x?node-id=1-1", "file": "FILEKEY",
                        "node": "1:1"}}[kind]
    suite = {"version": webtest_suite.VERSION, "id": folder.name, "name": name, "project": project, "case_lang": "en",
             "created_at": "2026-11-25T09:00:00+09:00", "updated_at": "", "source": source, "state": "review",
             "generate_job": None, "confirmed_at": None, "confirmed_by": None, "suite_digest": None,
             "cases": [{"case": f"c{n}", **webtest_suite.check_case(c, case_id=f"c{n}")}
                       for n, c in enumerate(cases if cases is not None else SUITE_CASES, start=1)]}
    webtest_suite.save(folder, suite)
    webtest_suite.confirm(folder, "fp-tester")
    return folder
