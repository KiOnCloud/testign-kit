from make_report import write_report

from testign import gitscope, hashcheck


def pin(demo_repo, tmp_path):
    repo = str(demo_repo.path)
    head = gitscope.resolve_ref(repo, "develop")
    base = gitscope.merge_base(repo, "master", "develop")
    return write_report(tmp_path / "reports", demo_repo.path, head, base)


def commit_on(demo_repo, branch, path, text, message):
    demo_repo.git("checkout", "-q", branch)
    target = demo_repo.path / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")
    demo_repo.git("add", "-A")
    demo_repo.git("commit", "-q", "-m", message)
    demo_repo.git("checkout", "-q", "master")


def test_same_refs(demo_repo, tmp_path):
    assert hashcheck.check(str(pin(demo_repo, tmp_path)))["status"] == "same"


def test_develop_moved_touching_report_source_is_stale(demo_repo, tmp_path):
    rpt = pin(demo_repo, tmp_path)
    commit_on(demo_repo, "develop", "src/services/OrderService.cs", "changed\n", "DEMO-3: rewrite total")
    res = hashcheck.check(str(rpt))
    assert res["status"] == "stale"
    assert res["stale_files"] == ["src/services/OrderService.cs"]
    assert res["stale_rows"] == ["B2", "R1"]
    assert res["moves"][0]["ref"] == "develop_head"
    assert res["moves"][0]["commits"][0]["subject"] == "DEMO-3: rewrite total"


def test_develop_moved_elsewhere_warns_only(demo_repo, tmp_path):
    rpt = pin(demo_repo, tmp_path)
    commit_on(demo_repo, "develop", "src/other/Unrelated.cs", "x\n", "DEMO-4: unrelated")
    res = hashcheck.check(str(rpt))
    assert res["status"] == "moved_no_impact"
    assert res["stale_rows"] == []


def test_merge_base_moved_by_merged_hotfix_is_stale(demo_repo, tmp_path):
    rpt = pin(demo_repo, tmp_path)
    commit_on(demo_repo, "master", "src/screens/OrderConfirm.cs", "hotfixed\n", "HOTFIX-10: confirm button")
    demo_repo.git("checkout", "-q", "develop")
    demo_repo.git("merge", "-q", "--no-edit", "master")
    demo_repo.git("checkout", "-q", "master")
    res = hashcheck.check(str(rpt))
    assert res["status"] == "stale"
    moved = {m["ref"]: m for m in res["moves"]}
    assert "merge_base" in moved
    assert res["current"]["merge_base"] == gitscope.resolve_ref(str(demo_repo.path), "master")
    assert "src/screens/OrderConfirm.cs" in moved["merge_base"]["changed_files"]
    assert "B1" in res["stale_rows"]
