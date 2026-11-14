"""Command line entry for the testign skills. Every subcommand prints JSON on stdout."""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import __version__, backlog_wiki, cache, config, decisions, gitscope, hashcheck, report, templates, trace, xlsx


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


def _cmd_report_path(args: argparse.Namespace) -> int:
    output_dir = Path(config.load()["output_dir"])
    folder = report.ticket_dir(output_dir, args.ticket)
    try:
        latest = str(report.latest_revision(folder, args.ticket))
    except report.ReportError:
        latest = None
    return _emit({"folder": str(folder), "latest": latest, "next": str(report.new_report_path(output_dir, args.ticket))})


def _cmd_report_validate(args: argparse.Namespace) -> int:
    result = report.validate(Path(args.report))
    _emit(result)
    return 0 if result["ok"] else 1


def _cmd_report_save(args: argparse.Namespace) -> int:
    """Turn a draft into the next revision: number, previous, version and time are set here.

    The draft is only read until it validates; the revision file is created exclusively, then the draft
    is removed. A draft that is itself a saved revision is refused.
    """
    draft = Path(args.draft)
    if report.is_revision_file(draft):
        raise report.ReportError(
            f"{draft.name} is a saved revision; copy it to <TICKET>-survey-draft.md and save the copy"
        )
    meta, body = report.load(draft)
    ticket = str(meta.get("ticket") or "")
    if not re.fullmatch(decisions.ticket_pattern(config.load()["ticket_id_regex"]), ticket):
        raise report.ReportError(f"draft frontmatter has an invalid ticket ID: {ticket!r}")
    output_dir = Path(args.out_dir or config.load()["output_dir"])
    folder = report.ticket_dir(output_dir, ticket)
    target = report.new_report_path(output_dir, ticket)
    try:
        previous = report.latest_revision(folder, ticket).name
    except report.ReportError:
        previous = None
    meta.update(
        revision=int(target.stem.rsplit("-r", 1)[1]),
        previous=previous,
        plugin_version=__version__,
        generated_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    )
    text = report.join(meta, body)
    result = report.validate_text(text)
    if not result["ok"]:
        _emit({"saved": None, **result})
        return 1
    report.write_new(target, text)
    draft.unlink()
    return _emit({"saved": str(target), "revision": meta["revision"], "previous": previous, **result})


def _backlog_cfg() -> dict:
    backlog = config.load()["backlog"]
    decisions.check_text_format(backlog.get("text_format", "markdown"))
    return backlog


def _wiki_id(args: argparse.Namespace, backlog: dict) -> str:
    if getattr(args, "wiki_id", None):
        return backlog_wiki.wiki_id_of(args.wiki_id)
    if backlog.get("decisions_log_wiki_id"):
        return backlog_wiki.wiki_id_of(backlog["decisions_log_wiki_id"])
    if backlog.get("project_key") and backlog.get("decisions_log_page"):
        return str(backlog_wiki.find(backlog["project_key"], backlog["decisions_log_page"]))
    raise ValueError(
        "no decisions log page configured: set backlog.decisions_log_wiki_id, or backlog.project_key and "
        "backlog.decisions_log_page, in ~/.testign-kit/config.json (or pass --wiki-id)"
    )


def _read_rows(path: str) -> list[dict]:
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read rows file {path}: {exc}") from exc
    if not isinstance(rows, list) or not rows:
        raise ValueError("rows file must be a non-empty JSON list of approved decisions")
    return rows


def _keepends(text: str) -> list[str]:
    return [line + eol for line, eol in decisions.split_lines(text)]


