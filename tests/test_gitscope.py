import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from make_repo import JP_DOC

from testign import cli, config, gitscope

REPO = Path(__file__).resolve().parent.parent
REGEX = config.DEFAULT_TICKET_ID_REGEX


def paths_of(entries):
    return {e["path"] for e in entries}


def test_merge_base_is_branch_point_not_master_head(demo_repo):
    base = gitscope.merge_base(str(demo_repo.path), "master", "develop")
    assert base == demo_repo.commits["B"]
    assert base != gitscope.resolve_ref(str(demo_repo.path), "master")


def test_three_dot_diff_hides_unmerged_hotfix_two_dot_shows_it(demo_repo):
    repo = str(demo_repo.path)
    three = gitscope.diff_name_status(repo, "master", "develop")
    two = gitscope.diff_name_status(repo, "master", "develop", three_dot=False)
    assert "src/hotfix/Patch.cs" not in paths_of(three)
    removed = {e["path"] for e in two if e["status"] == "D"}
    assert "src/hotfix/Patch.cs" in removed


def test_commits_grouped_by_ticket(demo_repo):
    c = demo_repo.commits
    groups = gitscope.commits_by_ticket(str(demo_repo.path), c["B"], "develop", REGEX)
    assert [x["sha"] for x in groups["DEMO-1"]] == [c["D1"]]
    assert [x["sha"] for x in groups["DEMO-2"]] == [c["D2"]]
    assert [x["sha"] for x in groups[gitscope.UNLINKED]] == [c["U"]]
    assert "HOTFIX-9" not in groups


def test_anchor_grep_at_merge_base_and_develop(demo_repo):
    base = demo_repo.commits["B"]
    hits = {
        h["anchor"]: h
        for h in gitscope.grep_anchors(str(demo_repo.path), base, "develop", ["「確定」", "ポイント利用", "存在しない"])
    }
    confirm = hits["「確定」"]
    assert confirm["status"] == "production"
    assert confirm["merge_base"][0]["path"] == "src/screens/OrderConfirm.cs"
    assert confirm["merge_base"][0]["line"] == 6
    point = hits["ポイント利用"]
    assert point["status"] == "new_in_phase"
    assert point["merge_base"] == []
    assert paths_of(point["develop"]) == {"src/screens/PointScreen.cs", JP_DOC}
    assert hits["存在しない"]["status"] == "not_found"


def test_develop_scope_by_terms(demo_repo):
    repo = str(demo_repo.path)
    scoped = ["src/screens/OrderConfirm.cs", "src/services/"]
    res = gitscope.changed_files(repo, "master", "develop", scoped, ["CalcTotal"])
    kept = {e["path"]: e for e in res["kept"]}
    assert kept["src/services/OrderService.cs"]["reason"] == "scoped_path"
    assert kept["src/reports/Invoice.cs"]["reason"] == "term"
    assert kept["src/reports/Invoice.cs"]["matched_terms"] == ["CalcTotal"]
    assert "src/util/Format.cs" in paths_of(res["dropped"])

    without = gitscope.changed_files(repo, "master", "develop", scoped, [])
    assert "src/reports/Invoice.cs" in paths_of(without["dropped"])


def test_refs_as_shas_give_same_result(demo_repo):
    repo = str(demo_repo.path)
    master_sha = gitscope.resolve_ref(repo, "master")
    develop_sha = gitscope.resolve_ref(repo, "develop")
    by_name = cli.scout_facts(repo, ["「確定」"], "master", "develop", REGEX, symbols=["CalcTotal"])
    by_sha = cli.scout_facts(repo, ["「確定」"], master_sha, develop_sha, REGEX, symbols=["CalcTotal"])
    for key in ("anchors", "scoped_paths", "blob_hashes_at_merge_base", "changed_files", "commits_by_ticket", "unreadable"):
        assert by_name[key] == by_sha[key], key
    assert by_name["refs"]["merge_base"] == by_sha["refs"]["merge_base"]
    assert by_sha["refs"]["develop_head"] == develop_sha


def test_short_sha_resolves_to_full(demo_repo):
    full = demo_repo.commits["B"]
    assert gitscope.resolve_ref(str(demo_repo.path), full[:8]) == full


