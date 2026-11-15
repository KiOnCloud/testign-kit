import json
import os
import subprocess
import sys
from pathlib import Path

from make_report import write_report

from testign import cache, cli, config, gitscope, report

REPO = Path(__file__).resolve().parent.parent
REGEX = config.DEFAULT_TICKET_ID_REGEX
ANCHORS = ["「確定」", "CalcTotal"]
SOURCES = ["src/screens/OrderConfirm.cs", "src/services/OrderService.cs", "db/sp_order_total.sql", "README.txt"]


def facts_for(repo, anchors=ANCHORS):
    return cli.scout_facts(str(repo.path), anchors, "master", "develop", REGEX, paths=SOURCES)


def brief_for(facts):
    h = facts["blob_hashes_at_merge_base"]
    b = lambda p: f"`{p}@{h[p][:8]}`"  # noqa: E731
    return (
        "---\nticket: DEMO-1\n---\n\n# Scout brief\n\n## 1. Production behavior (merge-base)\n\n"
        "| ID | Hành vi | Nguồn | Source files |\n|---|---|---|---|\n"
        f"| B1 | Nút 「確定」 | `[code]` | {b('src/screens/OrderConfirm.cs')} |\n"
        f"| B2 | Tổng tiền | `[code]` | {b('src/services/OrderService.cs')}, {b('src/screens/OrderConfirm.cs')} |\n"
        f"| B3 | SP tổng | `[suy luận]` | {b('db/sp_order_total.sql')} |\n"
        f"| B4 | README | `[code]` | {b('README.txt')} |\n\n"
        "## 2. Changes in this phase\n\n## 3. Coverage\n"
    )


def check(repo, home, anchors=ANCHORS, version="0.1.0"):
    facts = facts_for(repo, anchors)
    folder = cache.entry_dir(facts["refs"]["root_commit"], "注文確定", home)
    manifest, problem = cache.load(folder)
    hashes = gitscope.blob_hashes(str(repo.path), facts["refs"]["merge_base"], manifest["files"]) if manifest else {}
    return cache.decide(manifest, anchors, hashes, version, facts["refs"]["root_commit"], problem), folder, facts


def seed(repo, home):
    facts = facts_for(repo)
    folder = cache.entry_dir(facts["refs"]["root_commit"], "注文確定", home)
    cache.save(folder, brief_for(facts), facts, "注文確定")
    return folder


def advance_master(repo, path, text):
    """Commit on master and merge it into develop, so the merge-base moves to the new master."""
    target = repo.path / path
    target.write_text(text, encoding="utf-8")
    repo.git("add", "-A")
    repo.git("commit", "-q", "-m", "HOTFIX-11: production change")
    repo.git("checkout", "-q", "develop")
    repo.git("merge", "-q", "--no-edit", "master")
    repo.git("checkout", "-q", "master")


