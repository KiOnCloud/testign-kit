import json
from datetime import datetime
from pathlib import Path

import pytest

openpyxl = pytest.importorskip("openpyxl")

from make_report import write_report  # noqa: E402

from testign import templates, webtest_sources, webtest_suite as ws, xlsx  # noqa: E402
from testign.webtest import WebtestError  # noqa: E402
from testign.webtest_suite import CaseError  # noqa: E402

FIGMA = "https://www.figma.com/design/AbCdEfGhIjKlMn/USUPP?node-id=6647-118148"
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32
WHEN = datetime(2026, 11, 25, 10, 0)


@pytest.fixture
def env(tmp_path):
    return webtest_sources.Env(tmp_path / "out", tmp_path)


@pytest.fixture
def root(env):
    return env.output_dir / "webtest"


@pytest.fixture
def survey(env, tmp_path):
    return write_report(env.output_dir / "DEMO-1", tmp_path, "a" * 40, "b" * 40, revision=2)


def manual(root, env, name="Login regression"):
    made = ws.new_suite(root, name=name, kind="manual", payload={}, env=env, project="usupp", when=WHEN)
    return ws.find_suite(root, made["id"])


def agent_case(**extra):
    return {"content": "Label shows 確定", "class": "sure", "runner": "agent", "scenario": "staff",
            "screen": "/office/edit", "kind": "label", **extra}


def test_manual_suite_starts_empty_in_review(root, env):
    folder = manual(root, env)
    suite = ws.load(folder)
    assert folder.name == "S20261125-1000-login-regression"
    assert suite["state"] == "review" and suite["cases"] == [] and suite["project"] == "usupp"
    assert ws.list_suites(root) == {folder.name: folder}


def test_suite_ids_never_clash_and_are_not_runs(root, env):
    first = manual(root, env, "Same")
    second = manual(root, env, "Same")
    assert first.name != second.name and second.name.endswith("-2")
    from testign import webtest
    assert webtest.list_runs(root) == {}
    with pytest.raises(WebtestError):
        ws.find_suite(root, "../x")


def test_japanese_name_gets_a_neutral_slug(root, env):
    assert manual(root, env, "小多機 チェックシート").name.endswith("-suite")


def test_case_edits_and_ready_goes_back_to_review(root, env):
    folder = manual(root, env)
    added = ws.add_case(folder, agent_case())
    assert added["case"]["case"] == "c1" and added["case"]["creator"] == "tester"
    assert added["case"]["screen"] == {"url": "/office/edit", "name": "", "confidence": "high"}
    confirmed = ws.confirm(folder, "Kien")
    assert confirmed["state"] == "ready" and len(confirmed["suite_digest"]) == 64
    ws.update_case(folder, "c1", {"expected": "確定 is shown"})
    suite = ws.load(folder)
    assert suite["state"] == "review" and suite["suite_digest"] is None
    assert suite["cases"][0]["expected"] == "確定 is shown"


def test_per_case_rules_return_field_errors(root, env):
    folder = manual(root, env)
    with pytest.raises(CaseError) as err:
        ws.add_case(folder, agent_case(viewport="mobile"))  # a phone check defaults to a real device
    assert err.value.errors == {"runner": ws.DEVICE_IS_THE_TESTERS}
    with pytest.raises(CaseError) as err:
        ws.add_case(folder, agent_case(**{"class": "choice"}))
    assert set(err.value.errors) == {"preconditions"}
    with pytest.raises(CaseError) as err:
        ws.add_case(folder, agent_case(mobile_method="emulation"))
    assert err.value.errors == {"mobile_method": "a pc row has no phone check method"}
    with pytest.raises(CaseError) as err:
        ws.add_case(folder, agent_case(screen="https://elsewhere.example/x", viewport="tablet"))
    assert set(err.value.errors) == {"screen", "viewport"}
    ok = ws.add_case(folder, agent_case(viewport="mobile", mobile_method="emulation"))["case"]
    assert ok["mobile_method"] == "emulation"
    not_web = ws.add_case(folder, {"content": "batch", "class": "not-web"})["case"]
    assert not_web["runner"] == "none"


