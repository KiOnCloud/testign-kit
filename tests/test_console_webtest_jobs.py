import re
import time

import pytest

from testign import webtest
from testign.console import jobs
from testign.console.server import ApiError

A = "s-aaaaaaaaaaaaaaaa"
FIGMA = "https://www.figma.com/design/AbCdEfGhIjKl/Shop?node-id=6647-118148&t=x"
RUN = "W20261119-1000-header-update"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class World:
    """Fake context: one project, its scenarios and one run, all in memory."""

    def __init__(self):
        self.projects = {"demo": {"hosts": ["dev.example.test"], "signin_hosts": []}}
        self.scenarios = {"member": {"name": "member", "label": "Member", "approved": True, "steps": ["Sign in"],
                                     "login_url": "https://dev.example.test/login", "account_hint": "a member",
                                     "signout_url": "https://dev.example.test/logout", "hash": "h1"},
                          "admin": {"name": "admin", "label": "Admin", "approved": False}}
        self.runs = {RUN: {"id": RUN, "project": "demo", "confirmed": True, "ticket": None, "report_lang": "ja",
                           "open": 2}}
        self.finish = set()
        self.facts = {"sample": {"headers": {"A": "No", "B": "確認内容", "F": "結果"}, "last": 8,
                                 "merged": [("J4:L4", 10, 12)]}}

    def context(self):
        return jobs.Context(
            cfg=lambda: {"ticket_id_regex": r"\b[A-Z][A-Z0-9_]+-\d+\b", "lang": "vi"},
            ticket_rx=lambda cfg: re.compile(r"[A-Z][A-Z0-9_]+-\d+"),
            latest=lambda t: None,
            templates=lambda: {"default": "sample", "templates": [{"name": "sample", "purpose": "webtest"}]},
            workbooks=lambda t: [], row_ids=lambda t: set(), usable_repo=lambda r: None,
            projects=lambda: self.projects,
            run_info=lambda run: self.runs.get(run),
            scenario=lambda project, name: self.scenarios.get(name),
            scenarios=lambda project: list(self.scenarios.values()),
            run_finish=lambda run: run in self.finish,
            template_facts=lambda name: self.facts.get(name),
        )


@pytest.fixture
def world():
    return World()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def bridge(world, clock):
    b = jobs.Bridge(jobs.MemoryStore(), world.context(), clock=clock)
    b.startup()
    return b


def plan_body(**extra):
    return {"kind": "webtest-plan", "ui_lang": "en", "name": "Header update", "figma_url": FIGMA,
            "base_url": "https://dev.example.test/", "project": "demo", **extra}


def start(bridge, body, session=A, *, created_before=1.0):
    job = bridge.create(body)
    bridge.jobs[job["id"]]["created_ts"] = time.time() + created_before  # tabs made "now" are older
    assert bridge.wait(session, 0)["job"]["id"] == job["id"]
    bridge.claim(job["id"], session)
    return job["id"]


def review_ask(run=RUN, **extra):
    return {"type": "review-table", "id": f"review-{run}", "run": run, "template": "sample",
            "headers": {"A": "No", "B": "確認内容", "F": "結果"}, "last_column": "H",
            "columns": [{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "F"}],
            "verdict_labels": {"pass": "OK", "fail": "NG"},
            "lines": [{"row": "r01", "content": "label", "class": "sure", "runner": "agent", "scenario": "member",
                       "viewport": "pc", "screen": "/mypage", "confidence": "high"},
                      {"row": "r05", "content": "rule", "class": "choice", "runner": "tester", "scenario": "member",
                       "viewport": "pc", "screen": "/reservations", "confidence": "low"}],
            "digest": "d1", **extra}


ANSWER = {"columns": [{"field": "content", "letter": "B"}, {"field": "verdict", "letter": "F"}],
          "verdict_labels": {"pass": "OK", "fail": "NG"}, "rows": {}, "confirm": True}


def plan_with_run(bridge):
    job = start(bridge, plan_body())
    bridge.attach_run(job, A, RUN)
    return job


def ask_and_answer(bridge, job, ask, answer, session_created=None):
    assert bridge.ask(job, A, ask, 0) == {"answers": None}
    return bridge.answer(job, {"ask_id": ask["id"], "answer": answer}, "browser-s", session_created)


# kinds ---------------------------------------------------------------------------------------------
def test_plan_kind_checks_and_stores_server_facts(bridge):
    job = bridge.create(plan_body(ticket="DEMO-1"))
    record = bridge.jobs[job["id"]]
    assert record["params"]["source"] == {"kind": "figma", "url": FIGMA, "file": "AbCdEfGhIjKl", "node": "6647:118148"}
    assert record["params"]["hosts"] == ["dev.example.test"] and record["params"]["template"] == "sample"
    assert record["queued_by"] == "tester" and record["opened"] is True and record["report_lang"] == "vi"
    assert job["run"] is None and job["queued_by"] == "tester"


