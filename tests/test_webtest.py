import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from make_webtest_run import HOSTS, FakeConsole, build
from testign import webtest
from testign.webtest import WebtestError

S = "s-test0001"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


@pytest.fixture
def root(tmp_path):
    return tmp_path / "out" / "webtest"


@pytest.fixture
def server():
    return FakeConsole()


def folder_of(root, run_id):
    return webtest.find_run(root, run_id)


def run_job(server, run_id, job="j-run1"):
    server.add_job(job, "webtest-run", run=run_id, tester="Asher")
    return job


def state(root, run_id, row):
    return webtest.case_of(webtest.load(folder_of(root, run_id)), row)


def take_row(root, server, run_id, job, evidence=True):
    folder = folder_of(root, run_id)
    got = webtest.next_row(folder, server, job, S)
    if got.get("row") and evidence:
        webtest.add_evidence(folder, got["row"], PNG, "agent")
    return got


@pytest.mark.parametrize("case", [
    {"row": "x1", "source": {"kind": "figma"}, "content": "a"},
    {"row": "r01", "source": {"kind": "mail"}, "content": "a"},
    {"row": "r01", "source": {"kind": "workbook"}, "content": "a"},
    {"row": "r01", "source": {"kind": "figma"}, "content": ""},
    {"row": "r01", "source": {"kind": "figma"}, "content": "a", "steps": "agent text"},
])
def test_bad_staged_cases_are_refused(case):
    with pytest.raises(WebtestError):
        webtest.check_staged(case)


def test_a_run_from_a_suite_sets_the_initial_states(root, server):
    run_id = build(root, server)
    run = webtest.load(folder_of(root, run_id))
    by_row = {c["row"]: c for c in run["cases"]}
    assert by_row["r01"]["state"] == "queued"
    assert by_row["r05"]["state"] == "not-run" and by_row["r05"]["not_run_reason"] == "unanswered"
    assert by_row["r06"]["state"] == "manual"
    assert by_row["r07"]["state"] == "not-applicable"
    assert by_row["r08"]["state"] == "awaiting-tester"
    assert run["confirmed"]["by"] == "Asher"


def test_a_delegated_choice_case_needs_preconditions(root, server):
    with pytest.raises(WebtestError, match="preconditions"):
        build(root, server, rows_answer={"r05": {"runner": "agent"}})


def test_delegated_choice_row_records_who_decided(root, server):
    run_id = build(root, server, rows_answer={"r05": {"runner": "agent", "preconditions": "A confirmed reservation"}})
    case = state(root, run_id, "r05")
    assert case["state"] == "queued" and case["decided_by"]["by"] == "Asher"


def test_a_suite_with_an_agent_case_lacking_a_scenario_or_a_screen_is_not_confirmed(root, server):
    with pytest.raises(WebtestError, match="scenario"):
        build(root, server, rows_answer={"r04": {"scenario": None}})
    with pytest.raises(WebtestError, match="screen"):
        build(root / "other", server, rows_answer={"r02": {"screen": ""}})


def test_phone_cases_default_to_the_real_device_method(root, server):
    run = webtest.load(folder_of(root, build(root, server)))
    by_row = {c["row"]: c for c in run["cases"]}
    assert by_row["r08"]["mobile_method"] == "device"
    assert by_row["r02"].get("mobile_method") is None  # pc rows carry no method


def test_a_real_device_case_is_never_the_agents(root, server):
    with pytest.raises(WebtestError, match="real device go to the tester"):
        build(root, server, rows_answer={"r08": {"runner": "agent"}})


def test_an_emulated_phone_case_is_queued_for_the_agent(root, server):
    run_id = build(root, server, rows_answer={"r08": {"runner": "agent", "mobile_method": "emulation"}})
    case = state(root, run_id, "r08")
    assert case["state"] == "queued" and case["mobile_method"] == "emulation"
    view = webtest.worker_view(webtest.load(folder_of(root, run_id)), case)
    assert view["viewport"] == "mobile" and view["mobile_method"] == "emulation"


