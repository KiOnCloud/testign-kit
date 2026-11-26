"""Tests for the git write guard (scripts/testign/git_guard.py and hooks/git_guard.py).

The shell parsing cases come from qingyi-test-kit's source-control hook; testign adds the guard list
(only listed repositories are protected) and blocks checkout, switch and new branches outright.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / "hooks" / "git_guard.py"
sys.path.insert(0, str(ROOT / "scripts"))

from testign import git_guard as hook  # noqa: E402


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    _git(path, "init", "-q")
    (path / "app.py").write_text("print('hi')\n")
    return path


@pytest.fixture()
def other_repo(tmp_path: Path) -> Path:
    path = tmp_path / "other"
    path.mkdir()
    _git(path, "init", "-q")
    return path


@pytest.fixture()
def plain_dir(tmp_path: Path) -> Path:
    path = tmp_path / "plain"
    path.mkdir()
    return path


def bash(command: str, cwd: Path, guarded: list | None = None) -> str | None:
    guarded = guarded if guarded is not None else [str(cwd.parent / "repo")]
    return hook.evaluate({"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}, guarded)


BLOCKED = [
    "git commit -m 'wip'",
    "git commit --amend --no-edit",
    "git push",
    "git push --force origin main",
    "git push -f",
    "git pull --rebase",
    "git merge feature",
    "git rebase -i HEAD~3",
    "git cherry-pick abc123",
    "git revert HEAD",
    "git am < fix.patch",
    "git reset --hard HEAD~1",
    "git reset --soft HEAD~1",
    "git reset origin/main",
    "git tag v1.0",
    "git tag -a v1.0 -m release",
    "git tag -d v1.0",
    "git branch -D feature",
    "git branch -d feature",
    "git branch --delete feature",
    "git branch -m old new",
    "git branch -f main HEAD~2",
    "git stash",
    "git stash push -m x",
    "git stash pop",
    "git stash drop",
    "git stash clear",
    "git checkout -- app.py",
    "git checkout app.py",
    "git checkout .",
    "git checkout -B main",
    "git switch -C main",
    "git switch --discard-changes main",
    "git restore app.py",
    "git restore --staged --worktree app.py",
    "git clean -fd",
    "git remote add evil https://example.com/x.git",
    "git remote set-url origin https://example.com/x.git",
    "git config user.email someone@example.com",
    "git config --unset user.name",
    "git config set alias.c commit",
    "git update-ref refs/heads/main HEAD~1",
    "git symbolic-ref HEAD refs/heads/other",
    "git filter-branch --tree-filter 'rm x' HEAD",
    "git reflog expire --expire=now --all",
    "git worktree remove ../wt",
    "git notes add -m hi",
    "git lfs migrate import",
    "gh pr create --fill",
    "gh pr merge 12 --squash",
    "gh pr close 12",
    "gh pr comment 12 -b hi",
    "gh release create v1",
    "gh repo delete owner/repo",
    "gh workflow run ci.yml",
    "gh api repos/o/r/pulls -f title=x",
    "gh api -X DELETE repos/o/r/git/refs/heads/x",
    "gh api --method=PATCH repos/o/r",
    "gh api graphql -f query='mutation { addStar(input:{}) { clientMutationId } }'",
    "gh some-extension do-something",
    "git branch new-test-branch",
    "git checkout main",
    "git checkout -b test/repro",
    "git switch main",
    "git switch -c test/repro",
    "gh pr checkout 12",
]


@pytest.mark.parametrize("command", BLOCKED)
def test_blocks_source_control_changes(command: str, repo: Path) -> None:
    assert bash(command, repo) is not None


CHAINED = [
    "npm test && git commit -am wip",
    "npm test; git push",
    "npm test || git push",
    "git status\ngit push",
    "npm test | git commit -F -",
    "(cd sub && git push)",
    "echo $(git commit -m x)",
    'echo "$(git push)"',
    "echo `git push`",
    "bash -c 'git push origin main'",
    "sh -lc \"npm test && git commit -m x\"",
    "eval git push",
    "env GIT_TRACE=1 git push",
    "sudo -u dev git push",
    "timeout 30 git push",
    "nohup git push &",
    "xargs -n1 git push < remotes.txt",
    "find . -name '*.orig' -exec git rm {} \\; -exec git commit -m x \\;",
    "/usr/bin/git push",
    "git -C . commit -m x",
    "git -c user.name=x commit -m y",
    "git --no-pager -C . push",
    "git\\\n  push",
    "FOO=1 git push",
    "echo a#b; git push",
]


@pytest.mark.parametrize("command", CHAINED)
def test_blocks_hidden_and_chained_forms(command: str, repo: Path) -> None:
    assert bash(command, repo) is not None


ALLOWED = [
    "git status",
    "git status --short",
    "git diff",
    "git diff --staged HEAD~1",
    "git log --oneline -20",
    "git log --grep fix",
    "git show HEAD:app.py",
    "git blame app.py",
    "git branch",
    "git branch -a --contains HEAD",
    "git restore --staged app.py",
    "git reset",
    "git reset HEAD",
    "git tag",
    "git tag -l 'v1.*'",
    "git tag --sort=-v:refname",
    "git stash list",
    "git stash show -p",
    "git remote -v",
    "git remote show origin",
    "git config --get user.email",
    "git config user.email",
    "git config --list",
    "git clean -n",
    "git fetch origin",
    "git rev-parse HEAD",
    "git ls-files",
    "git grep 'git push'",
    "git worktree list",
    "git symbolic-ref HEAD",
    "git --version",
    "git help commit",
    "gh pr view 12",
    "gh pr list --state open",
    "gh pr diff 12",
    "gh pr checks 12",
    "gh run view 123 --log",
    "gh run watch 123",
    "gh issue list",
    "gh repo view",
    "gh search prs --author @me",
    "gh auth status",
    "gh api repos/o/r/pulls",
    "gh api -X GET search/issues -f q=bug",
    "gh api graphql -f query='{ viewer { login } }'",
    "gh --version",
    "npm test && git diff --stat",
    "grep -rn 'git push' docs/",
    "echo 'remember: git push later' > notes.txt",
    "pytest -q; git status",
    "cat .git/HEAD",
]


@pytest.mark.parametrize("command", ALLOWED)
def test_allows_read_only_commands(command: str, repo: Path) -> None:
    assert bash(command, repo) is None


@pytest.mark.parametrize("command", ["git commit -m x", "git push", "gh pr create --fill"])
def test_does_nothing_outside_a_git_repo(command: str, plain_dir: Path, repo: Path) -> None:
    assert bash(command, plain_dir, [str(repo)]) is None


@pytest.mark.parametrize("command", ["git commit -m x", "git checkout -b x", "rm -rf .git"])
def test_does_nothing_in_a_repo_off_the_list(command: str, other_repo: Path, repo: Path) -> None:
    assert bash(command, other_repo, [str(repo)]) is None


def test_does_nothing_with_an_empty_list(repo: Path) -> None:
    assert bash("git push --force", repo, []) is None


def test_subfolders_of_a_guarded_repo_are_guarded(repo: Path) -> None:
    (repo / "src").mkdir()
    assert bash("git commit -m x", repo / "src", [str(repo)]) is not None


# Paths are written as a shell would get them: forward slashes, or quoted (an unquoted Windows path
# loses its backslashes in bash itself, so the guard reads it the same way bash does).
def test_follows_cd_into_a_repo(plain_dir: Path, repo: Path) -> None:
    assert bash(f"cd {repo.as_posix()} && git commit -m x", plain_dir, [str(repo)]) is not None
    assert bash(f'cd "{repo}" && git commit -m x', plain_dir, [str(repo)]) is not None


def test_follows_git_dash_c_into_a_repo(plain_dir: Path, repo: Path) -> None:
    assert bash(f"git -C {repo.as_posix()} push", plain_dir, [str(repo)]) is not None
    assert bash(f'git -C "{repo}" push', plain_dir, [str(repo)]) is not None


def test_explicit_git_dir_counts_as_repo(plain_dir: Path) -> None:
    assert bash("git --git-dir=/elsewhere/.git commit -m x", plain_dir, ["/guarded"]) is not None
    assert bash("GIT_DIR=/elsewhere/.git git commit -m x", plain_dir, ["/guarded"]) is not None


def test_checkout_of_a_path_in_a_subdirectory_uses_cd(repo: Path) -> None:
    (repo / "src").mkdir()
    (repo / "src" / "mod.py").write_text("x = 1\n")
    assert bash("cd src && git checkout mod.py", repo) is not None
    assert bash("cd src && git restore mod.py", repo) is not None


def test_resolves_git_aliases(repo: Path) -> None:
    _git(repo, "config", "alias.ci", "commit")
    _git(repo, "config", "alias.ship", "!git push origin HEAD")
    _git(repo, "config", "alias.st", "status")
    assert bash("git ci -m x", repo) is not None
    assert bash("git ship", repo) is not None
    assert bash("git st", repo) is None


def test_resolves_inline_aliases(repo: Path) -> None:
    assert bash("git -c alias.x=push x", repo) is not None


def test_blocks_writes_into_dot_git_from_bash(repo: Path) -> None:
    assert bash("rm -rf .git", repo) is not None
    assert bash("echo deadbeef > .git/refs/heads/main", repo) is not None
    assert bash("cp hook.sh .git/hooks/pre-commit", repo) is not None


@pytest.mark.parametrize("tool", ["Write", "Edit", "MultiEdit"])
def test_blocks_file_tools_inside_dot_git(tool: str, repo: Path) -> None:
    payload = {"tool_name": tool, "tool_input": {"file_path": str(repo / ".git" / "config")},
               "cwd": str(repo)}
    assert hook.evaluate(payload, [str(repo)]) is not None
    assert hook.evaluate(payload, []) is None


@pytest.mark.parametrize("name", [".gitignore", ".github/workflows/ci.yml", "tests/test_x.py"])
def test_allows_file_tools_elsewhere(name: str, repo: Path) -> None:
    payload = {"tool_name": "Write", "tool_input": {"file_path": str(repo / name)}, "cwd": str(repo)}
    assert hook.evaluate(payload, [str(repo)]) is None


def test_unbalanced_quotes_mentioning_git_are_blocked(repo: Path) -> None:
    assert bash("git commit -m 'oops", repo) is not None
    assert bash("echo 'oops", repo) is None


def test_message_explains_the_block(repo: Path) -> None:
    message = bash("npm test && git push --force", repo)
    assert "git push" in message
    assert "guard list" in message


def _run_hook(payload: dict | str, cwd: Path, home: Path) -> subprocess.CompletedProcess:
    data = payload if isinstance(payload, str) else json.dumps(payload)
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    return subprocess.run([sys.executable, str(HOOK)], input=data, text=True, capture_output=True,
                          cwd=cwd, env=env)


@pytest.fixture()
def home(tmp_path: Path) -> Path:
    path = tmp_path / "home"
    path.mkdir()
    return path


def test_process_exits_2_with_stderr_when_blocked(repo: Path, home: Path) -> None:
    hook.enable(str(repo), str(home))
    result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "git push"},
                        "cwd": str(repo), "hook_event_name": "PreToolUse"}, repo, home)
    assert result.returncode == 2
    assert "git push" in result.stderr


def test_process_exits_0_when_allowed(repo: Path, home: Path) -> None:
    hook.enable(str(repo), str(home))
    result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "git status"},
                        "cwd": str(repo), "hook_event_name": "PreToolUse"}, repo, home)
    assert result.returncode == 0
    assert result.stderr == ""


def test_process_exits_0_without_a_list(repo: Path, home: Path) -> None:
    result = _run_hook({"tool_name": "Bash", "tool_input": {"command": "git push"}, "cwd": str(repo)}, repo, home)
    assert result.returncode == 0


def test_process_blocks_on_invalid_input_only_with_a_list(repo: Path, home: Path) -> None:
    assert _run_hook("not json", repo, home).returncode == 0
    hook.enable(str(repo), str(home))
    assert _run_hook("not json", repo, home).returncode == 2


def test_enable_disable_status(repo: Path, home: Path) -> None:
    (repo / "sub").mkdir()
    out = hook.enable(str(repo / "sub"), str(home))
    assert out == {"repo": hook.norm_path(str(repo)), "guarded": True, "changed": True}
    assert hook.enable(str(repo), str(home))["changed"] is False
    assert hook.status(str(repo), str(home))["guarded"] is True
    assert hook.load_list(str(home)) == [hook.norm_path(str(repo))]
    assert not (repo / ".claude").exists()  # nothing is written into the customer repository
    assert hook.disable(str(repo), str(home))["changed"] is True
    assert hook.status(str(repo), str(home))["guarded"] is False


def test_enable_refuses_a_folder_outside_git(plain_dir: Path, home: Path) -> None:
    with pytest.raises(ValueError):
        hook.enable(str(plain_dir), str(home))


def test_run_python_launcher_fails_closed_only_with_a_list(tmp_path: Path, home: Path) -> None:
    launcher = ROOT / "hooks" / "run-python.sh"
    sh = "sh"
    env = {"HOME": str(home), "PATH": str(tmp_path / "empty-bin")}  # no Python on PATH
    if not shutil_which(sh):
        pytest.skip("no sh")
    args = [shutil_which(sh), str(launcher), "fail-closed", str(HOOK)]
    assert subprocess.run(args, input="{}", text=True, capture_output=True, env=env).returncode == 0
    (home / ".testign-kit").mkdir()
    (home / ".testign-kit" / "guarded_repos.json").write_text('{"repos": ["/x"]}')
    blocked = subprocess.run(args, input="{}", text=True, capture_output=True, env=env)
    assert blocked.returncode == 2 and "Python 3.10" in blocked.stderr
    args[2] = "fail-open"
    assert subprocess.run(args, input="{}", text=True, capture_output=True, env=env).returncode == 0


def shutil_which(name: str) -> str | None:
    import shutil  # noqa: PLC0415
    return shutil.which(name)


def test_cli_guard_commands(repo: Path, home: Path) -> None:
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    run = [sys.executable, str(ROOT / "scripts" / "run.py"), "guard"]
    out = subprocess.run([*run, "enable", "--repo", str(repo)], capture_output=True, text=True, env=env)
    assert out.returncode == 0 and json.loads(out.stdout)["guarded"] is True
    status = json.loads(subprocess.run([*run, "status", "--repo", str(repo)], capture_output=True, text=True,
                                       env=env).stdout)
    assert status["guarded"] is True and len(status["repos"]) == 1
    out = subprocess.run([*run, "disable", "--repo", str(repo)], capture_output=True, text=True, env=env)
    assert json.loads(out.stdout)["guarded"] is False


@pytest.mark.parametrize("command", ["python3 scripts/run.py guard disable --repo .",
                                     "echo '{}' > ~/.testign-kit/guarded_repos.json"])
def test_claude_cannot_take_a_repo_off_the_list(command: str, plain_dir: Path, repo: Path) -> None:
    assert bash(command, plain_dir, [str(repo)]) is not None


def test_file_tools_cannot_edit_the_list(plain_dir: Path, repo: Path) -> None:
    payload = {"tool_name": "Write", "tool_input": {"file_path": "/h/.testign-kit/guarded_repos.json"},
               "cwd": str(plain_dir)}
    assert hook.evaluate(payload, [str(repo)]) is not None
