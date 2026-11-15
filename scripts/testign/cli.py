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
    if not backlog.get("decisions_log_prefix"):
        raise ValueError("set backlog.decisions_log_prefix (e.g. \"QA/Decisions\") in ~/.testign-kit/config.json")
    return backlog


def _page_name(backlog: dict, slug: str) -> str:
    return f"{backlog['decisions_log_prefix'].rstrip('/')}/{slug}"


def _need_project(backlog: dict) -> str:
    if not backlog.get("project_key"):
        raise ValueError("set backlog.project_key in ~/.testign-kit/config.json")
    return backlog["project_key"]


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


def _diff(name: str, old: str, new: str) -> str:
    return "".join(difflib.unified_diff(_keepends(old), _keepends(new), f"{name} (now)", f"{name} (after append)"))


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _titles(rows: list[dict]) -> dict[str, str]:
    return {r["ticket"]: r["ticket_title"] for r in rows if r.get("ticket") and r.get("ticket_title")}


def _cmd_decisions_parse(args: argparse.Namespace) -> int:
    decisions.check_text_format(config.load()["backlog"].get("text_format", "markdown"))
    page = Path(args.file).read_text(encoding="utf-8")
    if args.index:
        return _emit({"index": decisions.parse_index(page)})
    return _emit(decisions.parse(page, config.load()["ticket_id_regex"]))


def _cmd_decisions_lookup(args: argparse.Namespace) -> int:
    backlog = _backlog_cfg()
    spec = _read_anchors_file(args.anchors_file)
    feature = decisions.page_slug(args.feature) if args.feature else None
    if args.index_file:
        index = Path(args.index_file).read_text(encoding="utf-8")
        found = decisions.lookup(index, spec["anchors"], args.ticket, feature)
        return _emit({"mode": "manual", **found, "page_names": [_page_name(backlog, p) for p in found["pages"]]})
    project = _need_project(backlog)
    listing = backlog_wiki.list_pages(project, backlog["decisions_log_prefix"])
    index_name = _page_name(backlog, decisions.INDEX)
    index = backlog_wiki.get(listing[index_name]["id"])["content"] if index_name in listing else ""
    found = decisions.lookup(index, spec["anchors"], args.ticket, feature)
    regex = config.load()["ticket_id_regex"]
    pages = []
    for slug in found["pages"]:
        name = _page_name(backlog, slug)
        if name not in listing:
            pages.append({"page": slug, "name": name, "exists": False})
            continue
        content = backlog_wiki.get(listing[name]["id"])["content"]
        pages.append({"page": slug, "name": name, "exists": True, "parsed": decisions.parse(content, regex)})
    return _emit({"mode": "api", "index_exists": index_name in listing, "matched": found["matched"], "pages": pages})


def _plan_wiki(backlog: dict, rows: list[dict]) -> dict:
    """Read the index and every page the rows need, compute the new contents and an approval hash."""
    project = _need_project(backlog)
    listing = backlog_wiki.list_pages(project, backlog["decisions_log_prefix"])
    index_name = _page_name(backlog, decisions.INDEX)

    def read(name: str) -> str:
        return backlog_wiki.get(listing[name]["id"])["content"] if name in listing else ""

    index = read(index_name)
    pages = {slug: read(_page_name(backlog, slug)) for slug in decisions.pages_needed(rows, index)}
    changed, new_index, result = decisions.apply_changes(
        pages, index, rows, config.load()["ticket_id_regex"], _titles(rows), project)
    writes = [(_page_name(backlog, slug), pages[slug], new) for slug, new in sorted(changed.items())]
    if new_index != index:
        writes.append((index_name, index, new_index))  # the index is written last
    approval = _sha(json.dumps([[n, listing.get(n, {}).get("updated"), new] for n, _old, new in writes],
                               ensure_ascii=False))
    return {"listing": listing, "writes": writes, "result": result, "approval": approval, "project": project}