def test_agent_may_not_delegate_a_choice_or_pick_emulation(root, env):
    folder = ws.find_suite(root, ws.new_suite(root, name="Figma", kind="figma", payload={"figma_url": FIGMA},
                                              env=env, when=WHEN)["id"])
    ws.attach_job(folder, "j1")
    with pytest.raises(CaseError) as err:
        ws.stage_generated(folder, [agent_case(**{"class": "choice", "preconditions": "x"})], "j1")
    assert err.value.errors == {"runner": ws.CHOICE_BY_AGENT}
    with pytest.raises(CaseError):
        ws.stage_generated(folder, [agent_case(viewport="mobile", mobile_method="emulation")], "j1")
    with pytest.raises(WebtestError, match="does not generate"):
        ws.stage_generated(folder, [agent_case()], "j2")


def test_confirm_refuses_incomplete_cases(root, env):
    folder = manual(root, env)
    with pytest.raises(WebtestError, match="at least one case"):
        ws.confirm(folder)
    ws.add_case(folder, {"content": "no class yet"})
    ws.add_case(folder, agent_case(screen=None))
    with pytest.raises(CaseError) as err:
        ws.confirm(folder)
    assert err.value.problems == {"c1": {"class": "is required"},
                                  "c2": {"screen": "an agent case needs a screen path"}}
    assert ws.load(folder)["state"] == "review"


def test_delete_and_bulk_update(root, env):
    folder = manual(root, env)
    for n in range(3):
        ws.add_case(folder, {"content": f"case {n}", "class": "sure", "runner": "tester"})
    assert ws.bulk_update(folder, ["c1", "c3"], {"runner": "agent", "scenario": "staff"})["changed"] == ["c1", "c3"]
    cases = {c["case"]: c for c in ws.load(folder)["cases"]}
    assert cases["c1"]["runner"] == "agent" and cases["c2"]["runner"] == "tester"
    with pytest.raises(CaseError):
        ws.bulk_update(folder, ["c2"], {"class": "choice", "runner": "agent"})
    with pytest.raises(WebtestError, match="class, runner or scenario"):
        ws.bulk_update(folder, ["c2"], {"content": "x"})
    ws.delete_cases(folder, ["c2"])
    assert [c["case"] for c in ws.load(folder)["cases"]] == ["c1", "c3"]
    assert ws.add_case(folder, {"content": "next"})["case"]["case"] == "c4"


def test_backlog_suite_generates_and_reports_coverage(root, env, survey):
    made = ws.new_suite(root, name="DEMO-1 order", kind="backlog", payload={"ticket": "DEMO-1"}, env=env, when=WHEN)
    folder = ws.find_suite(root, made["id"])
    assert made["state"] == "generating" and made["source"]["report"] == "DEMO-1-survey-r2.md"
    with pytest.raises(WebtestError, match="still writing"):
        ws.add_case(folder, agent_case())
    ws.attach_job(folder, "j1")
    staged = ws.stage_generated(folder, [agent_case(trace=["B1"]), agent_case(trace="B2, R1"),
                                         {"content": "batch only", "class": "not-web", "trace": ["B9"]}], "j1")
    assert staged["staged"] == ["c1", "c2", "c3"]
    ws.stage_generated(folder, [{"case": "c1", "expected": "updated"}], "j1")
    assert ws.finish_generate(folder, "j1")["state"] == "review"
    shown = ws.show(folder, env)
    cov = shown["coverage"]
    assert cov["uncovered"] == ["B3", "R2"] and cov["orphans"] == ["c3"]
    assert {r["id"]: r["cases"] for r in cov["rows"]}["B2"] == ["c2"]
    assert shown["cases"][0]["expected"] == "updated" and shown["cases"][0]["creator"] == "agent"


def test_stop_generating_keeps_what_was_staged(root, env, survey):
    folder = ws.find_suite(root, ws.new_suite(root, name="x", kind="backlog", payload={"ticket": "DEMO-1"},
                                              env=env, when=WHEN)["id"])
    ws.attach_job(folder, "j1")
    with pytest.raises(WebtestError, match="no case was staged"):
        ws.finish_generate(folder, "j1")
    with pytest.raises(WebtestError, match="already generated"):
        ws.attach_job(folder, "j2")
    assert ws.stop_generating(folder)["state"] == "review"


