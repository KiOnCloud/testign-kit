"""Login Recipes, profiles and the secret guard. No browser."""

import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from testign import cli, login_recipe, login_scenarios, secret_guard

HOST = "dev.example.test"
SCENARIO = {"name": "member", "label": "Member", "login_url": f"https://{HOST}/login", "steps": ["Sign in"]}
RECIPE = {"profile": "member01", "login_url": f"https://{HOST}/login", "steps": [
    {"action": "goto", "value": f"https://{HOST}/login"},
    {"action": "fill", "locator": {"label": "User"}, "value": "{{username}}"},
    {"action": "fill", "locator": {"label": "Password"}, "value": "{{password}}"},
    {"action": "click", "locator": {"role": "button", "name": "Sign in"}},
    {"action": "wait_url", "value": f"https://{HOST}/mypage"},
]}
HOOK = Path(__file__).resolve().parents[1] / "hooks" / "secret_guard.py"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    login_scenarios.save_project(tmp_path, "demo", [HOST], ["sso.example.test"])
    login_scenarios.save_draft(tmp_path, "demo", SCENARIO)
    return tmp_path


def test_a_recipe_fills_placeholders_only_and_ends_in_a_check(home):
    bad = {**RECIPE, "steps": [{"action": "goto", "value": "https://evil.example/login"},
                               {"action": "fill", "locator": {"label": "Password"}, "value": "hunter2"},
                               {"action": "wait_url", "value": "**"},
                               {"action": "click", "locator": {"role": "button"}}]}
    with pytest.raises(login_recipe.RecipeError) as err:
        login_recipe.save(home, "demo", "member", bad)
    text = str(err.value)
    assert "goto needs a URL on the project's hosts" in text
    assert "never the value itself" in text and "hunter2" not in text
    assert "matches every page" in text
    assert "the last step must prove the sign-in worked" in text


def test_a_recipe_is_usable_after_a_profile_a_passing_test_and_the_testers_approval(home):
    view = login_recipe.save(home, "demo", "member", RECIPE)
    assert view["placeholders"] == ["password", "username"] and not view["usable"]
    assert view["missing_values"] == ["password", "username"] and not view["profile_set"]
    with pytest.raises(login_recipe.RecipeError, match="test the recipe first"):
        login_recipe.approve(home, "demo", "member", view["fingerprint"], "fp")
    login_recipe.set_profile(home, "demo", "member01", {"username": "u1", "password": "p@ss word"})
    login_recipe.store_test(home, "demo", "member", view["fingerprint"], {"ok": True})
    assert not login_recipe.view(home, "demo", "member")["usable"]
    with pytest.raises(login_recipe.RecipeError, match="changed since you opened it"):
        login_recipe.approve(home, "demo", "member", "0" * 64, "fp")
    approved = login_recipe.approve(home, "demo", "member", view["fingerprint"], "fp")
    assert approved["usable"] and approved["approved_by"] == "fp"
    assert "p@ss word" not in json.dumps(approved)
    # Saving the recipe again clears its test and approval.
    again = login_recipe.save(home, "demo", "member", {**RECIPE, "steps": RECIPE["steps"][:-1] +
                                                       [{"action": "wait_visible", "locator": {"text": "My Page"}}]})
    assert not again["tested"] and not again["approved"]


@pytest.mark.skipif(os.name != "posix", reason="mode bits only on POSIX")
def test_profiles_and_sessions_are_owner_only(home):
    login_recipe.set_profile(home, "demo", "member01", {"username": "u1"})
    path = login_recipe.profiles_dir(home) / "demo" / "member01.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE((login_recipe.profiles_dir(home) / "demo").stat().st_mode) == 0o700
    session = login_recipe.save_session(home, "demo", "member", {"cookies": [{"name": "sid"}], "origins": []})
    assert stat.S_IMODE(session.stat().st_mode) == 0o600
    assert login_recipe.list_profiles(home, "demo") == [{"profile": "member01", "keys": ["username"]}]


def test_profile_values_are_checked(home):
    with pytest.raises(login_recipe.RecipeError, match="one line"):
        login_recipe.set_profile(home, "demo", "p", {"password": "a\nb"})
    with pytest.raises(login_recipe.RecipeError, match="letters, digits"):
        login_recipe.set_profile(home, "demo", "p", {"pass word": "x"})
    with pytest.raises(login_recipe.RecipeError, match="not set"):
        login_recipe.profile_values(home, "demo", "nobody")


def test_profile_set_refuses_piped_input(home, capsys):
    rc = cli.main(["profile-set", "--project", "demo", "--profile", "p", "--key", "password"])
    assert rc == 2 and "own terminal" in capsys.readouterr().err
    assert login_recipe.list_profiles(home, "demo") == []


def test_redact_and_sign_in_page():
    assert login_recipe.redact("Error: filled p@ss into x\nmore", {"password": "p@ss"}) == "Error: filled [redacted] into x"
    assert login_recipe.same_page("https://h/login?next=/a", "https://h/login")
    assert not login_recipe.same_page("https://h/mypage", "https://h/login")


@pytest.mark.parametrize("payload, blocked", [
    ({"tool_name": "Read", "tool_input": {"file_path": "~/.testign-kit/webtest/profiles/demo/a.json"}}, True),
    ({"tool_name": "Edit", "tool_input": {"file_path": "~/.testign-kit/webtest/sessions/demo/member.json"}}, True),
    ({"tool_name": "Grep", "tool_input": {"pattern": "password", "path": "~/.testign-kit"}}, True),
    ({"tool_name": "Glob", "tool_input": {"pattern": "**/webtest/profiles/**"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "cat ~/.testign-kit/webtest/profiles/demo/a.json"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "python run.py profile-set --project d --profile p --key x"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "curl -X POST http://127.0.0.1:4791/api/webtest/login/d/m/recipe/approve"}}, True),
    ({"tool_name": "Bash", "tool_input": {"command": "python run.py login-recipe-test --project d --scenario m"}}, False),
    ({"tool_name": "Read", "tool_input": {"file_path": "~/.testign-kit/webtest/login/demo/member/recipe.json"}}, False),
    ({"tool_name": "Grep", "tool_input": {"pattern": "x", "path": "/usr/share"}}, False),
])
def test_secret_guard(home, payload, blocked):
    assert (secret_guard.evaluate(payload, home) is not None) is blocked


def test_secret_guard_hook_process(home):
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    payload = {"tool_name": "Bash", "tool_input": {"command": "cat ~/.testign-kit/webtest/sessions/demo/m.json"}}
    out = subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), text=True, capture_output=True, env=env)
    assert out.returncode == 2 and "Blocked by testign" in out.stderr
    out = subprocess.run([sys.executable, str(HOOK)], input="not json", text=True, capture_output=True, env=env)
    assert out.returncode == 0
