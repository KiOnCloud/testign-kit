"""Command line entry for the testign skills. Every subcommand prints JSON on stdout."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__, config, gitscope, hashcheck, report, templates, trace, xlsx


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


def _emit(data) -> int:
    print(json.dumps(data, ensure_ascii=False, indent=2))
    return 0


def _parse_map(pairs: list[str] | None) -> dict[str, str]:
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise ValueError(f"--map expects role=COLUMN, got '{pair}'")
        role, col = pair.split("=", 1)
        out[role.strip()] = col.strip()
    return out


def _layout(args: argparse.Namespace) -> tuple[dict, Path]:
    """Layout (sheet, header_row, columns) and template path from --template NAME (or the default)."""
    entry = templates.resolve(getattr(args, "template", None))
    return entry, Path(entry["path"])


def _cmd_template_register(args: argparse.Namespace) -> int:
    return _emit(
        templates.register(
            Path(args.file),
            args.name,
            sheet=args.sheet,
            header_row=args.header_row,
            overrides=_parse_map(args.map),
            make_default=args.default,
            replace=args.replace,
        )
    )


def _cmd_template_list(_args: argparse.Namespace) -> int:
    return _emit(templates.list_templates())


def _cmd_template_default(args: argparse.Namespace) -> int:
    return _emit(templates.set_default(args.name))


def _cmd_template_remove(args: argparse.Namespace) -> int:
    return _emit(templates.remove(args.name))


def _cmd_template_preview(args: argparse.Namespace) -> int:
    if args.file:
        text = templates.preview(Path(args.file), sheet=args.sheet, rows=args.rows)
    else:
        entry = templates.resolve(args.template)
        text = templates.preview(
            Path(entry["path"]), entry["sheet"], entry["header_row"], entry["columns"],
            title=f"{entry['name']} ({entry['source_name']})", rows=args.rows,
        )
    print(text)
    return 0


def _cmd_template_sample(args: argparse.Namespace) -> int:

    return _emit({"written": str(xlsx.build_sample(Path(args.out)).resolve())})


def _cmd_hash_check(args: argparse.Namespace) -> int:

    result = hashcheck.check(args.report, args.repo)
    _emit(result)
    return 1 if result["status"] == "stale" else 0


def _load_cases(path: str) -> list[dict]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read cases file {path}: {exc}") from exc


def _cmd_xlsx_fill(args: argparse.Namespace) -> int:

    entry, template_path = _layout(args)
    cases = _load_cases(args.cases)
    meta, _ = report.load(args.report)
    ticket = meta.get("ticket") or "TICKET"
    when = xlsx.stamp()
    if args.into:
        result = xlsx.add_sheet(Path(args.into), entry, cases, f"TC-{when}")
    else:
        out_dir = Path(args.out_dir or config.load()["output_dir"]) / ticket
        result = xlsx.fill_copy(template_path, entry, cases, out_dir / f"{ticket}-testcase-{when}.xlsx")
    return _emit({**result, "template": entry["name"], "cases": len(cases)})


def _cmd_trace(args: argparse.Namespace) -> int:

    entry, _ = _layout(args)
    meta, body = report.load(args.report)
    rows = report.behavior_rows(body) + report.regression_rows(body)
    sheet = xlsx.pick_sheet(Path(args.xlsx), entry, args.sheet)
    cases = xlsx.read_trace(Path(args.xlsx), entry, sheet)
    summary = trace.summarize(rows, cases)
    result = {"report": args.report, "xlsx": args.xlsx, "sheet": sheet, **summary}
    if args.write_revision:
        new_body = report.replace_section(body, 7, trace.section7(summary, Path(args.xlsx).name, sheet))
        result["revision"] = str(report.write_revision(Path(args.report), new_body))
    return _emit(result)


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

    tr = sub.add_parser("template-register", help="register an Excel test case template under a name")
    tr.add_argument("--file", required=True, help=".xlsx/.xlsm template to copy into ~/.testign-kit/templates/")
    tr.add_argument("--name", required=True, help="name the tester uses to pick this template")
    tr.add_argument("--sheet", help="sheet holding the test cases (default: detected by header names)")
    tr.add_argument("--header-row", type=int, help="header row number (default: detected)")
    tr.add_argument("--map", action="append", metavar="ROLE=COLUMN",
                    help="override a column, roles: no, item, steps, expected, evidence, trace")
    tr.add_argument("--default", action="store_true", help="make this the default template")
    tr.add_argument("--replace", action="store_true", help="replace a template already registered under this name")
    tr.set_defaults(func=_cmd_template_register)

    tl = sub.add_parser("template-list", help="list registered templates")
    tl.set_defaults(func=_cmd_template_list)

    td = sub.add_parser("template-default", help="set the default template")
    td.add_argument("--name", required=True)
    td.set_defaults(func=_cmd_template_default)

    tm = sub.add_parser("template-remove", help="unregister a template and delete its stored copy")
    tm.add_argument("--name", required=True)
    tm.set_defaults(func=_cmd_template_remove)

    tp = sub.add_parser("template-preview", help="print a template's layout as Markdown")
    src = tp.add_mutually_exclusive_group()
    src.add_argument("--template", help="registered template name (default: the default template)")
    src.add_argument("--file", help="preview an unregistered file")
    tp.add_argument("--sheet", help="sheet to show (with --file)")
    tp.add_argument("--rows", type=int, default=12, help="rows to show (default 12)")
    tp.set_defaults(func=_cmd_template_preview)

    ts = sub.add_parser("template-sample", help="write the basic sample template shipped with the plugin")
    ts.add_argument("--out", required=True)
    ts.set_defaults(func=_cmd_template_sample)

    hc = sub.add_parser("hash-check", help="check the report's pinned develop HEAD and merge-base (exit 1 = stale)")
    hc.add_argument("--report", required=True)
    hc.add_argument("--repo", help="repo path (default: repo in the report frontmatter)")
    hc.set_defaults(func=_cmd_hash_check)

    xf = sub.add_parser("xlsx-fill", help="write test cases into a copy of the template, never overwriting")
    xf.add_argument("--report", required=True, help="survey report the cases come from")
    xf.add_argument("--cases", required=True,
                    help='JSON list: [{"item", "steps", "expected", "evidence"?, "trace": ["B1"], "waiting_on": ["Q1"]?}]')
    xf.add_argument("--template", help="registered template name (default: the default template)")
    xf.add_argument("--out-dir", help="output folder (default: config output_dir); files go to <out-dir>/<TICKET>/")
    xf.add_argument("--into", help="already filled workbook: copy it and add a new TC-<stamp> sheet instead")
    xf.set_defaults(func=_cmd_xlsx_fill)

    tc = sub.add_parser("trace", help="gaps, orphans and waiting cases between a report and a filled workbook")
    tc.add_argument("--report", required=True)
    tc.add_argument("--xlsx", required=True)
    tc.add_argument("--template", help="registered template whose column mapping the workbook uses")
    tc.add_argument("--sheet", help="sheet to read (default: newest TC-* sheet, else the template sheet)")
    tc.add_argument("--write-revision", action="store_true", help="write section 7 into a new report revision")
    tc.set_defaults(func=_cmd_trace)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (config.ConfigError, gitscope.GitError, report.ReportError, templates.TemplateError, ValueError) as exc:
        print(f"testign: {exc}", file=sys.stderr)
        return 2