def test_figma_rows_are_staged_with_captures(root, env, tmp_path):
    folder = ws.find_suite(root, ws.new_suite(root, name="Figma", kind="figma", payload={"figma_url": FIGMA},
                                              env=env, when=WHEN)["id"])
    ws.attach_job(folder, "j1")
    rows = [{"row": f"r0{n}", "source": {"kind": "figma", "file": "AbCdEfGhIjKlMn", "table_node": "1:1",
                                        "row_node": f"2:{n}", "target_node": f"3:{n}", "no": str(n)},
             "type": "Label", "content": f"row {n}", "creator": "Designer", "capture_url": "https://x/a.png" if n == 1
             else None, "numbered_by": "no"} for n in (2, 1)]
    todo = ws.stage_rows(folder, rows, None, "j1")
    assert [r["row"] for r in todo["rows"]] == ["r02", "r01"]
    caps = tmp_path / "caps"
    caps.mkdir()
    with pytest.raises(WebtestError, match="no capture for r01"):
        ws.stage_rows(folder, rows, caps, "j1")
    (caps / "r01.png").write_bytes(PNG)
    done = ws.stage_rows(folder, rows, caps, "j1")
    assert done["total"] == 2
    suite = ws.load(folder)
    assert [c["source"]["no"] for c in suite["cases"]] == ["1", "2"]
    first = suite["cases"][0]
    assert first["capture"] == f"source/{first['case']}.png" and first["creator"] == "Designer"
    assert first["source"] == {"table_node": "1:1", "row_node": "2:1", "target_node": "3:1", "no": "1"}
    assert ws.stage_rows(folder, rows, caps, "j1")["skipped"] == ["r02", "r01"]
    assert ws.capture_path(folder, f"{first['case']}.png").read_bytes() == PNG
    with pytest.raises(WebtestError):
        ws.capture_path(folder, "../suite.json")


def test_excel_suite_is_read_now_without_the_agent(root, env, tmp_path):
    templates.register(xlsx.build_sample(tmp_path / "src" / "sample.xlsx"), "sample", home=tmp_path)
    entry = templates.resolve("sample", tmp_path)
    filled = xlsx.fill_copy(Path(entry["path"]), entry, [
        {"item": "Label", "steps": "1. open", "expected": "shown", "trace": ["B1"]},
        {"item": "Total", "steps": "", "expected": "sum", "trace": ["R1"]}], tmp_path / "filled.xlsx")
    made = ws.new_suite(root, name="v118", kind="excel", payload={"file_name": "v118 cases.xlsx",
                                                                  "template": "sample"},
                        env=env, upload=Path(filled["path"]), when=WHEN)
    assert made["state"] == "review" and made["cases"][0]["content"] == "Label"
    assert made["cases"][1]["source"] == {"no": "2"} and made["cases"][1]["trace"] == ["R1"]
    folder = ws.find_suite(root, made["id"])
    assert (folder / "source" / "v118-cases.xlsx").is_file()
    with pytest.raises(WebtestError, match="needs its file"):
        ws.new_suite(root, name="x", kind="excel", payload={"file_name": "a.xlsx", "template": "sample"}, env=env)


def test_failed_excel_read_leaves_no_folder(root, env, tmp_path):
    templates.register(xlsx.build_sample(tmp_path / "src" / "sample.xlsx"), "sample", home=tmp_path)
    empty = Path(templates.resolve("sample", tmp_path)["path"])
    with pytest.raises(webtest_sources.SourceError, match="no test case rows"):
        ws.new_suite(root, name="x", kind="excel", payload={"file_name": "a.xlsx", "template": "sample"},
                     env=env, upload=empty)
    assert ws.list_suites(root) == {}


def test_duplicate_rename_and_remove(root, env):
    folder = manual(root, env)
    ws.add_case(folder, agent_case())
    ws.confirm(folder)
    copy = ws.duplicate(root, folder, when=WHEN)
    assert copy["state"] == "review" and copy["name"] == "Login regression (copy)" and copy["cases"] == 1
    assert ws.rename(folder, "Login v2", project=None)["project"] is None
    with pytest.raises(WebtestError, match="still open"):
        ws.remove(folder, ["W20261125-1000-x"])
    assert ws.remove(folder, [])["removed"] and not folder.exists()


def test_a_tampered_suite_file_is_refused(root, env):
    folder = manual(root, env)
    ws.add_case(folder, agent_case())
    data = json.loads((folder / "suite.json").read_text(encoding="utf-8"))
    data["cases"][0]["capture"] = "../../secret.png"
    (folder / "suite.json").write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(WebtestError, match="capture"):
        ws.load(folder)
