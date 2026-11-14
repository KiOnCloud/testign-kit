"""Command line entry for the testign skills. Every subcommand prints JSON on stdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, config, gitscope


def _cmd_config(_args: argparse.Namespace) -> int:
    print(json.dumps(config.load(), ensure_ascii=False, indent=2))
    return 0


def _read_anchors_file(path: str) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read anchors file {path}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("anchors"), list) or not data["anchors"]:
        raise ValueError(f'{path} must be a JSON object with a non-empty "anchors" list')
    for key in ("paths", "symbols"):
        if not isinstance(data.get(key, []), list):
            raise ValueError(f'"{key}" in {path} must be a list')
    return data


def scout_facts(
    repo: str,
    anchors: list[str],
    master_ref: str,
    develop_ref: str,
    ticket_regex: str,
    paths: list[str] | None = None,
    symbols: list[str] | None = None,
) -> dict:
    """Collect every git fact the scout skill needs, without touching the working tree.

    When ``paths`` is empty, the scoped paths are the files where anchors hit at the merge-base.
    The skill runs this once with anchors only, reads code, then runs it again with the paths and
    symbols it collected so the develop diff is filtered by them.
    """
    refs = gitscope.resolve_refs(repo, master_ref, develop_ref)
    base = gitscope.merge_base(repo, refs["master"], refs["develop"])
    hits = gitscope.grep_anchors(repo, base, refs["develop"], anchors)

    scoped = list(dict.fromkeys(paths or [h["path"] for a in hits for h in a["merge_base"]]))
    terms = list(dict.fromkeys([*anchors, *(symbols or [])]))
    changes = gitscope.changed_files(repo, refs["master"], refs["develop"], scoped, terms)

    base_files = [p for p in scoped if not p.endswith("/")]
    new_files = [h["path"] for a in hits if a["status"] == "new_in_phase" for h in a["develop"]]
    considered = [*base_files, *new_files, *(c["path"] for c in changes["kept"])]

    return {
        "plugin_version": __version__,
        "repo": str(Path(repo).resolve()),
        "refs": {
            "master_ref": master_ref,
            "develop_ref": develop_ref,
            "master_sha": refs["master"],
            "develop_head": refs["develop"],
            "merge_base": base,
            "root_commit": gitscope.root_commit(repo, refs["master"]),
        },
        "anchors": hits,
        "scoped_paths": scoped,
        "symbols": symbols or [],
        "blob_hashes_at_merge_base": gitscope.blob_hashes(repo, base, base_files),
        "changed_files": changes,
        "commits_by_ticket": gitscope.commits_by_ticket(repo, base, refs["develop"], ticket_regex),
        "unreadable": gitscope.classify_unreadable(considered),
    }


def _cmd_scout_facts(args: argparse.Namespace) -> int:
    cfg = config.load()
    spec = _read_anchors_file(args.anchors_file)
    if args.fetch:
        gitscope.fetch(args.repo)
    facts = scout_facts(
        repo=args.repo,
        anchors=spec["anchors"],
        master_ref=args.master_ref or cfg["master_ref"],
        develop_ref=args.develop_ref or cfg["develop_ref"],
        ticket_regex=args.ticket_regex or cfg["ticket_id_regex"],
        paths=spec.get("paths"),
        symbols=spec.get("symbols"),
    )
    text = json.dumps(facts, ensure_ascii=False, indent=2)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n", encoding="utf-8")
        print(json.dumps({"written": str(out.resolve())}, ensure_ascii=False))
    else:
        print(text)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="testign")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    cfg = sub.add_parser("config", help="print the effective tester config, creating it on first run")
    cfg.set_defaults(func=_cmd_config)

    sf = sub.add_parser("scout-facts", help="collect read-only git facts for the scout skill as JSON")
    sf.add_argument("--repo", required=True, help="path to the local clone of the customer repo")
    sf.add_argument(
        "--anchors-file",
        required=True,
        help='JSON file: {"anchors": [...], "paths": [...optional], "symbols": [...optional]}',
    )
    sf.add_argument("--master-ref", help="branch or SHA for Production (default: config master_ref)")
    sf.add_argument("--develop-ref", help="branch or SHA for the current phase (default: config develop_ref)")
    sf.add_argument("--ticket-regex", help="ticket ID regex (default: config ticket_id_regex)")
    sf.add_argument("--fetch", action="store_true", help="run git fetch first (updates remote-tracking refs only)")
    sf.add_argument("--out", help="write the JSON here instead of stdout")
    sf.set_defaults(func=_cmd_scout_facts)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (config.ConfigError, gitscope.GitError, ValueError) as exc:
        print(f"testign: {exc}", file=sys.stderr)
        return 2
