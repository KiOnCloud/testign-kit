import re
import time

import pytest

from testign.console import jobs
from testign.console.server import ApiError

A = "s-aaaaaaaaaaaaaaaa"
RUN = "W20261119-1000-header-update"
SUITE = "S20261125-0900-header-update"
SIGN_IN = {"type": "sign-in", "id": "signin-member", "scenario": "member"}
SIGNED_IN = {"choice": "signed-in"}


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
        self.suites = {SUITE: {"id": SUITE, "state": "generating", "generate_job": None, "generate_job_active": False,
                               "source": {"kind": "backlog", "ticket": "DEMO-1", "report": "DEMO-1-survey-r2.md",
                                          "revision": 2}}}

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
            suite_info=lambda suite: self.suites.get(suite),
            attach_suite=lambda suite, job: self.suites[suite].update(generate_job=job),
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


def run_body(**extra):
    return {"kind": "webtest-run", "ui_lang": "en", "run": RUN, "tester": "T", **extra}


def start(bridge, body, session=A, *, created_before=1.0):
    job = bridge.create(body)
    bridge.jobs[job["id"]]["created_ts"] = time.time() + created_before  # tabs made "now" are older
    assert bridge.wait(session, 0)["job"]["id"] == job["id"]
    bridge.claim(job["id"], session)
    return job["id"]


# kinds ---------------------------------------------------------------------------------------------
def test_suite_generate_carries_the_suites_source_and_attaches_itself(bridge, world):
    job = bridge.create({"kind": "suite-generate", "ui_lang": "ja", "suite": SUITE})
    record = bridge.jobs[job["id"]]
    assert record["suite"] == SUITE and record["params"] == {"suite": SUITE, "source": world.suites[SUITE]["source"],
                                                                "depth": world.suites[SUITE].get("depth")}
    assert record["ticket"] == "DEMO-1" and record["base_revision"] is None  # a later survey must not stop the job
    assert world.suites[SUITE]["generate_job"] == job["id"] and bridge.summary(record)["suite"] == SUITE
    with pytest.raises(ApiError) as exc:
        bridge.create({"kind": "suite-generate", "ui_lang": "en", "suite": SUITE})
    assert exc.value.code == "suite-busy"
    bridge.jobs[job["id"]]["state"] = "done"
    extend = bridge.create({"kind": "suite-generate", "ui_lang": "en", "suite": SUITE, "extend": True})
    assert bridge.jobs[extend["id"]]["params"]["extend"] is True


@pytest.mark.parametrize("change,code", [
    ({"suite": "S20990101-0000-nope"}, "unknown-suite"),
    ({"state": "review"}, "suite-not-generating"),
    ({"generate_job_active": True}, "suite-busy"),
    ({"source": {"kind": "excel", "file": "a.xlsx"}}, "bad-source"),
])
def test_suite_generate_refusals(bridge, world, change, code):
    suite = change.pop("suite", SUITE)
    world.suites[SUITE].update(change)
    with pytest.raises(ApiError) as exc:
        bridge.create({"kind": "suite-generate", "ui_lang": "en", "suite": suite})
    assert exc.value.code == code


def test_the_plan_kind_is_retired(bridge, world, clock):
    with pytest.raises(ApiError):
        bridge.create({"kind": "webtest-plan", "ui_lang": "en", "name": "x", "base_url": "https://dev.example.test/",
                       "project": "demo"})
    store = jobs.MemoryStore()
    store.save({"id": "j20261119-100000-aaaa", "kind": "webtest-plan", "state": "queued", "created_at": "2026-11-19T10:00:00+09:00",
                "params": {}, "asked": []})
    store.save({"id": "j20261119-100000-bbbb", "kind": "webtest-run", "state": "queued", "created_at": "2026-11-19T10:00:00+09:00",
                "params": {}, "asked": []})
    b = jobs.Bridge(store, world.context(), clock=clock)
    b.startup()
    assert b.jobs["j20261119-100000-aaaa"]["reason"] == "retired-kind"
    assert b.jobs["j20261119-100000-bbbb"]["reason"] == "server-stopped"


def test_info_gives_the_agent_its_run_job(bridge):
    job = run_job(bridge)
    assert bridge.info(job, A)["run"] == RUN
    with pytest.raises(ApiError):
        bridge.info(job, "s-otherotherother")


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
    for kind in ("survey", "close", "testcase", "webtest-plan", None):
        with pytest.raises(ApiError):
            bridge.agent_create({"kind": kind, "ui_lang": "en", "ticket": "DEMO-1", "tester": "T"})
    job = bridge.agent_create(run_body())
    assert job["queued_by"] == "agent" and job["opened"] is False
    assert bridge.get(job["id"])["opened"] is False
    assert bridge.get(job["id"], opened=True)["opened"] is True
    assert bridge.summary(bridge.jobs[job["id"]])["opened"] is True