@pytest.mark.parametrize("change,code", [
    ({"project": "other"}, "unknown-project"),
    ({"base_url": "https://evil.example/"}, "off-host"),
    ({"base_url": "ftp://dev.example.test/"}, "bad-base-url"),
    ({"figma_url": "https://www.figma.com/design/AbCdEfGhIjKl/Shop"}, "bad-source"),
    ({"figma_url": "https://figma.example/design/AbCdEfGhIjKl/Shop?node-id=1-2"}, "bad-source"),
    ({"template": "nope"}, "unknown-template"),
    ({"name": ""}, "bad-request"),
    ({"ticket": "not a ticket"}, "bad-request"),
])
def test_plan_kind_refusals(bridge, change, code):
    with pytest.raises(ApiError) as exc:
        bridge.create(plan_body(**change))
    assert exc.value.code == code


def test_run_kind_needs_a_confirmed_run_and_a_tester(bridge, world):
    with pytest.raises(ApiError, match="no such run"):
        bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": "W20261119-1000-nope", "tester": "T"})
    with pytest.raises(ApiError, match="no such run"):
        bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": "../x", "tester": "T"})
    with pytest.raises(ApiError) as exc:
        bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": RUN})
    assert exc.value.code == "tester-required"
    world.runs[RUN]["confirmed"] = False
    with pytest.raises(ApiError) as exc:
        bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": RUN, "tester": "T"})
    assert exc.value.code == "plan-not-confirmed"
    world.runs[RUN]["confirmed"] = True
    job = bridge.create({"kind": "webtest-run", "ui_lang": "en", "run": RUN, "tester": "T", "mode": "export"})
    assert job["run"] == RUN and bridge.jobs[job["id"]]["params"]["mode"] == "export"
    assert bridge.jobs[job["id"]]["report_lang"] == "ja"


def test_agent_queue_takes_web_kinds_only_and_marks_them(bridge):
    for kind in ("survey", "close", "testcase", None):
        with pytest.raises(ApiError):
            bridge.agent_create({"kind": kind, "ui_lang": "en", "ticket": "DEMO-1", "tester": "T"})
    job = bridge.agent_create(plan_body())
    assert job["queued_by"] == "agent" and job["opened"] is False
    assert bridge.get(job["id"])["opened"] is False
    assert bridge.get(job["id"], opened=True)["opened"] is True
    assert bridge.summary(bridge.jobs[job["id"]])["opened"] is True


def test_attach_run_once_and_info(bridge):
    job = start(bridge, plan_body())
    assert bridge.info(job, A)["run"] is None
    with pytest.raises(ApiError):
        bridge.attach_run(job, A, "../etc")
    bridge.attach_run(job, A, RUN)
    assert bridge.info(job, A)["run"] == RUN
    with pytest.raises(ApiError, match="already"):
        bridge.attach_run(job, A, RUN)
    with pytest.raises(ApiError):
        bridge.info(job, "s-otherotherother")


# review table ----------------------------------------------------------------------------------------
def test_review_table_carries_server_hosts_and_scenarios(bridge):
    job = plan_with_run(bridge)
    bridge.ask(job, A, {**review_ask(), "hosts": ["evil.example"]}, 0)
    ask = bridge.jobs[job]["ask"]
    assert ask["hosts"] == ["dev.example.test"]
    assert {s["name"]: s["approved"] for s in ask["scenarios"]} == {"member": True, "admin": False}


def test_review_table_checks_columns_against_the_template_not_the_ask(bridge):
    job = plan_with_run(bridge)
    sent = {**review_ask(), "headers": {"A": "No", "B": "確認内容", "C": "x", "F": "結果"}, "last_column": "C"}
    bridge.ask(job, A, sent, 0)
    ask = bridge.jobs[job]["ask"]
    assert ask["headers"] == {"A": "No", "B": "確認内容", "F": "結果"} and ask["last_column"] == "H"
    for col, message in (({"field": "screen", "letter": "C"}, "no header"),
                         ({"field": "screen", "letter": "K", "header": "画面", "new": True}, "merged")):
        with pytest.raises(ApiError, match=message):
            bridge.answer(job, {"ask_id": ask["id"], "answer": {**ANSWER, "columns": [*ANSWER["columns"], col]}},
                          "browser-s")
    ok = {"field": "screen", "letter": "M", "header": "画面", "new": True}
    assert bridge.answer(job, {"ask_id": ask["id"], "answer": {**ANSWER, "columns": [*ANSWER["columns"], ok]}},
                         "browser-s")["state"] == "running"


