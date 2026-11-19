import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from testign import login_scenarios as ls
from testign.webtest import WebtestError

RUN_PY = Path(__file__).resolve().parent.parent / "scripts" / "run.py"
DRAFT = {"name": "member", "label": "Member", "login_url": "https://auth.example.test/login",
         "signout_url": "https://dev.example.test/logout", "steps": ["Open the login page", "Sign in as a member"],
         "signed_in_check": {"url": "https://dev.example.test/mypage", "text": "My Page"},
         "account_hint": "any member account on dev"}


@pytest.fixture
def home(tmp_path):
    ls.save_project(tmp_path, "demo", ["dev.example.test"], ["auth.example.test"])
    return tmp_path


def run_cli(home, *args):
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home), "PYTHONIOENCODING": "utf-8"}
    return subprocess.run([sys.executable, str(RUN_PY), *args], capture_output=True, text=True, encoding="utf-8",
                          env=env, timeout=60)


def test_saved_draft_is_unapproved_until_the_tester_approves_its_hash(home):
    view = ls.save_draft(home, "demo", DRAFT)
    assert view["approved"] is False and view["hash"]
    approved = ls.approve(home, "demo", "member", view["hash"], "fp")
    assert approved["approved"] is True and ls.is_approved(home, "demo", "member")
    again = ls.save_draft(home, "demo", {**DRAFT, "label": "Member (new)"})
    assert again["approved"] is False and not ls.is_approved(home, "demo", "member")


def test_approval_for_an_older_hash_is_a_conflict(home):
    old = ls.save_draft(home, "demo", DRAFT)["hash"]
    ls.save_draft(home, "demo", {**DRAFT, "steps": ["Sign in"]})
    with pytest.raises(ls.Conflict):
        ls.approve(home, "demo", "member", old, "fp")


@pytest.mark.parametrize("change,message", [
    ({"login_url": "https://evil.example/login"}, "login_url"),
    ({"signout_url": "javascript:alert(1)"}, "signout_url"),
    ({"signed_in_check": {"url": "https://auth.example.test/me", "text": ""}}, "signed_in_check"),
    ({"password": "x"}, "unknown"),
    ({"account": "a"}, "unknown"),
    ({"steps": ["a\nb"]}, "one line"),
    ({"steps": ["s"] * 21}, "up to 20"),
    ({"name": "none"}, "built in"),
    ({"name": "../x"}, "lowercase"),
    ({"name": "con"}, "lowercase"),
])
def test_bad_drafts_are_refused(home, change, message):
    with pytest.raises(WebtestError, match=message):
        ls.save_draft(home, "demo", {**DRAFT, **change})


def test_the_store_has_no_field_for_an_account_value():
    assert not {k for k in ls.SCENARIO_KEYS if any(w in k for w in ("password", "secret", "token", "code", "user"))}


def test_reject_keeps_a_note_and_removes_the_approval(home):
    digest = ls.save_draft(home, "demo", DRAFT)["hash"]
    ls.approve(home, "demo", "member", digest, "fp")
    view = ls.reject(home, "demo", "member", "the login page is on another host", "fp")
    assert view["approved"] is False and view["rejection"]["note"].startswith("the login page")
    assert ls.save_draft(home, "demo", DRAFT)["rejection"] is None  # a new draft clears the note


def test_remove_takes_the_approval_with_it(home):
    digest = ls.save_draft(home, "demo", DRAFT)["hash"]
    ls.approve(home, "demo", "member", digest, "fp")
    ls.remove(home, "demo", "member")
    assert ls.list_scenarios(home, "demo") == []
    ls.save_draft(home, "demo", DRAFT)
    assert not ls.is_approved(home, "demo", "member")


def test_none_is_built_in_and_always_approved(home):
    assert ls.get_scenario(home, "demo", "none")["approved"] is True


@pytest.mark.parametrize("name", ["..", "a/b", "a\\b", "%2e%2e", "NUL", "com1", ""])
def test_unknown_or_traversing_names_are_not_found(home, name):
    ls.save_draft(home, "demo", DRAFT)
    with pytest.raises(WebtestError):
        ls.get_scenario(home, "demo", name)
    with pytest.raises(WebtestError):
        ls.list_scenarios(home, name)


@pytest.mark.skipif(os.name != "posix", reason="mode bits apply on POSIX only")
def test_store_is_owner_only(home):
    ls.save_draft(home, "demo", DRAFT)
    root = ls.store_dir(home)
    for folder in (root, root / "login", root / "login" / "demo", root / "login" / "demo" / "member"):
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700, folder
    assert stat.S_IMODE((root / "projects.json").stat().st_mode) == 0o600


def test_projects_need_valid_hosts(tmp_path):
    with pytest.raises(WebtestError):
        ls.save_project(tmp_path, "demo", [])
    with pytest.raises(WebtestError):
        ls.save_project(tmp_path, "demo", ["https://dev.example.test/"])
    assert ls.save_project(tmp_path, "demo", ["DEV.example.test"])["hosts"] == ["dev.example.test"]


def test_cli_saves_lists_and_removes_but_never_writes_hosts(home, tmp_path):
    draft = tmp_path / "draft.json"
    draft.write_text(json.dumps(DRAFT), encoding="utf-8")
    before = (ls.store_dir(home) / "projects.json").read_bytes()
    out = run_cli(home, "login-scenario-save", "--project", "demo", "--file", str(draft))
    assert out.returncode == 0, out.stderr
    assert json.loads(out.stdout)["approved"] is False
    listed = json.loads(run_cli(home, "login-scenario-list", "--project", "demo").stdout)
    assert [s["name"] for s in listed["scenarios"]] == ["member"]
    assert run_cli(home, "login-scenario-remove", "--project", "demo", "--name", "member").returncode == 0
    bad = run_cli(home, "login-scenario-save", "--project", "other", "--file", str(draft))
    assert bad.returncode == 2 and "project" in bad.stderr
    assert (ls.store_dir(home) / "projects.json").read_bytes() == before
    from testign import cli  # noqa: PLC0415

    sub = next(a for a in cli.build_parser()._actions if a.dest == "command")
    assert "login-scenario-save" in sub.choices
    assert not [name for name in sub.choices if "project" in name or "host" in name]