def test_unreadable_classification():
    flagged = {
        f["path"]: f["kind"]
        for f in gitscope.classify_unreadable(
            [
                "db/sp_order_total.sql",
                "config/app.config",
                "src/appsettings.Production.json",
                "batch/nightly_close.bat",
                "data/masterdata/prefectures.csv",
                "src/services/OrderService.cs",
            ]
        )
    }
    assert flagged == {
        "db/sp_order_total.sql": "stored_procedure",
        "config/app.config": "config",
        "src/appsettings.Production.json": "config",
        "batch/nightly_close.bat": "batch",
        "data/masterdata/prefectures.csv": "master_data",
    }


def test_blob_hashes_match_rev_parse(demo_repo):
    repo = str(demo_repo.path)
    base = demo_repo.commits["B"]
    wanted = ["src/services/OrderService.cs", JP_DOC, "src/screens/PointScreen.cs"]
    hashes = gitscope.blob_hashes(repo, base, wanted)
    for path in wanted[:2]:
        assert hashes[path] == demo_repo.git("rev-parse", f"{base}:{path}").strip()
    assert hashes["src/screens/PointScreen.cs"] is None


def test_jp_path_round_trip(demo_repo):
    repo = str(demo_repo.path)
    kept = gitscope.changed_files(repo, "master", "develop", [], ["ポイント利用"])["kept"]
    assert JP_DOC in paths_of(kept)
    assert JP_DOC in gitscope.blob_hashes(repo, demo_repo.commits["B"], [JP_DOC])


def test_working_tree_untouched(demo_repo):
    repo = str(demo_repo.path)
    (demo_repo.path / "scratch.txt").write_text("local edit\n", encoding="utf-8")

    def snapshot():
        return (
            demo_repo.git("rev-parse", "HEAD"),
            demo_repo.git("symbolic-ref", "HEAD"),
            demo_repo.git("status", "--porcelain=v1"),
            demo_repo.git("for-each-ref"),
        )

    before = snapshot()
    cli.scout_facts(repo, ["「確定」", "ポイント利用"], "master", "develop", REGEX, symbols=["CalcTotal"])
    assert snapshot() == before


def test_scout_facts_flags_unreadable_and_new_anchor(demo_repo):
    facts = cli.scout_facts(
        str(demo_repo.path),
        ["「確定」", "TaxRate", "ポイント利用"],
        "master",
        "develop",
        REGEX,
        symbols=["CalcTotal"],
    )
    assert facts["refs"]["root_commit"] == demo_repo.commits["A"]
    assert "config/app.config" in facts["scoped_paths"]
    assert {"path": "config/app.config", "kind": "config"} in facts["unreadable"]
    statuses = {a["anchor"]: a["status"] for a in facts["anchors"]}
    assert statuses["ポイント利用"] == "new_in_phase"
    assert facts["blob_hashes_at_merge_base"]["src/screens/OrderConfirm.cs"]


def run_cli(*args, home):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    return subprocess.run(
        [sys.executable, str(REPO / "scripts" / "run.py"), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


def test_cli_writes_facts_file(demo_repo, tmp_path):
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"anchors": ["「確定」"], "symbols": ["CalcTotal"]}, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out" / "facts.json"
    proc = run_cli("scout-facts", "--repo", str(demo_repo.path), "--anchors-file", str(anchors), "--out", str(out), home=tmp_path)
    assert proc.returncode == 0, proc.stderr
    facts = json.loads(out.read_text(encoding="utf-8"))
    assert facts["anchors"][0]["anchor"] == "「確定」"
    assert facts["refs"]["merge_base"] == demo_repo.commits["B"]


def test_missing_ref_gives_clear_error(demo_repo, tmp_path):
    demo_repo.git("branch", "-D", "develop")
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"anchors": ["x"]}), encoding="utf-8")
    proc = run_cli("scout-facts", "--repo", str(demo_repo.path), "--anchors-file", str(anchors), home=tmp_path)
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
    assert "ref 'develop' not found" in proc.stderr


@pytest.mark.parametrize("content", ["{}", '{"anchors": []}', "not json"])
def test_bad_anchors_file_gives_clear_error(demo_repo, tmp_path, content):
    anchors = tmp_path / "anchors.json"
    anchors.write_text(content, encoding="utf-8")
    proc = run_cli("scout-facts", "--repo", str(demo_repo.path), "--anchors-file", str(anchors), home=tmp_path)
    assert proc.returncode == 2
    assert "Traceback" not in proc.stderr