@pytest.mark.parametrize("line,message", [
    ({"class": "choice", "runner": "agent", "preconditions": "x"}, "only the tester delegates"),
    ({"viewport": "mobile"}, "phone-width"),
])
def test_review_table_refuses_lines_only_the_tester_may_set(bridge, line, message):
    job = plan_with_run(bridge)
    ask = review_ask()
    ask["lines"] = [{**ask["lines"][0], **line}, ask["lines"][1]]
    with pytest.raises(ApiError, match=message):
        bridge.ask(job, A, ask, 0)


def test_review_answer_refuses_a_phone_row_for_the_agent(bridge):
    job = plan_with_run(bridge)
    bridge.ask(job, A, review_ask(), 0)
    with pytest.raises(ApiError, match="phone-width"):
        bridge.answer(job, {"ask_id": review_ask()["id"], "answer": {**ANSWER, "rows": {"r01": {"viewport": "mobile"}}}},
                      "browser-s")
    with pytest.raises(ApiError, match="scenario must be"):
        bridge.answer(job, {"ask_id": review_ask()["id"], "answer": {**ANSWER, "rows": {"r01": {"scenario": ["x"]}}}},
                      "browser-s")


def test_review_table_needs_the_runs_template(bridge, world):
    job = plan_with_run(bridge)
    with pytest.raises(ApiError, match="run's template"):
        bridge.ask(job, A, {**review_ask(), "template": "other"}, 0)
    world.facts.clear()
    with pytest.raises(ApiError, match="cannot be read"):
        bridge.ask(job, A, review_ask(), 0)


def test_review_table_belongs_to_the_plan_job_of_its_run(bridge):
    job = start(bridge, plan_body())
    with pytest.raises(ApiError, match="belongs"):
        bridge.ask(job, A, review_ask(), 0)  # no run attached yet
    bridge.attach_run(job, A, RUN)
    with pytest.raises(ApiError, match="belongs"):
        bridge.ask(job, A, review_ask(run="W20261119-1000-other"), 0)


def test_confirmed_review_keeps_the_decision_and_a_digest_of_what_was_shown(bridge):
    job = plan_with_run(bridge)
    assert bridge.review(job, A) == {"review": None}
    ask_and_answer(bridge, job, review_ask(), {**ANSWER, "rows": {"r05": {"runner": "agent",
                                                                          "preconditions": "a confirmed booking"}}})
    review = bridge.review(job, A)["review"]
    assert review["digest"] == webtest.cases_digest({"cases": review_ask()["lines"]})  # not the agent's "d1"
    assert review["template"] == "sample" and review["lines"][0]["row"] == "r01"
    assert set(review["lines"][0]) == set(webtest.PLAN_LINE_KEYS)  # no case text in the job record
    assert review["answer"]["rows"] == {"r05": {"runner": "agent", "preconditions": "a confirmed booking"}}
    assert review["answered_by"] == jobs.fingerprint("browser-s")
    assert bridge.ask(job, A, review_ask(), 0)["answers"]["confirm"] is True  # same id hands the answer out again


def test_not_confirmed_fails_the_plan_job(bridge):
    job = plan_with_run(bridge)
    ask_and_answer(bridge, job, review_ask(), {"confirm": False})
    record = bridge.jobs[job]
    assert record["state"] == "failed" and record["reason"] == "not-confirmed"
    assert record["asked"][-1]["answer"] == {"confirm": False}


@pytest.mark.parametrize("rows,code", [
    ({"r05": {"runner": "agent"}}, "preconditions-required"),
    ({"r01": {"screen": "https://evil.example/x"}}, "off-host"),
    ({"r01": {"screen": "//evil.example/x"}}, "off-host"),
    ({"r01": {"scenario": "ghost"}}, "unknown-scenario"),
    ({"r99": {"runner": "agent"}}, "unknown-row"),
    ({"r01": {"content": "rewritten"}}, "bad-request"),
])
def test_review_answer_rules(bridge, rows, code):
    job = plan_with_run(bridge)
    bridge.ask(job, A, review_ask(), 0)
    with pytest.raises(ApiError) as exc:
        bridge.answer(job, {"ask_id": f"review-{RUN}", "answer": {**ANSWER, "rows": rows}}, "browser-s")
    assert exc.value.code == code
    assert bridge.jobs[job]["state"] == "needs-input"