# review table ----------------------------------------------------------------------------------------
def test_a_tab_newer_than_the_web_job_cannot_answer(bridge):
    job = run_job(bridge)
    bridge.ask(job, A, SIGN_IN, 0)
    created = bridge.jobs[job]["created_ts"]
    with pytest.raises(ApiError) as exc:
        bridge.answer(job, {"ask_id": SIGN_IN["id"], "answer": SIGNED_IN}, "browser-s", created + 1)
    assert exc.value.code == "session-too-new"
    bridge.answer(job, {"ask_id": SIGN_IN["id"], "answer": SIGNED_IN}, "browser-s", created - 1)


# sign-in -------------------------------------------------------------------------------------------------
def ask_and_answer(bridge, job, ask, answer, session_created=None):
    assert bridge.ask(job, A, ask, 0) == {"answers": None}
    return bridge.answer(job, {"ask_id": ask["id"], "answer": answer}, "browser-s", session_created)


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


# no older tab ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("gap", [0.0, 0.0004, 0.5])
def test_tab_age_helper_matches_answer(bridge, gap):
    job = run_job(bridge)
    bridge.ask(job, A, SIGN_IN, 0)
    cutoff = jobs.answer_cutoff(bridge.jobs[job])
    for created in (cutoff - gap, cutoff + gap):
        allowed = jobs.tab_can_answer(cutoff, created)
        try:
            bridge.answer(job, {"ask_id": "nope", "answer": SIGNED_IN}, "browser-s", created)
            refused = False
        except ApiError as exc:
            refused = exc.code == "session-too-new"
        assert allowed is not refused


def test_claim_fails_the_job_when_no_tab_is_older(bridge):
    bridge.sessions = lambda: []
    job = bridge.create(run_body())
    assert bridge.wait(A, 0)["job"]["id"] == job["id"]
    with pytest.raises(ApiError) as exc:
        bridge.claim(job["id"], A)
    assert (exc.value.status, exc.value.code) == (409, "no-older-tab")
    record = bridge.jobs[job["id"]]
    assert record["state"] == "failed" and record["reason"] == "no-older-tab"


def test_claim_goes_on_with_an_older_tab(bridge):
    job = bridge.create(run_body())
    cutoff = bridge.jobs[job["id"]]["created_ts"]
    bridge.sessions = lambda: [cutoff - 1, cutoff + 1]
    bridge.wait(A, 0)
    assert bridge.claim(job["id"], A) == {"ok": True}
    assert bridge.jobs[job["id"]]["state"] == "running"


def test_a_held_ask_fails_with_no_older_tab(bridge):
    job = run_job(bridge)
    cutoff = bridge.jobs[job]["created_ts"]
    bridge.sessions = lambda: [cutoff + 5]  # only a tab opened after the job was queued
    with pytest.raises(ApiError) as exc:
        bridge.ask(job, A, SIGN_IN, 0)
    assert exc.value.code == "no-older-tab"
    assert bridge.jobs[job]["state"] == "failed" and bridge.jobs[job]["reason"] == "no-older-tab"


def test_can_answer_is_computed_for_the_requesting_tab(bridge):
    job = run_job(bridge)
    bridge.ask(job, A, SIGN_IN, 0)
    cutoff = bridge.jobs[job]["created_ts"]
    assert bridge.get(job, session_created=cutoff - 1)["can_answer"] is True
    assert bridge.get(job, session_created=cutoff + 1)["can_answer"] is False
    assert bridge.get(job, session_created=cutoff)["can_answer"] is False


def test_the_agent_marks_a_requeue_after_no_older_tab(bridge):
    job = bridge.agent_create({**run_body(), "queued_after": "no-older-tab"})
    assert job["queued_after"] == "no-older-tab" and job["queued_by"] == "agent"
    assert bridge.create({**run_body(), "queued_after": "no-older-tab"})["queued_after"] is None
    with pytest.raises(ApiError) as exc:
        bridge.agent_create({**run_body(), "queued_after": "anything"})
    assert exc.value.code == "bad-request"


# review answers that confirmation would drop -----------------------------------------------------------
def test_a_requeue_with_no_tab_at_all_is_refused(bridge):
    bridge.sessions = lambda: []
    with pytest.raises(ApiError) as exc:
        bridge.agent_create({**run_body(), "queued_after": "no-older-tab"})
    assert exc.value.code == "no-tab" and not bridge.jobs
    bridge.sessions = lambda: [time.time()]
    assert bridge.agent_create({**run_body(), "queued_after": "no-older-tab"})["queued_after"] == "no-older-tab"


def test_the_session_reports_its_tools_and_a_new_session_starts_unknown(bridge, clock):
    assert bridge.state_view()["agent"]["capabilities"] is None
    with pytest.raises(ApiError):
        bridge.report_capabilities({"session": A, "chrome": "yes", "figma": False, "backlog": False})
    bridge.report_capabilities({"session": A, "chrome": True, "figma": False, "backlog": True})
    caps = bridge.state_view()["agent"]["capabilities"]
    assert caps["chrome"] and not caps["figma"] and caps["backlog"] and caps["at"]
    clock.t += 3600  # the old session went silent long enough to be taken over
    bridge.wait("s-bbbbbbbbbbbbbbbb", 0)
    assert bridge.state_view()["agent"]["capabilities"] is None
