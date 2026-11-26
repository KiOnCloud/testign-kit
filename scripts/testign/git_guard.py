#!/usr/bin/env python3
"""Git write guard: keep Claude from changing a customer repository the tester put on the guard list.

testign only reads the customer repository (rules.md §2). When the working directory, or a directory
a command targets (`cd X`, `git -C X`), is inside a repository on the guard list, the PreToolUse hook
``hooks/git_guard.py`` blocks commands that create, rewrite, publish or discard history or change the
working tree: commit, push, merge, rebase, reset, checkout, switch, new branches, tags, stash, `gh pr
create/merge`, writes into `.git/`, and so on. Read-only git and gh commands pass through.
Repositories that are not on the list are left alone.

The list is ``~/.testign-kit/guarded_repos.json`` (each repository's top-level folder), managed with
``guard enable|disable|status``; nothing is written into the repository itself.

Protocol (Claude Code hooks): the tool call arrives as JSON on stdin. Exit 0 allows it; exit 2
blocks it and the message on stderr is shown to Claude.

This is a guardrail against accidental or habitual source-control changes, not a security boundary:
a determined process can still reach git through a script file or another interpreter. Standard
library only; the shell parsing comes from qingyi-test-kit's source-control hook.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Shell tokenizing
# --------------------------------------------------------------------------

_PUNCT = ";&|()<>`\n"
_SHELLS = {"sh", "bash", "zsh", "dash", "ksh", "ash", "fish", "mksh"}
_MAX_DEPTH = 5


def tokenize(command: str) -> list[str]:
    """Split a shell command into words and operator tokens.

    Raises ValueError on unbalanced quotes.
    """
    command = command.replace("\\\n", " ")
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCT)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    lexer.commenters = ""  # `#` mid-word is not a comment; scanning comments only over-blocks
    return list(lexer)


def _is_operator(tok: str) -> bool:
    return bool(tok) and all(c in _PUNCT for c in tok)


def _is_separator(tok: str) -> bool:
    return _is_operator(tok) and "<" not in tok and ">" not in tok


def _is_redirect(tok: str) -> bool:
    return _is_operator(tok) and ("<" in tok or ">" in tok)


def split_segments(tokens: list[str]) -> list[list[str]]:
    """Split on ; & && | || ( ) ` and newlines into simple commands."""
    segments: list[list[str]] = [[]]
    for tok in tokens:
        if _is_separator(tok):
            segments.append([])
        else:
            segments[-1].append(tok)
    return [s for s in segments if s]


def _basename(tok: str) -> str:
    name = tok.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    return name[:-4] if name.lower().endswith(".exe") else name


def _has_git_dir_part(path: str) -> bool:
    return ".git" in re.split(r"[\\/]+", path)


# --------------------------------------------------------------------------
# Scan state
# --------------------------------------------------------------------------


@dataclass
class Scan:
    cwd: str
    findings: list[str] = field(default_factory=list)
    target_dirs: list[str] = field(default_factory=list)  # from `cd X` and `git -C X`
    explicit_repo: bool = False  # --git-dir / --work-tree / GIT_DIR= in the command

    def block(self, what: str) -> None:
        if what not in self.findings:
            self.findings.append(what)


def _resolve(base: str, path: str) -> str:
    path = os.path.expanduser(os.path.expandvars(path))
    return os.path.normpath(os.path.join(base, path))


def _git_output(cwd: str, *args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=cwd if os.path.isdir(cwd) else None,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def _nearest_existing_dir(path: str) -> str | None:
    path = os.path.abspath(path)
    while not os.path.isdir(path):
        parent = os.path.dirname(path)
        if parent == path:
            return None
        path = parent
    return path


def repo_root(path: str) -> str | None:
    """The top-level folder of the repository holding ``path``, normalised for comparison."""
    existing = _nearest_existing_dir(path)
    if existing is None:
        return None
    top = _git_output(existing, "rev-parse", "--show-toplevel")
    return norm_path(top) if top else None


def norm_path(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.expanduser(path)))


# --------------------------------------------------------------------------
# Guard list
# --------------------------------------------------------------------------

LIST_FILE = "guarded_repos.json"


def config_home(home: str | None = None) -> str:
    """``<home>/.testign-kit``, as ``config.config_dir`` (``home`` defaults to the user's home)."""
    return os.path.join(str(home) if home else os.path.expanduser("~"), ".testign-kit")


def list_path(home: str | None = None) -> str:
    return os.path.join(config_home(home), LIST_FILE)


def load_list(home: str | None = None) -> list[str]:
    try:
        with open(list_path(home), encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return []
    repos = data.get("repos") if isinstance(data, dict) else None
    return [r for r in repos if isinstance(r, str) and r] if isinstance(repos, list) else []


def save_list(repos: list[str], home: str | None = None) -> None:
    path = list_path(home)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump({"repos": sorted(set(repos))}, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    os.replace(tmp, path)


def _need_root(repo: str) -> str:
    root = repo_root(repo) if os.path.isdir(repo) else None
    if root is None:
        raise ValueError(f"{repo} is not inside a git repository")
    return root


def enable(repo: str, home: str | None = None) -> dict:
    root = _need_root(repo)
    repos = load_list(home)
    added = root not in repos
    if added:
        save_list([*repos, root], home)
    return {"repo": root, "guarded": True, "changed": added}


def disable(repo: str, home: str | None = None) -> dict:
    root = repo_root(repo) if os.path.isdir(repo) else norm_path(repo)
    repos = load_list(home)
    removed = root in repos
    if removed:
        save_list([r for r in repos if r != root], home)
    return {"repo": root, "guarded": False, "changed": removed}


def status(repo: str | None = None, home: str | None = None) -> dict:
    repos = load_list(home)
    out: dict = {"repos": [{"repo": r, "exists": os.path.isdir(r)} for r in repos], "list": list_path(home)}
    if repo:
        root = repo_root(repo) if os.path.isdir(repo) else None
        out["repo"] = root or repo
        out["guarded"] = root is not None and root in repos
    return out


# --------------------------------------------------------------------------
# Option helpers
# --------------------------------------------------------------------------


def _flags(args: list[str]) -> set[str]:
    """Option names in args, with `--x=v` cut at `=` and `-abc` expanded to -a -b -c."""
    out: set[str] = set()
    for a in args:
        if a == "--":
            break
        if a.startswith("--"):
            out.add(a.split("=", 1)[0])
        elif a.startswith("-") and len(a) > 1:
            out.add(a)
            out.update(f"-{c}" for c in a[1:])
    return out


def _positionals(args: list[str], value_opts: frozenset[str] = frozenset()) -> list[str]:
    """Non-option arguments before `--`, skipping the values of `value_opts`."""
    out: list[str] = []
    skip = False
    for a in args:
        if skip:
            skip = False
            continue
        if a == "--":
            break
        if a.startswith("-") and len(a) > 1:
            if a in value_opts:
                skip = True
            continue
        out.append(a)
    return out


def _first_positional(args: list[str], value_opts: frozenset[str] = frozenset()) -> str | None:
    pos = _positionals(args, value_opts)
    return pos[0] if pos else None


# --------------------------------------------------------------------------
# git rules: return a short reason when the subcommand changes source control
# --------------------------------------------------------------------------

_GIT_ALWAYS_BLOCK = {
    "commit": "creates a commit",
    "push": "publishes commits",
    "pull": "merges remote commits into the branch",
    "merge": "merges history",
    "rebase": "rewrites history",
    "cherry-pick": "creates commits",
    "revert": "creates a revert commit",
    "am": "creates commits from patches",
    "filter-branch": "rewrites history",
    "filter-repo": "rewrites history",
    "update-ref": "moves refs directly",
    "replace": "replaces objects",
    "commit-tree": "creates commit objects",
    "fast-import": "writes history",
    "prune": "deletes unreachable objects",
    "send-email": "sends patches",
    "gui": "opens the commit GUI",
    "citool": "opens the commit GUI",
}


def _git_reset(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _flags(args) & {"--hard", "--soft", "--mixed", "--merge", "--keep"}:
        return "moves the branch or discards changes"
    if any(p != "HEAD" for p in _positionals(args)):
        return "may move the branch to another commit (use `git restore --staged <path>` to unstage)"
    return None


_TAG_VALUE_OPTS = frozenset(
    {"--sort", "--format", "--contains", "--no-contains", "--merged", "--no-merged", "--points-at"}
)


def _git_tag(args: list[str], scan: Scan, cwd: str) -> str | None:
    f = _flags(args)
    if f & {"-d", "--delete", "-f", "--force", "-a", "--annotate", "-s", "--sign", "-u",
            "--local-user", "-m", "--message", "-F", "--file", "-e", "--edit"}:
        return "creates or deletes a tag"
    if f & {"-l", "--list", "-n", "-v", "--verify"}:
        return None
    if _positionals(args, _TAG_VALUE_OPTS):
        return "creates a tag"
    return None


_BRANCH_LIST_FLAGS = {"-l", "--list", "-a", "--all", "-r", "--remotes", "-v", "-vv", "--verbose",
                      "--contains", "--no-contains", "--merged", "--no-merged", "--points-at", "--show-current",
                      "--format", "--sort", "--column", "--no-column"}
_BRANCH_VALUE_OPTS = frozenset({"--contains", "--no-contains", "--merged", "--no-merged", "--points-at",
                                "--format", "--sort", "--column"})


def _git_branch(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _flags(args) & {"-d", "-D", "--delete", "-m", "-M", "--move", "-c", "-C", "--copy", "-f",
                       "--force", "-u", "--set-upstream-to", "--unset-upstream", "--edit-description"}:
        return "deletes, renames, overwrites or re-points a branch"
    if _flags(args) & _BRANCH_LIST_FLAGS:
        return None
    if _positionals(args, _BRANCH_VALUE_OPTS):
        return "creates a branch"
    return None  # listing


def _git_checkout(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _flags(args) & {"-h", "--help"}:
        return None
    return "checks out another branch or restores paths (testign reads refs with `git show <ref>:<path>`)"


def _git_switch(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _flags(args) & {"-h", "--help"}:
        return None
    return "switches branches (testign reads refs with `git show <ref>:<path>`)"


def _git_restore(args: list[str], scan: Scan, cwd: str) -> str | None:
    f = _flags(args)
    if f & {"-S", "--staged"} and not f & {"-W", "--worktree"}:
        return None  # unstaging only touches the index
    return "discards working-tree changes"


def _git_clean(args: list[str], scan: Scan, cwd: str) -> str | None:
    return None if _flags(args) & {"-n", "--dry-run"} else "deletes untracked files"


def _git_stash(args: list[str], scan: Scan, cwd: str) -> str | None:
    return None if _first_positional(args) in {"list", "show"} else "stashes or rewrites local changes"


def _git_remote(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _first_positional(args) in {"add", "remove", "rm", "rename", "set-url", "set-head",
                                   "set-branches", "prune", "update"}:
        return "changes remotes"
    return None


_CONFIG_VALUE_OPTS = frozenset({"-f", "--file", "--blob", "--type", "--default"})


def _git_config(args: list[str], scan: Scan, cwd: str) -> str | None:
    f = _flags(args)
    pos = _positionals(args, _CONFIG_VALUE_OPTS)
    first = pos[0] if pos else None
    if first in {"get", "list"}:
        return None
    if first in {"set", "unset", "rename-section", "remove-section", "edit"}:
        return "writes git config"
    if f & {"--get", "--get-all", "--get-regexp", "--get-urlmatch", "-l", "--list", "--get-color",
            "--get-colorbool"}:
        return None
    if f & {"--add", "--unset", "--unset-all", "--replace-all", "--rename-section",
            "--remove-section", "-e", "--edit"} or len(pos) >= 2:
        return "writes git config"
    return None


def _git_worktree(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _first_positional(args) in {"remove", "move", "prune"}:
        return "removes or moves a worktree"
    return None


def _git_submodule(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _first_positional(args) in {"add", "deinit", "foreach", "set-branch", "set-url", "absorbgitdirs"}:
        return "changes submodules or runs commands in them"
    return None


def _git_notes(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _first_positional(args) in {"add", "append", "copy", "edit", "merge", "remove", "prune"}:
        return "writes notes"
    return None


def _git_reflog(args: list[str], scan: Scan, cwd: str) -> str | None:
    return "deletes reflog entries" if _first_positional(args) in {"expire", "delete"} else None


def _git_symbolic_ref(args: list[str], scan: Scan, cwd: str) -> str | None:
    if _flags(args) & {"-d", "--delete"} or len(_positionals(args)) >= 2:
        return "moves a symbolic ref"
    return None


def _git_lfs(args: list[str], scan: Scan, cwd: str) -> str | None:
    return "pushes or rewrites LFS history" if _first_positional(args) in {"push", "migrate"} else None


_GIT_RULES = {
    "reset": _git_reset,
    "tag": _git_tag,
    "branch": _git_branch,
    "checkout": _git_checkout,
    "switch": _git_switch,
    "restore": _git_restore,
    "clean": _git_clean,
    "stash": _git_stash,
    "remote": _git_remote,
    "config": _git_config,
    "worktree": _git_worktree,
    "submodule": _git_submodule,
    "notes": _git_notes,
    "reflog": _git_reflog,
    "symbolic-ref": _git_symbolic_ref,
    "lfs": _git_lfs,
}

_GIT_GLOBAL_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env",
                          "--super-prefix", "--list-cmds"}


def scan_git(args: list[str], scan: Scan, cwd: str, depth: int) -> None:
    """Analyze one `git ...` invocation (args exclude the `git` word)."""
    inline_aliases: dict[str, str] = {}
    i = 0
    while i < len(args) and args[i].startswith("-"):
        opt, _, attached = args[i].partition("=")
        if opt in _GIT_GLOBAL_VALUE_OPTS:
            value = attached if attached else (args[i + 1] if i + 1 < len(args) else "")
            i += 1 if attached else 2
            if opt == "-C":
                cwd = _resolve(cwd, value)
                scan.target_dirs.append(cwd)
            elif opt in {"--git-dir", "--work-tree"}:
                scan.explicit_repo = True
            elif opt == "-c" and value.startswith("alias."):
                name, _, body = value[len("alias."):].partition("=")
                inline_aliases[name] = body
            continue
        if opt in {"--git-dir", "--work-tree"}:
            scan.explicit_repo = True
        i += 1
    if i >= len(args):
        return
    sub, rest = args[i], args[i + 1:]

    reason = _GIT_ALWAYS_BLOCK.get(sub)
    if reason is None and sub in _GIT_RULES:
        reason = _GIT_RULES[sub](rest, scan, cwd)
    if reason:
        scan.block(f"`git {sub}` {reason}")
        return
    if sub in _GIT_ALWAYS_BLOCK or sub in _GIT_RULES or depth >= _MAX_DEPTH:
        return

    # Unknown subcommand: it may be an alias that expands to a blocked one.
    alias = inline_aliases.get(sub)
    if alias is None:
        alias = _git_output(cwd, "config", "--get", f"alias.{sub}")
    if not alias:
        return
    if alias.startswith("!"):
        scan_command(alias[1:], scan, cwd, depth + 1)
        return
    try:
        expanded = tokenize(alias)
    except ValueError:
        scan.block(f"`git {sub}` is an alias that could not be parsed")
        return
    scan_git(expanded + rest, scan, cwd, depth + 1)


# --------------------------------------------------------------------------
# gh rules: allowlist of read-only commands, everything else is blocked
# --------------------------------------------------------------------------

_GH_VALUE_OPTS = frozenset({"-R", "--repo", "--hostname", "-q", "--jq", "-t", "--template"})
_GH_READ_GROUPS = {"help", "version", "status", "browse", "completion", "search"}
_GH_READ_VERBS = {"list", "view", "status", "diff", "checks", "download", "watch",
                  "clone", "get", "verify"}
_GH_FIELD_OPTS = {"-f", "-F", "--field", "--raw-field", "--input"}


def _gh_api_reason(args: list[str]) -> str | None:
    method = None
    has_fields = False
    for i, a in enumerate(args):
        opt, eq, val = a.partition("=")
        if opt in {"-X", "--method"}:
            method = val if eq else (args[i + 1] if i + 1 < len(args) else "")
        elif a.startswith("-X") and len(a) > 2:
            method = a[2:]
        elif opt in _GH_FIELD_OPTS or (a[:2] in {"-f", "-F"} and len(a) > 2):
            has_fields = True
    endpoint = _first_positional(args, frozenset({"-X", "--method", "-H", "--header", "-f", "-F",
                                                  "--field", "--raw-field", "--input", "-q", "--jq",
                                                  "-t", "--template", "--hostname", "--cache"}))
    if endpoint == "graphql":
        if any(re.search(r"\bmutation\b", a, re.IGNORECASE) for a in args):
            return "runs a GraphQL mutation"
        return None
    if method is not None:
        return None if method.upper() in {"GET", "HEAD"} else f"sends a {method.upper()} request"
    return "sends a POST request" if has_fields else None


def scan_gh(args: list[str], scan: Scan) -> None:
    pos = _positionals(args, _GH_VALUE_OPTS)
    if not pos:
        return  # bare `gh`, `gh --help`, `gh --version`
    group = pos[0]
    verb = pos[1] if len(pos) > 1 else None
    if group in _GH_READ_GROUPS:
        return
    if group == "api":
        reason = _gh_api_reason(args[args.index("api") + 1:])
        if reason:
            scan.block(f"`gh api` {reason}")
        return
    if group == "auth" and verb in {"status", None}:
        return
    if verb is None or verb in _GH_READ_VERBS:
        return
    scan.block(f"`gh {group} {verb}` is not a read-only gh command")


# --------------------------------------------------------------------------
# Generic command scan
# --------------------------------------------------------------------------

_WRITE_TOOLS = {"rm", "rmdir", "mv", "tee", "truncate", "ln", "shred", "unlink"}


def _scan_segment(seg: list[str], scan: Scan, cwd: str, depth: int) -> str:
    """Scan one simple command; returns the working directory after it."""
    words: list[str] = []
    skip_next = False
    for tok in seg:
        if skip_next:
            skip_next = False
            if _has_git_dir_part(tok):
                scan.block("a redirect writes into `.git/`")
            continue
        if _is_redirect(tok):
            skip_next = ">" in tok
            continue
        if re.match(r"^GIT_(DIR|WORK_TREE)=", tok):
            scan.explicit_repo = True
        words.append(tok)

    # Command substitutions and `sh -c` / `eval` payloads hide commands inside one word.
    for idx, tok in enumerate(words):
        if depth < _MAX_DEPTH and ("$(" in tok or "`" in tok):
            inner = tok.replace("$(", " ; ").replace("`", " ; ").replace(")", " ; ")
            scan_command(inner, scan, cwd, depth + 1)
        name = _basename(tok)
        if depth < _MAX_DEPTH and name in _SHELLS:
            for j in range(idx + 1, len(words) - 1):
                if re.fullmatch(r"-[a-zA-Z]*c[a-zA-Z]*", words[j]):
                    scan_command(words[j + 1], scan, cwd, depth + 1)
                    break
        if depth < _MAX_DEPTH and name == "eval":
            scan_command(" ".join(words[idx + 1:]), scan, cwd, depth + 1)

    # Look for git/gh anywhere in the command, so wrappers like `env`, `sudo`,
    # `xargs`, `find -exec`, `timeout`, `nohup` cannot hide them.
    for idx, tok in enumerate(words):
        name = _basename(tok)
        if name == "git":
            scan_git(words[idx + 1:], scan, cwd, depth)
        elif name == "gh":
            scan_gh(words[idx + 1:], scan)
        elif name in _WRITE_TOOLS and any(_has_git_dir_part(w) for w in words[idx + 1:]):
            scan.block(f"`{name}` modifies files inside `.git/`")
        elif name == "cp" and len(words) > idx + 2 and _has_git_dir_part(words[-1]):
            scan.block("`cp` writes into `.git/`")

    # Track `cd` so later commands in the chain are judged in the right directory.
    first = next((w for w in words if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", w)), None)
    if first in {"cd", "pushd"}:
        targets = [w for w in words[words.index(first) + 1:] if not w.startswith("-")]
        new_cwd = _resolve(cwd, targets[0]) if targets else os.path.expanduser("~")
        scan.target_dirs.append(new_cwd)
        return new_cwd
    return cwd


def scan_command(command: str, scan: Scan, cwd: str | None = None, depth: int = 0) -> None:
    cwd = cwd or scan.cwd
    try:
        tokens = tokenize(command)
    except ValueError:
        if re.search(r"\b(git|gh)\b", command):
            scan.block("the command has unbalanced quotes and mentions git/gh")
        return
    for seg in split_segments(tokens):
        cwd = _scan_segment(seg, scan, cwd, depth)


# --------------------------------------------------------------------------
# Entry points
# --------------------------------------------------------------------------


def evaluate(payload: dict, guarded: list[str] | None = None) -> str | None:
    """Return a block message for this tool call, or None to allow it.

    ``guarded`` is the guard list (top-level folders, see ``norm_path``); None reads it from
    ``~/.testign-kit``. With an empty list nothing is blocked.
    """
    guarded = load_list() if guarded is None else [norm_path(g) for g in guarded]
    if not guarded:
        return None
    tool = payload.get("tool_name", "")
    tool_input = payload.get("tool_input") or {}
    cwd = payload.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()

    if tool in {"Write", "Edit", "MultiEdit", "NotebookEdit"}:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        if path and os.path.basename(path) == LIST_FILE:
            return _message([f"`{tool}` would change the guard list; only the tester changes it"])
        if path and _has_git_dir_part(path) and _guarded(_outside_git_dir(_resolve(cwd, path)), guarded):
            return _message([f"`{tool}` would modify `{path}` inside `.git/`"])
        return None

    if tool != "Bash":
        return None
    command = tool_input.get("command") or ""
    if re.search(r"\bguard\s+disable\b", command) or LIST_FILE in command:
        return _message(["the command would change the guard list; only the tester runs `guard disable`"])
    scan = Scan(cwd=cwd)
    scan_command(command, scan)
    if not scan.findings:
        return None
    if scan.explicit_repo or any(_guarded(d, guarded) for d in (cwd, *scan.target_dirs)):
        return _message(scan.findings)
    return None


def _outside_git_dir(path: str) -> str:
    """The folder holding the first ``.git`` part of ``path``: git finds no work tree inside ``.git``."""
    parts = re.split(r"([\\/]+)", path)
    for i, part in enumerate(parts):
        if part == ".git":
            return "".join(parts[:i]) or os.sep
    return path


def _guarded(path: str, guarded: list[str]) -> bool:
    root = repo_root(path)
    return root is not None and root in guarded


def _message(findings: list[str]) -> str:
    lines = "\n".join(f"  - {f}" for f in findings)
    return (
        "Blocked by testign: this customer repository is on the guard list, and testign only reads it "
        "(rules.md §2).\n"
        f"{lines}\n"
        "Read-only commands (git show/diff/log/grep/merge-base/rev-parse/status, gh pr view/list/diff) are allowed. "
        "Do not retry or work around this; tell the user which change you wanted to make so they "
        "can run it themselves."
    )


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        if load_list():
            print(f"testign git guard could not read its input ({exc}); blocking to be safe.", file=sys.stderr)
            return 2
        return 0
    message = evaluate(payload)
    if message:
        print(message, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