def test_a_tab_newer_than_the_web_job_cannot_answer(bridge):
    job = plan_with_run(bridge)
    bridge.ask(job, A, review_ask(), 0)
    created = bridge.jobs[job]["created_ts"]
    with pytest.raises(ApiError) as exc:
        bridge.answer(job, {"ask_id": f"review-{RUN}", "answer": ANSWER}, "browser-s", created + 1)
    assert exc.value.code == "session-too-new"
    bridge.answer(job, {"ask_id": f"review-{RUN}", "answer": ANSWER}, "browser-s", created - 1)


# sign-in -------------------------------------------------------------------------------------------------
def run_job(bridge):
    return start(bridge, {"kind": "webtest-run", "ui_lang": "en", "run": RUN, "tester": "T"})


def test_sign_in_needs_an_approved_scenario_and_carries_its_checklist(bridge):
    job = run_job(bridge)
    with pytest.raises(ApiError) as exc:
        bridge.ask(job, A, {"type": "sign-in", "id": "signin-admin", "scenario": "admin"}, 0)
    assert exc.value.code == "scenario-not-approved"
    with pytest.raises(ApiError):
        bridge.ask(job, A, {"type": "sign-in", "id": "signin-none", "scenario": "none"}, 0)
    bridge.ask(job, A, {"type": "sign-in", "id": "signin-member", "scenario": "member", "switching_from": "admin"}, 0)
    ask = bridge.jobs[job]["ask"]
    assert ask["checklist"]["login_url"] == "https://dev.example.test/login" and ask["checklist"]["hash"] == "h1"
    assert ask["previous"]["name"] == "admin"


def test_sign_in_answer_is_read_back(bridge):
    job = run_job(bridge)
    assert bridge.signed_in_view(job, A) == {"signed_in": None}
    with pytest.raises(ApiError):
        ask_and_answer(bridge, job, {"type": "sign-in", "id": "s1", "scenario": "member"}, {"choice": "finish"})
    bridge.answer(job, {"ask_id": "s1", "answer": {"choice": "signed-in"}}, "browser-s")
    assert bridge.signed_in_view(job, A)["signed_in"]["choice"] == "signed-in"


def test_finish_ends_an_open_sign_in_question(bridge):
    job = run_job(bridge)
    bridge.ask(job, A, {"type": "sign-in", "id": "s1", "scenario": "member"}, 0)
    assert bridge.finish_sign_in("W20261119-1000-other", "browser-s") is False
    assert bridge.finish_sign_in(RUN, "browser-s") is True
    assert bridge.jobs[job]["state"] == "running"
    assert bridge.ask(job, A, {"type": "sign-in", "id": "s1", "scenario": "member"}, 0) == {
        "answers": {"choice": "finish"}}
    assert bridge.signed_in_view(job, A)["signed_in"]["choice"] == "finish"


# done, silence ---------------------------------------------------------------------------------------------
def test_done_is_refused_with_open_rows_until_the_tester_finishes(bridge, world):
    job = run_job(bridge)
    with pytest.raises(ApiError) as exc:
        bridge.done(job, A, "done", "x")
    assert exc.value.code == "open-rows"
    world.finish.add(RUN)
    assert bridge.done(job, A, "done", "x") == {"ok": True}


def test_done_with_no_open_rows_and_failed_always_pass(bridge, world):
    job = run_job(bridge)
    bridge.done(job, A, "failed", "stopped")
    assert bridge.jobs[job]["state"] == "failed"
    world.runs[RUN]["open"] = 0
    job = run_job(bridge)
    assert bridge.done(job, A, "done", "x") == {"ok": True}


def test_web_silence_counts_from_the_last_progress_line(bridge, clock):
    job = run_job(bridge)
    clock.t += 119
    assert bridge.get(job)["progress_stale"] is False
    clock.t += 2
    view = bridge.state_view()
    assert view["open"]["progress_stale"] is True and view["open"]["silent"] is False
    bridge.progress(job, A, "r01 running")
    assert bridge.state_view()["open"]["progress_stale"] is False
    # a held call does not hide a stalled web job
    bridge.ask(job, A, {"type": "sign-in", "id": "s1", "scenario": "member"}, 0)
    clock.t += jobs.SILENT_WITH_JOB + 1
    assert bridge.get(job)["silent"] is True
    assert bridge.mark_failed(job)["reason"] == "marked"


def test_needs_input_counts_run_questions(bridge, world):
    ctx = world.context()
    ctx.run_needs_input = lambda: 3
    b = jobs.Bridge(jobs.MemoryStore(), ctx)
    assert b.state_view()["needs_input"] == 3
    ctx.run_needs_input = lambda: 1 / 0
    assert b.state_view()["needs_input"] == 0