def _cmd_wiki_append_preview(args: argparse.Namespace) -> int:
    backlog = _backlog_cfg()
    rows = _read_rows(args.rows)
    if args.pages_dir:
        folder = Path(args.pages_dir)

        def read(slug: str) -> str:
            f = folder / f"{slug}.md"
            return f.read_text(encoding="utf-8") if f.exists() else ""

        index = read(decisions.INDEX)
        pages = {slug: read(slug) for slug in decisions.pages_needed(rows, index)}
        changed, new_index, result = decisions.apply_changes(
            pages, index, rows, config.load()["ticket_id_regex"], _titles(rows), backlog.get("project_key", ""))
        if new_index != index:
            changed[decisions.INDEX] = new_index
        return _emit({"mode": "manual", **result, "pages": [
            {"page": slug, "name": _page_name(backlog, slug), "exists": (folder / f"{slug}.md").exists(),
             "diff": _diff(slug, pages.get(slug, index if slug == decisions.INDEX else ""), new), "new_content": new}
            for slug, new in changed.items()
        ]})
    plan = _plan_wiki(backlog, rows)
    return _emit({"mode": "api", **plan["result"], "approval": plan["approval"], "pages": [
        {"name": name, "exists": name in plan["listing"], "updated": plan["listing"].get(name, {}).get("updated"),
         "diff": _diff(name, old, new)}
        for name, old, new in plan["writes"]
    ]})


def _cmd_wiki_update(args: argparse.Namespace) -> int:
    backlog = _backlog_cfg()
    plan = _plan_wiki(backlog, _read_rows(args.rows))
    if plan["approval"] != args.approval:
        raise backlog_wiki.ConflictError(
            "the wiki pages or the content to write differ from the diff the tester approved. "
            "Run wiki-append-preview again and show the new diff."
        )
    if not plan["writes"]:
        return _emit({"written": [], **plan["result"], "reason": "every row is already in the log"})
    written = []
    for name, old, new in plan["writes"]:
        try:
            if name in plan["listing"]:
                saved = backlog_wiki.update(plan["listing"][name]["id"], new, plan["listing"][name]["updated"],
                                            expected_content=old, mail_notify=args.mail_notify)
            else:
                saved = backlog_wiki.create(plan["project"], name, new, mail_notify=args.mail_notify)
        except backlog_wiki.BacklogError as exc:
            done = ", ".join(w["name"] for w in written) or "none"
            raise backlog_wiki.BacklogError(
                f"{exc} (pages already written: {done}; rerun the preview: entries already on a page are "
                "skipped and missing index rows are added)"
            ) from None
        written.append(saved)
    return _emit({"written": written, **plan["result"]})


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
        "scout_model": (manifest or {}).get("scout_model"),
    })


def _cmd_cache_save(args: argparse.Namespace) -> int:
    facts = json.loads(Path(args.facts).read_text(encoding="utf-8"))
    brief = Path(args.brief).read_text(encoding="utf-8")
    folder = cache.entry_dir(facts["refs"]["root_commit"], args.feature)
    manifest = cache.save(folder, brief, facts, args.feature)
    return _emit({"cache_dir": str(folder), "cache_root": manifest["root_commit"],
                  "cache_feature": cache.slug(args.feature), "files": len(manifest["files"]),
                  "rows": list(manifest["rows"]), "scout_model": manifest["scout_model"]})


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

    dp = sub.add_parser("decisions-parse", help="parse a decisions page (or the index) saved to a file")
    dp.add_argument("--file", required=True)
    dp.add_argument("--index", action="store_true", help="the file is the decisions index page")
    dp.set_defaults(func=_cmd_decisions_parse)

    dl = sub.add_parser("decisions-lookup", help="find decisions for a survey through the index (feature pages + common)")
    dl.add_argument("--anchors-file", required=True)
    dl.add_argument("--ticket")
    dl.add_argument("--feature", help="the survey's feature (its page is always opened)")
    dl.add_argument("--index-file", help="index page saved from Backlog MCP; prints the pages to open, no API call")
    dl.set_defaults(func=_cmd_decisions_lookup)

    wp = sub.add_parser("wiki-append-preview", help="show the diffs that appending approved rows would make")
    wp.add_argument("--rows", required=True, help="JSON list of approved decision rows")
    wp.add_argument("--pages-dir", help="folder of pages saved from Backlog MCP as <slug>.md and index.md; no API call")
    wp.set_defaults(func=_cmd_wiki_append_preview)

    wu = sub.add_parser("wiki-update", help="write the approved diffs if no page changed since the preview")
    wu.add_argument("--rows", required=True)
    wu.add_argument("--approval", required=True, help="'approval' value from wiki-append-preview")
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