def _diff(old: str, new: str) -> str:
    return "".join(difflib.unified_diff(_keepends(old), _keepends(new), "wiki (now)", "wiki (after append)"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _append(page: str, rows: list[dict]) -> tuple[str, dict]:
    titles = {r["ticket"]: r["ticket_title"] for r in rows if r.get("ticket_title")}
    return decisions.append(page, rows, config.load()["ticket_id_regex"], titles)


def _cmd_decisions_parse(args: argparse.Namespace) -> int:
    _backlog_cfg()
    page = Path(args.file).read_text(encoding="utf-8")
    return _emit(decisions.parse(page, config.load()["ticket_id_regex"]))


def _cmd_wiki_get(args: argparse.Namespace) -> int:
    backlog = _backlog_cfg()
    page = backlog_wiki.get(_wiki_id(args, backlog))
    return _emit({**page, "parsed": decisions.parse(page["content"], config.load()["ticket_id_regex"])})


def _cmd_wiki_append_preview(args: argparse.Namespace) -> int:
    backlog = _backlog_cfg()
    rows = _read_rows(args.rows)
    if args.page_file:
        page = Path(args.page_file).read_text(encoding="utf-8")
        new, result = _append(page, rows)
        return _emit({"mode": "manual", **result, "diff": _diff(page, new), "new_content": new})
    current = backlog_wiki.get(_wiki_id(args, backlog))
    new, result = _append(current["content"], rows)
    return _emit({"mode": "api", "wiki_id": current["id"], "name": current["name"], "updated": current["updated"],
                  "new_sha256": _sha(new), **result, "diff": _diff(current["content"], new)})


def _cmd_wiki_update(args: argparse.Namespace) -> int:
    backlog = _backlog_cfg()
    rows = _read_rows(args.rows)
    wiki_id = _wiki_id(args, backlog)
    current = backlog_wiki.get(wiki_id)
    if current["updated"] != args.expected_updated:
        raise backlog_wiki.ConflictError(
            f"the wiki page changed since the diff was shown (updated {args.expected_updated} -> "
            f"{current['updated']}). Run wiki-append-preview again and show the new diff."
        )
    new, result = _append(current["content"], rows)
    if _sha(new) != args.expected_hash:
        raise backlog_wiki.ConflictError(
            "the content to write differs from the diff the tester approved (did the rows file change?). "
            "Run wiki-append-preview again and show the new diff."
        )
    if not result["added"] and not result["superseded"]:
        return _emit({"written": False, **result, "reason": "every row is already in the log"})
    saved = backlog_wiki.update(wiki_id, new, current["updated"], expected_content=current["content"],
                                mail_notify=args.mail_notify)
    return _emit({"written": True, **saved, **result})


def _cmd_cache_check(args: argparse.Namespace) -> int:
    cfg = config.load()
    spec = _read_anchors_file(args.anchors_file)
    refs = gitscope.resolve_refs(args.repo, args.master_ref or cfg["master_ref"], args.develop_ref or cfg["develop_ref"])
    base = gitscope.merge_base(args.repo, refs["master"], refs["develop"])
    root = gitscope.root_commit(args.repo, refs["master"])
    folder = cache.entry_dir(root, args.feature)
    manifest, problem = cache.load(folder)
    hashes = gitscope.blob_hashes(args.repo, base, manifest["files"]) if manifest else {}
    decision = cache.decide(manifest, spec["anchors"], hashes, __version__, root, problem)
    return _emit({
        **decision,
        "cache_root": root,
        "cache_feature": cache.slug(args.feature),
        "cache_dir": str(folder),
        "brief": str(folder / cache.BRIEF) if decision["result"] != "miss" else None,
        "merge_base": base,
        "reviewed_by": (manifest or {}).get("reviewed_by"),
    })


def _cmd_cache_save(args: argparse.Namespace) -> int:
    facts = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    brief = Path(args.brief).read_text(encoding="utf-8")
    folder = cache.entry_dir(facts["refs"]["root_commit"], args.feature)
    manifest = cache.save(folder, brief, facts, args.feature)
    return _emit({"cache_dir": str(folder), "cache_root": manifest["root_commit"],
                  "cache_feature": cache.slug(args.feature), "files": len(manifest["files"]),
                  "rows": list(manifest["rows"])})


def _cmd_cache_review(args: argparse.Namespace) -> int:
    meta, _ = report.load(args.report)
    if not meta.get("cache_root") or not meta.get("cache_feature"):
        return _emit({"reviewed": False, "reason": "the report did not use the scout cache"})
    folder = cache.entry_dir(meta["cache_root"], meta["cache_feature"])
    manifest = cache.review(folder, args.by)
    return _emit({"reviewed": True, "cache_dir": str(folder), "reviewed_by": manifest["reviewed_by"]})


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

    rp = sub.add_parser("report-path", help="latest and next survey report revision paths for a ticket")
    rp.add_argument("--ticket", required=True)
    rp.set_defaults(func=_cmd_report_path)

    rv = sub.add_parser("report-validate", help="check a report against the template contract (exit 1 = errors)")
    rv.add_argument("--report", required=True)
    rv.set_defaults(func=_cmd_report_validate)

    rs = sub.add_parser("report-save", help="validate a draft and save it as the next revision, never overwriting")
    rs.add_argument("--draft", required=True, help="draft report with frontmatter (moved into place when valid)")
    rs.add_argument("--out-dir", help="output folder (default: config output_dir)")
    rs.set_defaults(func=_cmd_report_save)

    dp = sub.add_parser("decisions-parse", help="parse a decisions log page saved to a file")
    dp.add_argument("--file", required=True)
    dp.set_defaults(func=_cmd_decisions_parse)

    wg = sub.add_parser("wiki-get", help="read the decisions log page through the Backlog REST API")
    wg.add_argument("--wiki-id")
    wg.set_defaults(func=_cmd_wiki_get)

    wp = sub.add_parser("wiki-append-preview", help="show the diff that appending approved rows would make")
    wp.add_argument("--rows", required=True, help="JSON list of approved decision rows")
    wp.add_argument("--wiki-id")
    wp.add_argument("--page-file", help="page content saved from Backlog MCP; no API call, prints the new content")
    wp.set_defaults(func=_cmd_wiki_append_preview)

    wu = sub.add_parser("wiki-update", help="append approved rows to the wiki page if it did not change")
    wu.add_argument("--rows", required=True)
    wu.add_argument("--expected-updated", required=True, help="'updated' value from wiki-append-preview")
    wu.add_argument("--expected-hash", required=True, help="'new_sha256' value from wiki-append-preview")
    wu.add_argument("--wiki-id")
    wu.add_argument("--mail-notify", action="store_true", help="let Backlog email watchers about the edit")
    wu.set_defaults(func=_cmd_wiki_update)

    cc = sub.add_parser("cache-check", help="decide whether the cached master brief can be reused")
    cc.add_argument("--repo", required=True)
    cc.add_argument("--feature", required=True, help="feature name, e.g. the main screen")
    cc.add_argument("--anchors-file", required=True)
    cc.add_argument("--master-ref")
    cc.add_argument("--develop-ref")
    cc.set_defaults(func=_cmd_cache_check)

    cs = sub.add_parser("cache-save", help="store a scout brief's master section in the cache")
    cs.add_argument("--feature", required=True)
    cs.add_argument("--brief", required=True)
    cs.add_argument("--facts", required=True, help="scout-facts JSON from the same run")
    cs.set_defaults(func=_cmd_cache_save)

    cr = sub.add_parser("cache-review", help="mark the cache entry a report used as reviewed")
    cr.add_argument("--report", required=True)
    cr.add_argument("--by", required=True, help="tester name")
    cr.set_defaults(func=_cmd_cache_review)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (
        config.ConfigError,
        gitscope.GitError,
        report.ReportError,
        templates.TemplateError,
        decisions.DecisionsError,
        backlog_wiki.BacklogError,
        ValueError,
    ) as exc:
        print(f"testign: {exc}", file=sys.stderr)
        return 2