def test_no_cache_is_miss_then_saved(demo_repo, tmp_path):
    decision, folder, facts = check(demo_repo, tmp_path)
    assert decision["result"] == "miss" and decision["reason"] == "no cache entry"
    cache.save(folder, brief_for(facts), facts, "注文確定")
    manifest = json.loads((folder / cache.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["rows"]["B2"] == ["src/services/OrderService.cs", "src/screens/OrderConfirm.cs"]
    assert manifest["files"]["README.txt"] == facts["blob_hashes_at_merge_base"]["README.txt"]
    assert manifest["reviewed_by"] is None
    assert {"path": "db/sp_order_total.sql", "kind": "stored_procedure"} in manifest["unread"]


def test_scout_model_comes_from_the_skill_unless_forced(tmp_path):
    assert cache.scout_model({}) == "sonnet"
    assert cache.scout_model({"CLAUDE_CODE_SUBAGENT_MODEL": "haiku"}) == "sonnet"
    forced = {"CLAUDE_CODE_SUBAGENT_MODEL": "opus", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE": "1"}
    assert cache.scout_model(forced) == "opus (forced)"
    unpinned = tmp_path / "SKILL.md"
    unpinned.write_text("---\nname: scout\ncontext: fork\n---\n\nmodel: opus in the body is not frontmatter\n",
                        encoding="utf-8")
    assert cache.scout_model({}, unpinned) == "inherit"
    assert cache.scout_model({}, tmp_path / "missing.md") == "unknown"


def test_manifest_records_the_scout_model(demo_repo, tmp_path):
    facts = facts_for(demo_repo)
    folder = cache.entry_dir(facts["refs"]["root_commit"], "注文確定", tmp_path)
    assert cache.save(folder, brief_for(facts), facts, "注文確定", model="haiku (forced)")["scout_model"] == "haiku (forced)"
    manifest, problem = cache.load(folder)
    assert problem is None and manifest["scout_model"] == "haiku (forced)"


def test_nothing_changed_is_hit(demo_repo, tmp_path):
    seed(demo_repo, tmp_path)
    assert check(demo_repo, tmp_path)[0]["result"] == "hit"
    assert check(demo_repo, tmp_path, anchors=["CalcTotal"])[0]["result"] == "hit"


def test_one_source_changed_is_partial_with_only_its_rows(demo_repo, tmp_path):
    seed(demo_repo, tmp_path)
    advance_master(demo_repo, "README.txt", "changed in production\n")
    decision = check(demo_repo, tmp_path)[0]
    assert decision["result"] == "partial"
    assert decision["changed_files"] == ["README.txt"]
    assert decision["stale_rows"] == ["B4"]


def test_changed_file_never_hits(demo_repo, tmp_path):
    seed(demo_repo, tmp_path)
    advance_master(demo_repo, "src/screens/OrderConfirm.cs", "rewritten\n")
    decision = check(demo_repo, tmp_path)[0]
    assert decision["result"] != "hit"
    assert set(decision["stale_rows"]) == {"B1", "B2"}


def test_most_files_changed_is_miss(demo_repo, tmp_path):
    seed(demo_repo, tmp_path)
    for path in ("src/screens/OrderConfirm.cs", "db/sp_order_total.sql"):  # not touched on develop, so no conflict
        (demo_repo.path / path).write_text("rewritten\n", encoding="utf-8")
    advance_master(demo_repo, "README.txt", "rewritten\n")
    assert check(demo_repo, tmp_path)[0]["reason"] == "most source files changed"


def test_new_anchor_is_partial(demo_repo, tmp_path):
    seed(demo_repo, tmp_path)
    decision = check(demo_repo, tmp_path, anchors=[*ANCHORS, "TaxRate"])[0]
    assert decision["result"] == "partial" and decision["new_anchors"] == ["TaxRate"]
    assert decision["stale_rows"] == []


def test_plugin_major_bump_is_miss(demo_repo, tmp_path):
    seed(demo_repo, tmp_path)
    assert check(demo_repo, tmp_path, version="1.0.0")[0]["reason"] == "plugin major version changed"
    assert check(demo_repo, tmp_path, version="0.9.0")[0]["result"] == "hit"


def test_other_clone_shares_the_cache_dir(demo_repo, tmp_path):
    folder = seed(demo_repo, tmp_path)
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(demo_repo.path), str(clone)], check=True)
    root = gitscope.root_commit(str(clone), "origin/master")
    assert cache.entry_dir(root, "注文確定", tmp_path) == folder


def test_corrupt_manifest_is_miss(demo_repo, tmp_path):
    folder = seed(demo_repo, tmp_path)
    (folder / cache.MANIFEST).write_text("{broken", encoding="utf-8")
    decision = check(demo_repo, tmp_path)[0]
    assert decision["result"] == "miss" and "unreadable" in decision["reason"]


def test_malformed_manifests_are_miss_not_crash(demo_repo, tmp_path):
    folder = seed(demo_repo, tmp_path)
    good = json.loads((folder / cache.MANIFEST).read_text(encoding="utf-8"))
    bad_manifests = [
        b"\xff\xfe not utf-8",
        json.dumps({**good, "anchors": 5}).encode(),
        json.dumps({**good, "rows": []}).encode(),
        json.dumps({**good, "files": {}}).encode(),
        json.dumps([1, 2]).encode(),
    ]
    for raw in bad_manifests:
        (folder / cache.MANIFEST).write_bytes(raw)
        decision = check(demo_repo, tmp_path)[0]
        assert decision["result"] == "miss", raw


def test_brief_written_without_its_manifest_is_miss(demo_repo, tmp_path):
    folder = seed(demo_repo, tmp_path)
    (folder / cache.BRIEF).write_text("a newer brief whose manifest was never written\n", encoding="utf-8")
    decision = check(demo_repo, tmp_path)[0]
    assert decision["result"] == "miss" and "does not match" in decision["reason"]


def test_rows_without_sources_are_not_cached(demo_repo, tmp_path):
    facts = facts_for(demo_repo)
    brief = brief_for(facts).replace("| B4 | README | `[code]` |", "| B5 | Không nguồn | `[code]` | |\n| B4 | README | `[code]` |")
    folder = cache.entry_dir(facts["refs"]["root_commit"], "x", tmp_path)
    try:
        cache.save(folder, brief, facts, "x")
    except ValueError as exc:
        assert "B5" in str(exc)
    else:
        raise AssertionError("expected ValueError")
    assert not (folder / cache.MANIFEST).exists()


def run_cli(*args, home, **extra_env):
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    for name in ("CLAUDE_CODE_SUBAGENT_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL_FORCE"):
        env.pop(name, None)
    env.update(extra_env)
    return subprocess.run([sys.executable, str(REPO / "scripts" / "run.py"), *args],
                          capture_output=True, text=True, encoding="utf-8", env=env)


def test_cli_check_save_and_review_after_close(demo_repo, tmp_path):
    home = tmp_path / "home"
    anchors = tmp_path / "anchors.json"
    anchors.write_text(json.dumps({"anchors": ANCHORS, "paths": SOURCES}, ensure_ascii=False), encoding="utf-8")
    first = json.loads(run_cli("cache-check", "--repo", str(demo_repo.path), "--feature", "注文確定",
                               "--anchors-file", str(anchors), home=home).stdout)
    assert first["result"] == "miss" and first["brief"] is None

    facts_path, brief_path = tmp_path / "facts.json", tmp_path / "brief.md"
    assert run_cli("scout-facts", "--repo", str(demo_repo.path), "--anchors-file", str(anchors),
                   "--out", str(facts_path), home=home).returncode == 0
    brief_path.write_text(brief_for(json.loads(facts_path.read_text(encoding="utf-8"))), encoding="utf-8")
    saved = run_cli("cache-save", "--feature", "注文確定", "--brief", str(brief_path), "--facts", str(facts_path), home=home)
    assert saved.returncode == 0, saved.stderr

    hit = json.loads(run_cli("cache-check", "--repo", str(demo_repo.path), "--feature", "注文確定",
                             "--anchors-file", str(anchors), home=home).stdout)
    assert hit["result"] == "hit" and Path(hit["brief"]).exists()
    assert json.loads(saved.stdout)["scout_model"] == "sonnet" and hit["scout_model"] == "sonnet"

    folder = Path(hit["cache_dir"])
    before = ((folder / cache.BRIEF).read_bytes(), json.loads((folder / cache.MANIFEST).read_text(encoding="utf-8"))["files"])
    rpt = write_report(tmp_path / "reports", demo_repo.path, "d" * 40, "b" * 40)
    meta, body = report.load(rpt)
    rpt.write_text(report.join({**meta, "cache_root": hit["cache_root"], "cache_feature": hit["cache_feature"]}, body),
                   encoding="utf-8")
    reviewed = run_cli("cache-review", "--report", str(rpt), "--by", "Asher", home=home)
    assert reviewed.returncode == 0, reviewed.stderr
    manifest = json.loads((folder / cache.MANIFEST).read_text(encoding="utf-8"))
    assert manifest["reviewed_by"]["name"] == "Asher"
    assert ((folder / cache.BRIEF).read_bytes(), manifest["files"]) == before