def test_a_pc_case_has_no_phone_method(root, server):
    run_id = build(root, server, rows_answer={"r08": {"viewport": "pc", "runner": "agent"}})
    case = state(root, run_id, "r08")
    assert case["viewport"] == "pc" and case["mobile_method"] is None and case["state"] == "queued"


def test_a_run_written_before_mobile_methods_still_loads(root, server):
    folder = folder_of(root, build(root, server))
    raw = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    for case in raw["cases"]:
        case.pop("mobile_method", None)
    (folder / "run.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    run = webtest.load(folder)
    case = next(c for c in run["cases"] if c["row"] == "r08")
    assert webtest.worker_view(run, case)["mobile_method"] == "device"


def test_next_only_returns_agent_rows_of_the_signed_in_scenario(root, server):
    run_id = build(root, server)
    job = run_job(server, run_id)
    webtest.recover(folder_of(root, run_id), server, job, S)
    got = take_row(root, server, run_id, job)
    assert got["row"] == "r02"  # public page first
    webtest.record_row(folder_of(root, run_id), "r02", {"verdict": "pass", "actual": "ok",
                                                         "url": "https://dev.example.test/"})
    got = webtest.next_row(folder_of(root, run_id), server, job, S)
    assert got == {"row": None, "need": "member", "signed_in": None}
    server.sign_ins[job] = {"scenario": "member", "choice": "signed-in", "at": "t"}
    webtest.signed_in(folder_of(root, run_id), server, job, S, "member")
    seen = []
    while True:
        got = take_row(root, server, run_id, job)
        if not got.get("row"):
            break
        seen.append(got["row"])
        webtest.record_row(folder_of(root, run_id), got["row"],
                           {"verdict": "fail", "actual": "no", "url": "https://dev.example.test/mypage"})
    assert set(seen) == {"r01", "r03", "r04"}  # never r05 (choice, undecided), r08 (tester) or not-web rows


def test_next_ignores_a_sign_in_from_another_job_and_refuses_other_jobs(root, server):
    run_id = build(root, server)
    folder = folder_of(root, run_id)
    run = webtest.load(folder)
    run["signed_in"] = {"scenario": "member", "job": "j-old", "at": "t"}  # left by an earlier job
    webtest.save(folder, run)
    with pytest.raises((WebtestError, ValueError)):  # the console refuses a job it does not know
        webtest.next_row(folder, server, "j-made-up", S)
    job = run_job(server, run_id)
    with pytest.raises((WebtestError, ValueError)):
        webtest.next_row(folder, server, job, "s-other")
    got = webtest.next_row(folder, server, job, S)
    assert got["row"] == "r02"  # the public row only; member rows wait for a sign-in in this job
    webtest.add_evidence(folder, "r02", PNG, "agent")
    webtest.record_row(folder, "r02", {"verdict": "pass", "actual": "ok", "url": "https://dev.example.test/"})
    assert webtest.next_row(folder, server, job, S) == {"row": None, "need": "member", "signed_in": None}
    server.end_job(job)
    with pytest.raises(WebtestError):
        webtest.next_row(folder, server, job, S)


def test_a_sign_in_is_not_reused_after_the_session_was_signed_out(root, server):
    run_id = build(root, server)
    folder = folder_of(root, run_id)
    job = run_job(server, run_id)
    server.sign_ins[job] = {"scenario": "member", "choice": "signed-in", "at": "t1"}
    webtest.signed_in(folder, server, job, S, "member")
    got = webtest.next_row(folder, server, job, S)
    webtest.requeue(folder, got["row"], "signed out", signed_out=True)
    with pytest.raises(WebtestError, match="sign in again"):
        webtest.signed_in(folder, server, job, S, "member")
    server.sign_ins[job] = {"scenario": "member", "choice": "signed-in", "at": "t2"}  # the tester answered again
    assert webtest.signed_in(folder, server, job, S, "member")["signed_in"] == "member"


def test_off_site_result_becomes_not_run(root, server):
    run_id = build(root, server)
    job = run_job(server, run_id)
    take_row(root, server, run_id, job)
    out = webtest.record_row(folder_of(root, run_id), "r02",
                             {"verdict": "pass", "actual": "ok", "url": "https://dev.example.test.evil.test/"})
    assert out["reason"] == "off-site"
    assert state(root, run_id, "r02")["not_run_reason"] == "off-site"


def test_pass_needs_evidence_of_the_current_attempt(root, server):
    run_id = build(root, server)
    job = run_job(server, run_id)
    take_row(root, server, run_id, job)  # attempt 1 with evidence
    webtest.requeue(folder_of(root, run_id), "r02", "page did not load")
    take_row(root, server, run_id, job, evidence=False)  # attempt 2, no evidence yet
    with pytest.raises(WebtestError, match="no evidence for attempt 2"):
        webtest.record_row(folder_of(root, run_id), "r02",
                           {"verdict": "pass", "actual": "ok", "url": "https://dev.example.test/"})
    webtest.add_evidence(folder_of(root, run_id), "r02", JPG, "agent")
    out = webtest.record_row(folder_of(root, run_id), "r02",
                             {"verdict": "pass", "actual": "ok", "url": "https://dev.example.test/"})
    assert out["evidence"] == ["evidence/r02-a2-1.jpg"]


def test_evidence_must_be_an_image(root, server):
    run_id = build(root, server)
    job = run_job(server, run_id)
    take_row(root, server, run_id, job, evidence=False)
    with pytest.raises(WebtestError, match="PNG or JPEG"):
        webtest.add_evidence(folder_of(root, run_id), "r02", b"<svg/>", "agent")
    with pytest.raises(WebtestError):
        webtest.add_evidence(folder_of(root, run_id), "r06", PNG, "agent")


def test_parked_sure_row_becomes_choice_and_requeued_one_does_not(root, server):
    run_id = build(root, server)
    job = run_job(server, run_id)
    take_row(root, server, run_id, job)
    webtest.requeue(folder_of(root, run_id), "r02", "a browser dialog")
    assert state(root, run_id, "r02")["class"] == "sure"
    take_row(root, server, run_id, job)
    out = webtest.park(folder_of(root, run_id), "r02", {"body": "The footer has no help link; another page?"})
    assert out["question"] == "r02-a2"
    case = state(root, run_id, "r02")
    assert case["class"] == "choice" and case["class_changed"]["from"] == "sure"


def test_three_requeues_in_a_row_halt_the_run(root, server):
    run_id = build(root, server)
    job = run_job(server, run_id)
    for _ in range(3):
        take_row(root, server, run_id, job)
        out = webtest.requeue(folder_of(root, run_id), "r02", "extension lost")
    assert out["halted"] is True
    assert webtest.next_row(folder_of(root, run_id), server, job, S) == {"row": None, "halted": True}


def test_a_dead_job_is_recovered_and_the_run_closes_and_exports(root, server):
    run_id = build(root, server)
    first = run_job(server, run_id, "j-run1")
    webtest.recover(folder_of(root, run_id), server, first, S)
    take_row(root, server, run_id, first)
    server.end_job(first)  # the session died with r02 running
    second = run_job(server, run_id, "j-run2")
    with pytest.raises(WebtestError):
        webtest.next_row(folder_of(root, run_id), server, second, S)
    out = webtest.recover(folder_of(root, run_id), server, second, S)
    assert out["requeued"] == ["r02"]
    case = state(root, run_id, "r02")
    assert case["state"] == "queued" and case["attempt"] == 1
    closed = webtest.close(folder_of(root, run_id), server.job_open, stopped=True)
    assert webtest.open_rows(webtest.load(folder_of(root, run_id))) == 0
    assert "r02" in closed["closed"]


def test_recover_refuses_a_row_of_an_open_job(root, server):
    run_id = build(root, server)
    first = run_job(server, run_id, "j-run1")
    take_row(root, server, run_id, first)
    second = run_job(server, run_id, "j-run2")
    with pytest.raises(WebtestError, match="still open"):
        webtest.recover(folder_of(root, run_id), server, second, S)
    with pytest.raises(WebtestError, match="still open"):
        webtest.close(folder_of(root, run_id), server.job_open)


def test_answers_apply_once_and_only_to_their_attempt(root, server, tmp_path):
    run_id = build(root, server)
    job = run_job(server, run_id)
    take_row(root, server, run_id, job)
    webtest.park(folder_of(root, run_id), "r02", {"body": "Which page?"})
    server.answers["r02-a1"] = {"action": "delegate", "preconditions": "Use the help page", "by": "fp", "at": "t"}
    images = tmp_path / "images"
    out = webtest.resolve(folder_of(root, run_id), server, job, S, images)
    assert out["applied"] == ["r02-a1"]
    case = state(root, run_id, "r02")
    assert case["state"] == "queued" and case["preconditions"] == "Use the help page"
    # The same answer again changes nothing.
    server.done_ids.clear()
    before = webtest.load(folder_of(root, run_id))
    out = webtest.resolve(folder_of(root, run_id), server, job, S, images)
    assert out["applied"] == [] and out["ignored"] == ["r02-a1"]
    assert webtest.load(folder_of(root, run_id))["cases"] == before["cases"]
    # An answer to the first park is not applied to the second.
    take_row(root, server, run_id, job)
    webtest.park(folder_of(root, run_id), "r02", {"body": "Still missing"})
    server.done_ids.clear()
    out = webtest.resolve(folder_of(root, run_id), server, job, S, images)
    assert state(root, run_id, "r02")["state"] == "parked" and out["applied"] == []


def test_tester_result_with_an_image(root, server, tmp_path):
    run_id = build(root, server)
    job = run_job(server, run_id)
    images = tmp_path / "images"
    images.mkdir()
    (images / "0123456789abcdef.png").write_bytes(PNG)
    server.results["r08-r0"] = {"verdict": "fail", "actual": "Still 料金", "image": "0123456789abcdef",
                                "by": "fp", "at": "t"}
    out = webtest.resolve(folder_of(root, run_id), server, job, S, images)
    assert out["applied"] == ["r08-r0"]
    case = state(root, run_id, "r08")
    assert case["state"] == "self-run" and case["result"]["evidence"] == ["evidence/r08-a0-1.png"]
    assert (folder_of(root, run_id) / "evidence" / "r08-a0-1.png").read_bytes() == PNG


def test_skip_scenario_marks_its_rows(root, server):
    run_id = build(root, server)
    job = run_job(server, run_id)
    server.sign_ins[job] = {"scenario": "member", "choice": "skip", "at": "t"}
    out = webtest.signed_in(folder_of(root, run_id), server, job, S, "member")
    assert set(out["skipped"]) == {"r01", "r03", "r04"}
    with pytest.raises(WebtestError):
        webtest.signed_in(folder_of(root, run_id), server, job, S, "admin")


def test_close_leaves_no_open_row(root, server):
    run_id = build(root, server, rows_answer={"r05": {"runner": "agent", "preconditions": "x"}})
    job = run_job(server, run_id)
    take_row(root, server, run_id, job)
    webtest.park(folder_of(root, run_id), "r02", {"body": "?"})
    server.end_job(job)
    out = webtest.close(folder_of(root, run_id), server.job_open)
    run = webtest.load(folder_of(root, run_id))
    assert webtest.open_rows(run) == 0
    reasons = {c["row"]: c.get("not_run_reason") for c in run["cases"] if c["state"] == "not-run"}
    assert reasons["r02"] == "unanswered" and reasons["r08"] == "no-result" and reasons["r01"] == "stopped"
    assert set(out["closed"]) >= {"r01", "r02", "r08"}


@pytest.mark.parametrize("bad", ["..", "W20261119-1000-a/../b", "W20261119-1000-a%2Fb", "W20261119-1000-a\\b",
                                 "../W20261119-1000-a", "w20261119-1000-a", ""])
def test_run_ids_with_separators_are_not_found(root, server, bad):
    build(root, server)
    with pytest.raises(WebtestError, match="no such run"):
        webtest.find_run(root, bad)


def test_host_check_is_exact_after_idna():
    assert webtest.url_on_hosts("https://DEV.example.test/a", HOSTS)
    assert not webtest.url_on_hosts("https://dev.example.test.evil.test/", HOSTS)
    assert not webtest.url_on_hosts("https://x.dev.example.test/", HOSTS)
    assert not webtest.url_on_hosts("javascript:alert(1)", HOSTS)
    assert not webtest.url_on_hosts("ftp://dev.example.test/", HOSTS)
    assert webtest.url_on_hosts("https://bücher.test/", ["xn--bcher-kva.test"])
    with pytest.raises(WebtestError):
        webtest.check_host("*.example.test")


@pytest.mark.parametrize("url", [
    "https://evil.example\\@dev.example.test/login",  # Chrome goes to evil.example
    "https://evil.example@dev.example.test/",
    "https://user:pw@dev.example.test/",
    "https://dev.example.test%2F@evil.example/",
    "https://dev%2Eexample.test/",
    "https://dev.example.test/a b",
    "https://dev.example.test/\t",
    "https://dev.example.test/\x00",
])
def test_host_check_refuses_urls_browsers_read_differently(url):
    assert not webtest.url_on_hosts(url, HOSTS)
    assert not webtest.screen_url_ok(url, HOSTS)


def test_a_hand_edited_run_json_is_refused(root, server):
    run_id = build(root, server)
    folder = folder_of(root, run_id)
    data = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    data["cases"][0]["state"] = "done"
    (folder / "run.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(WebtestError, match="unknown state"):
        webtest.load(folder)


def test_cli_status_and_bad_run_exit_2(tmp_path):
    from console_helpers import run_cli, write_config

    write_config(tmp_path)
    out = run_cli(tmp_path, "webtest-status", "--run", "W20261119-1000-nothing")
    assert out.returncode == 2 and "no such run" in out.stderr


def test_cli_reports_an_unreadable_file_without_its_path(tmp_path, server):
    root = tmp_path / "Downloads" / "webtest"
    run_id = build(root, server)
    missing = tmp_path / "secret-folder" / "result.json"
    run_py = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
    env = {**os.environ, "HOME": str(tmp_path), "USERPROFILE": str(tmp_path), "PYTHONIOENCODING": "utf-8"}
    out = subprocess.run([sys.executable, str(run_py), "webtest-row", "--run", run_id, "--row", "r01",
                          "--result", str(missing)],
                         capture_output=True, text=True, encoding="utf-8", env=env, timeout=60)
    assert out.returncode == 2, out.stderr
    assert "FileNotFoundError" in out.stderr and "secret-folder" not in out.stderr and "Traceback" not in out.stderr


def test_a_hand_edited_real_device_row_for_the_agent_does_not_load(root, server):
    folder = folder_of(root, build(root, server))
    raw = json.loads((folder / "run.json").read_text(encoding="utf-8"))
    case = next(c for c in raw["cases"] if c["row"] == "r08")
    case.update({"runner": "agent", "state": "queued"})
    (folder / "run.json").write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(WebtestError, match="real device go to the tester"):
        webtest.load(folder)


@pytest.mark.parametrize("rows, message", [
    ({"r06": {"runner": "agent"}}, "not-web row"),
    ({"r01": {"class": "not-web", "runner": "tester"}}, "not-web row"),
    ({"r01": {"mobile_method": "emulation"}}, "pc row"),
])
def test_a_case_a_run_would_drop_is_refused(root, server, rows, message):
    with pytest.raises(WebtestError, match=message):
        build(root, server, rows_answer=rows)

