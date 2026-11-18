import itertools
import re
import threading
import time

import pytest

from testign.console import jobs
from testign.console.server import ApiError

STATES = ("queued", "offered", "running", "needs-input", "done", "failed", "cancelled")
A = "s-aaaaaaaaaaaaaaaa"
B = "s-bbbbbbbbbbbbbbbb"


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


class World:
    """A fake context: tickets with their latest revision, templates, workbooks and rows."""

    def __init__(self):
        self.latest = {"DEMO-1": "DEMO-1-survey-r2.md"}
        self.templates = {"default": "a", "templates": [{"name": "a"}]}
        self.workbooks = {"DEMO-1": ["tc.xlsx"]}
        self.rows = {"DEMO-1": {"B1", "B2", "R1"}}
        self.repos = {"/repo"}

    def context(self):
        return jobs.Context(
            cfg=lambda: {"ticket_id_regex": r"\b[A-Z][A-Z0-9_]+-\d+\b", "lang": "vi"},
            ticket_rx=lambda cfg: re.compile(r"[A-Z][A-Z0-9_]+-\d+"),
            latest=lambda t: {"name": self.latest[t]} if t in self.latest else None,
            templates=lambda: self.templates,
            workbooks=lambda t: self.workbooks.get(t, []),
            row_ids=lambda t: self.rows.get(t, set()),
            usable_repo=lambda r: r if r in self.repos else None,
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


def close_job(bridge, **extra):
    return bridge.create({"kind": "close", "ticket": "DEMO-1", "tester": "Asher", "ui_lang": "ja", **extra})


def running(bridge, session=A):
    job = close_job(bridge)
    offered = bridge.wait(session, 0)
    assert offered["job"]["id"] == job["id"]
    assert bridge.claim(job["id"], session) == {"ok": True}
    return job["id"]


QUESTIONS = {"type": "questions", "id": "q1", "questions": [
    {"question": "Ticket text?", "header": "Ticket", "options": [{"label": "Paste"}, {"label": "Skip"}],
     "other": "multiline"}]}
ROWS = {"type": "review-rows", "id": "rows1", "rows": [
    {"row": "r1", "q": "Q1", "class": "intent", "feature": "注文確定", "page": "QA/Decisions/order",
     "anchors": ["確定"], "decision": "Discount applies", "quote": "割引は適用", "quote_lang": "ja",
     "source": "Backlog comment", "decided_by": "BrSE", "date": "2026-11-18"},
    {"row": "r2", "q": "Q1", "class": "fact", "decision": "Rounding down", "quote": "", "source": "",
     "decided_by": "Dev", "date": "2026-11-18"}]}


def test_every_transition_pair(bridge):
    with bridge.cond:
        _every_pair(bridge)


def _every_pair(bridge):
    for start, to in itertools.product(STATES, STATES):
        job = {"id": f"j-{start}-{to}", "state": start, "ask": None, "asked": []}
        if (start, to) in jobs.TRANSITIONS:
            bridge._move(job, to)
            assert job["state"] == to
        else:
            with pytest.raises(ApiError) as err:
                bridge._move(job, to)
            assert err.value.status == 409


def test_job_record_shape_and_kind_table(bridge):
    job = close_job(bridge)
    record = bridge.jobs[job["id"]]
    assert re.fullmatch(r"j\d{8}-\d{6}-[0-9a-f]{4}", record["id"])
    assert record["state"] == "queued" and record["base_revision"] == "DEMO-1-survey-r2.md"
    assert record["params"] == {"tester": "Asher"} and record["ui_lang"] == "ja" and record["report_lang"] is None
    assert set(jobs.KINDS) == {"survey", "close", "testcase"}


@pytest.mark.parametrize("body,code", [
    ({"kind": "deploy", "ui_lang": "vi"}, "bad-request"),
    ({"kind": "close", "ticket": "DEMO-1", "tester": "A"}, "bad-request"),
    ({"kind": "close", "ticket": "DEMO-1", "ui_lang": "fr", "tester": "A"}, "bad-request"),
    ({"kind": "close", "ticket": "DEMO-1", "ui_lang": "vi"}, "tester-required"),
    ({"kind": "close", "ticket": "DEMO-1", "ui_lang": "vi", "tester": "x" * 101}, "tester-required"),
    ({"kind": "close", "ticket": "DEMO-9", "ui_lang": "vi", "tester": "A"}, "not-found"),
    ({"kind": "survey", "ticket": "demo-1", "repo": "/repo", "ui_lang": "vi"}, "bad-request"),
    ({"kind": "survey", "ticket": "DEMO-5", "repo": "/plain", "ui_lang": "vi"}, "bad-request"),
    ({"kind": "survey", "ticket": "DEMO-5", "repo": "/repo", "master_ref": "a b", "ui_lang": "vi"}, "bad-request"),
    ({"kind": "survey", "ticket": "DEMO-5", "repo": "/repo", "fetch": "yes", "ui_lang": "vi"}, "bad-request"),
    ({"kind": "survey", "ticket": "DEMO-5", "repo": "/repo", "report_lang": "fr", "ui_lang": "vi"}, "bad-request"),
    ({"kind": "testcase", "ticket": "DEMO-1", "mode": "trace", "workbook": "tc.xlsx", "ui_lang": "vi"},
     "template-required"),
    ({"kind": "testcase", "ticket": "DEMO-1", "mode": "write", "template": "zz", "ui_lang": "vi"}, "unknown-template"),
    ({"kind": "testcase", "ticket": "DEMO-1", "mode": "trace", "template": "a", "ui_lang": "vi"}, "workbook-required"),
    ({"kind": "testcase", "ticket": "DEMO-1", "mode": "write", "workbook": "x.xlsx", "ui_lang": "vi"},
     "unknown-workbook"),
    ({"kind": "testcase", "ticket": "DEMO-1", "mode": "write", "focus": ["R3"], "ui_lang": "vi"}, "unknown-row"),
    ({"kind": "testcase", "ticket": "DEMO-1", "mode": "draw", "ui_lang": "vi"}, "bad-request"),
])
def test_kind_checks(bridge, body, code):
    with pytest.raises(ApiError) as err:
        bridge.create(body)
    assert err.value.code == code


def test_kind_checks_accept_valid_jobs(bridge, world):
    survey = bridge.create({"kind": "survey", "ticket": "DEMO-5", "repo": "/repo", "develop_ref": "release/1.2",
                            "fetch": True, "feature": "注文確定", "ui_lang": "en"})
    record = bridge.jobs[survey["id"]]
    assert record["report_lang"] == "vi" and record["base_revision"] is None
    assert record["params"] == {"repo": "/repo", "develop_ref": "release/1.2", "fetch": True, "feature": "注文確定"}
    tc = bridge.create({"kind": "testcase", "ticket": "DEMO-1", "mode": "write", "focus": ["R1"], "ui_lang": "vi"})
    assert bridge.jobs[tc["id"]]["params"] == {"mode": "write", "template": "a", "focus": ["R1"]}
    world.templates = {"default": "a", "templates": [{"name": "a"}, {"name": "b"}]}
    with pytest.raises(ApiError):
        bridge.create({"kind": "testcase", "ticket": "DEMO-1", "mode": "write", "ui_lang": "vi"})


def test_wait_offers_one_job_at_a_time_in_order(bridge):
    first = close_job(bridge)
    second = close_job(bridge)
    assert bridge.wait(A, 0)["job"]["id"] == first["id"]
    assert bridge.jobs[first["id"]]["state"] == "offered"
    bridge.claim(first["id"], A)
    assert bridge.jobs[second["id"]]["state"] == "queued"
    assert bridge.busy() is True


def test_wait_with_nothing_queued(bridge):
    assert bridge.wait(A, 0) == {"session": A, "job": None}
    assert bridge.busy() is False


def test_unclaimed_offer_returns_to_the_queue(bridge, clock):
    job = close_job(bridge)
    bridge.wait(A, 0)
    clock.t += jobs.OFFER_TIMEOUT
    bridge.tick()
    assert bridge.jobs[job["id"]]["state"] == "queued"


def test_new_wait_from_the_same_session_takes_back_an_unclaimed_offer(bridge):
    job = close_job(bridge)
    assert bridge.wait(A, 0)["job"]["id"] == job["id"]
    assert bridge.wait(A, 0)["job"]["id"] == job["id"]
    assert bridge.jobs[job["id"]]["state"] == "offered"


def test_claim_fails_with_revision_moved(bridge, world):
    job = close_job(bridge)
    bridge.wait(A, 0)
    world.latest["DEMO-1"] = "DEMO-1-survey-r3.md"
    assert bridge.claim(job["id"], A) == {"ok": False, "reason": "revision-moved"}
    assert bridge.jobs[job["id"]]["state"] == "failed" and bridge.jobs[job["id"]]["reason"] == "revision-moved"


def test_progress_ask_and_done_claim_implicitly(bridge):
    job = close_job(bridge)
    bridge.wait(A, 0)
    bridge.progress(job["id"], A, "Đang đọc report")
    assert bridge.jobs[job["id"]]["state"] == "running"
    assert bridge.jobs[job["id"]]["started_at"]


def test_ask_answer_round_trip_with_edit(bridge):
    job_id = running(bridge)
    assert bridge.ask(job_id, A, ROWS, 0) == {"answers": None}
    assert bridge.jobs[job_id]["state"] == "needs-input"
    with pytest.raises(ApiError):
        bridge.answer(job_id, {"ask_id": "rows1", "answer": {"rows": {"r1": {"action": "write"}}}}, "tok")
    with pytest.raises(ApiError):
        bridge.answer(job_id, {"ask_id": "rows1", "answer": {"rows": {"r1": {"action": "edit"},
                                                                       "r2": {"action": "skip"}}}}, "tok")
    bridge.answer(job_id, {"ask_id": "rows1", "answer": {"rows": {
        "r1": {"action": "edit", "decision": "Discount applies to 請求書 too", "anchors": ["確定", "請求書"]},
        "r2": {"action": "skip"}}}}, "browser-token")
    assert bridge.jobs[job_id]["state"] == "running"
    got = bridge.ask(job_id, A, ROWS, 0)
    assert got["answers"]["rows"]["r1"]["decision"] == "Discount applies to 請求書 too"
    asked = bridge.jobs[job_id]["asked"][0]
    assert asked["answered_by"] == jobs.fingerprint("browser-token") and "browser-token" not in str(asked)
    with pytest.raises(ApiError) as err:
        bridge.ask(job_id, A, ROWS, 0)
    assert err.value.code == "bad-request"


def test_second_answer_to_the_same_ask_is_refused(bridge):
    job_id = running(bridge)
    bridge.ask(job_id, A, QUESTIONS, 0)
    answer = {"ask_id": "q1", "answer": [{"selected": [], "other": "line one\nline two"}]}
    bridge.answer(job_id, answer, "t")
    with pytest.raises(ApiError) as err:
        bridge.answer(job_id, answer, "t")
    assert err.value.status == 409
    assert bridge.ask(job_id, A, QUESTIONS, 0)["answers"][0]["other"] == "line one\nline two"


def test_confirm_diff_stores_the_confirmed_approval(bridge):
    job_id = running(bridge)
    preview = {"pages": [{"name": "QA/Decisions/order", "exists": False, "updated": None, "diff": "+ row"}],
               "added": ["Q1"], "skipped": [], "superseded": [], "index_repaired": [], "approval": "abc123"}
    bridge.ask(job_id, A, {"type": "confirm-diff", "id": "confirm-abc", "preview": preview}, 0)
    assert bridge.approval(job_id, A) == {"approval": None}
    bridge.answer(job_id, {"ask_id": "confirm-abc", "answer": {"confirm": True}}, "t")
    assert bridge.approval(job_id, A) == {"approval": "abc123"}


@pytest.mark.parametrize("ask", [
    {"type": "questions", "id": "x", "questions": []},
    {"type": "questions", "id": "bad id!", "questions": QUESTIONS["questions"]},
    {"type": "questions", "id": "x", "body": "a‮b", "questions": QUESTIONS["questions"]},
    {"type": "questions", "id": "x", "body": "x" * 8001, "questions": QUESTIONS["questions"]},
    {"type": "questions", "id": "x", "questions": [{"question": "q\x07", "options": [{"label": "a"}, {"label": "b"}]}]},
    {"type": "review-rows", "id": "x", "rows": [{"row": "r1"}, {"row": "r1"}]},
    {"type": "confirm-diff", "id": "x", "preview": {"pages": []}},
    {"type": "shell", "id": "x"},
])
def test_bad_asks_are_refused(bridge, ask):
    job_id = running(bridge)
    with pytest.raises(ApiError) as err:
        bridge.ask(job_id, A, ask, 0)
    assert err.value.status == 400


def test_agent_progress_text_is_checked(bridge):
    job_id = running(bridge)
    with pytest.raises(ApiError):
        bridge.progress(job_id, A, "evil⁦text")
    with pytest.raises(ApiError):
        bridge.progress(job_id, A, "")


def test_done_while_a_question_is_open(bridge):
    job_id = running(bridge)
    bridge.ask(job_id, A, QUESTIONS, 0)
    with pytest.raises(ApiError):
        bridge.done(job_id, A, "done", None)
    bridge.done(job_id, A, "failed", "Tester did not answer")
    assert bridge.jobs[job_id]["state"] == "failed" and bridge.jobs[job_id]["asked"][0]["outcome"] == "unanswered"


def test_done_closes_the_job(bridge):
    job_id = running(bridge)
    bridge.done(job_id, A, "done", "Wrote 2 rows")
    job = bridge.jobs[job_id]
    assert job["state"] == "done" and job["summary"] == "Wrote 2 rows" and job["finished_at"]
    assert bridge.busy() is False


def test_waiting_again_with_a_running_job_fails_it_as_not_closed(bridge):
    job_id = running(bridge)
    bridge.wait(A, 0)
    assert bridge.jobs[job_id]["reason"] == "not-closed"


def test_takeover_rules(bridge, clock):
    bridge.wait(A, 0)
    with pytest.raises(ApiError) as err:
        bridge.wait(B, 0)
    assert err.value.code == "session-refused"
    clock.t += jobs.SILENT_NO_JOB
    assert bridge.wait(B, 0)["session"] == B

    job_id = running(bridge, B)
    clock.t += jobs.SILENT_NO_JOB
    with pytest.raises(ApiError):
        bridge.wait(A, 0)
    clock.t += jobs.SILENT_WITH_JOB
    bridge.wait(A, 0)
    assert bridge.jobs[job_id]["state"] == "failed" and bridge.jobs[job_id]["reason"] == "session-lost"
    with pytest.raises(ApiError) as err:
        bridge.progress(job_id, B, "still here")
    assert err.value.code == "session-replaced"


def test_mark_failed_only_when_silent(bridge, clock):
    job_id = running(bridge)
    with pytest.raises(ApiError):
        bridge.mark_failed(job_id)
    assert bridge.state_view()["open"]["silent"] is False
    clock.t += jobs.SILENT_WITH_JOB
    assert bridge.state_view()["open"]["silent"] is True
    bridge.mark_failed(job_id)
    assert bridge.jobs[job_id]["reason"] == "marked"


def test_release_fails_the_open_job(bridge):
    job_id = running(bridge)
    assert bridge.release() == {"released": True}
    assert bridge.jobs[job_id]["reason"] == "session-lost"
    assert bridge.state_view()["agent"]["attached"] is False


def test_cancel_only_queued(bridge):
    job = close_job(bridge)
    bridge.cancel(job["id"])
    assert bridge.jobs[job["id"]]["state"] == "cancelled"
    job_id = running(bridge)
    with pytest.raises(ApiError):
        bridge.cancel(job_id)


def test_restart_fails_open_and_queued_jobs(world, clock):
    store = jobs.MemoryStore()
    first = jobs.Bridge(store, world.context(), clock=clock)
    first.startup()
    open_id = running(first)
    queued = close_job(first)
    second = jobs.Bridge(store, world.context(), clock=clock)
    second.startup()
    assert second.jobs[open_id]["state"] == "failed" and second.jobs[open_id]["reason"] == "server-stopped"
    assert second.jobs[queued["id"]]["reason"] == "server-stopped"
    assert second.busy() is False


@pytest.fixture
def live(world):
    """A bridge on the real clock, for tests where held calls run in threads."""
    b = jobs.Bridge(jobs.MemoryStore(), world.context())
    b.startup()
    yield b
    b.shutdown()


def spawn(fn):
    t = threading.Thread(target=fn, daemon=True)
    t.start()
    return t


def test_shutdown_fails_open_jobs_and_releases_held_calls(live):
    job = close_job(live)
    out = {}
    live.wait(A, 0)
    live.claim(job["id"], A)
    t = spawn(lambda: out.setdefault("ask", live.ask(job["id"], A, QUESTIONS, 30)))
    time.sleep(0.3)
    live.shutdown()
    t.join(5)
    assert not t.is_alive()
    assert live.jobs[job["id"]]["reason"] == "server-stopped"


def test_a_newer_held_call_replaces_the_older_one(live):
    out = {}
    t = spawn(lambda: out.setdefault("first", live.wait(A, 30)))
    time.sleep(0.3)
    job = close_job(live)
    t.join(5)
    assert out["first"]["job"]["id"] == job["id"]

    live.claim(job["id"], A)
    live.done(job["id"], A, "done", None)
    t = spawn(lambda: out.setdefault("old", live.wait(A, 30)))
    time.sleep(0.3)
    started = time.monotonic()
    t2 = spawn(lambda: out.setdefault("new", live.wait(A, 1)))
    t.join(5)
    assert out["old"] == {"session": A, "job": None} and time.monotonic() - started < 2
    t2.join(5)
    assert not t2.is_alive() and out["new"] == {"session": A, "job": None}


def test_pruning_keeps_the_newest_finished_jobs(world, clock):
    store = jobs.MemoryStore()
    b = jobs.Bridge(store, world.context(), clock=clock)
    b.startup()
    for _ in range(jobs.KEEP_FINISHED + 5):
        b.cancel(close_job(b)["id"])
    b2 = jobs.Bridge(store, world.context(), clock=clock)
    b2.startup()
    assert len(b2.jobs) == jobs.KEEP_FINISHED
