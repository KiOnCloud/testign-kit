"""Command line entry for the testign skills. Every subcommand prints JSON on stdout."""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from . import (
    __version__, backlog_wiki, cache, config, decisions, figma_table, git_guard, gitscope, hashcheck, login_scenarios,
    report,
    login_recipe, setup_check, templates, trace, webtest, webtest_export, webtest_live, webtest_record, webtest_replay,
    webtest_sources, webtest_spec, webtest_suite, xlsx,
)
from .console import client as console_client
from .console import lifecycle


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
            purpose=args.purpose,
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
    found = trace.trace_for(Path(args.report), Path(args.xlsx), entry, args.sheet)
    sheet, summary = found["sheet"], found["summary"]
    result = {"report": args.report, "xlsx": args.xlsx, "sheet": sheet, **summary}
    if args.write_revision:
        new_body = report.replace_section(found["body"], 7, trace.section7(summary, Path(args.xlsx).name, sheet))
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


def _diff(name: str, old: str, new: str) -> str:
    return decisions.page_diff(name, old, new)


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
    approval = decisions.approval_hash([(n, listing.get(n, {}).get("updated"), new) for n, _old, new in writes])
    quotes = decisions.check_quotes(rows, backlog_wiki.domain_host(), _comment_text)
    decisions.refuse_bad_quotes(quotes)
    result = {**result, "quotes": quotes}
    return {"listing": listing, "writes": writes, "result": result, "approval": approval, "project": project}


def _comment_text(issue_key: str, comment_id: str) -> str | None:
    comment = backlog_wiki.get_comment(issue_key, comment_id)
    return None if comment is None else comment["content"]


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
         "diff": _diff(name, old, new), "old_content": old, "new_content": new}
        for name, old, new in plan["writes"]
    ]})


def _cmd_wiki_update(args: argparse.Namespace) -> int:
    if bool(args.job) != bool(args.session):
        raise ValueError("--job and --session go together")
    if args.job:
        # A console job writes only the approval the tester confirmed in the console.
        try:
            confirmed = console_client.approval(args.job, args.session).get("approval")
        except console_client.ClientError as exc:
            raise ValueError(f"cannot read the confirmed approval from the console: {exc.message}") from None
        if not confirmed or confirmed != args.approval:
            raise backlog_wiki.ConflictError(
                "the tester has not confirmed this diff in the console; ask with `console ask --from-preview` first"
            )
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


def _cmd_console_start(args: argparse.Namespace) -> int:
    return _emit(lifecycle.start(browser=not args.no_browser, skip_cloud_check=args.skip_cloud_check))


def _cmd_console_open(args: argparse.Namespace) -> int:
    return _emit(lifecycle.open_console(print_only=args.print))


def _cmd_console_status(_args: argparse.Namespace) -> int:
    return _emit(lifecycle.status())


def _cmd_console_stop(args: argparse.Namespace) -> int:
    return _emit(lifecycle.stop(force=args.force))


def _cmd_console_serve(args: argparse.Namespace) -> int:
    home = Path(args.home) if args.home else None
    return lifecycle.serve(home, port=args.port, instance=args.instance,
                           mode="foreground" if args.foreground else "detached")


def _agent_command(fn):
    """Agent commands print their result on stdout; errors as {error: {code, message}} on stderr, exit 2."""
    def run(args: argparse.Namespace) -> int:
        try:
            return _emit(fn(args))
        except console_client.ClientError as exc:
            print(json.dumps(exc.as_json(), ensure_ascii=False), file=sys.stderr)
            return 2
    return run


@_agent_command
def _cmd_console_wait(args: argparse.Namespace) -> dict:
    return console_client.wait(args.session, args.timeout)


@_agent_command
def _cmd_console_claim(args: argparse.Namespace) -> dict:
    return console_client.claim(args.job, args.session)


@_agent_command
def _cmd_console_progress(args: argparse.Namespace) -> dict:
    return console_client.progress(args.job, args.session, args.message)


@_agent_command
def _cmd_console_capabilities(args: argparse.Namespace) -> dict:
    return console_client.capabilities(args.session, {name: name in (args.has or []) for name in
                                                      ("chrome", "figma", "backlog")})


@_agent_command
def _cmd_console_ask(args: argparse.Namespace) -> dict:
    if args.question:
        ask = console_client.read_json(args.question)
    else:
        ask = console_client.ask_from_preview(console_client.read_json(args.from_preview))
    return console_client.ask(args.job, args.session, ask, args.timeout)


@_agent_command
def _cmd_console_done(args: argparse.Namespace) -> dict:
    report_text = None
    if args.report:
        try:
            report_text = Path(args.report).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise console_client.ClientError("bad-request", f"cannot read the report file: {type(exc).__name__}") from None
    return console_client.done(args.job, args.session, args.result, report_text)


@_agent_command
def _cmd_console_approval(args: argparse.Namespace) -> dict:
    return console_client.approval(args.job, args.session)


@_agent_command
def _cmd_console_queue(args: argparse.Namespace) -> dict:
    body = console_client.read_json(args.file)
    if not isinstance(body, dict):
        raise console_client.ClientError("bad-request", "the job file must hold a JSON object")
    return console_client.queue(body)


# web test runs --------------------------------------------------------------------------------
def _webtest_command(fn):
    """Web test commands print JSON; a console error becomes the one-line exit-2 message.

    A file that cannot be read (a capture, a staged case, a template workbook) is reported by its
    error type only, so stderr carries no path or traceback.
    """
    def run(args: argparse.Namespace) -> int:
        try:
            return _emit(fn(args))
        except console_client.ClientError as exc:
            raise webtest.WebtestError(f"console: {exc.code}: {exc.message}") from None
        except (OSError, zipfile.BadZipFile) as exc:
            raise webtest.WebtestError(f"a file of this run or its template cannot be read: "
                                       f"{type(exc).__name__}") from None
    return run


def _run_folder(args: argparse.Namespace) -> Path:
    return webtest.find_run(webtest.runs_root(), args.run)


def _read_json_file(path: str, what: str):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise webtest.WebtestError(f"cannot read the {what} file: {type(exc).__name__}") from None


def _job_args(args: argparse.Namespace) -> tuple[str, str]:
    if not args.job or not args.session:
        raise webtest.WebtestError("--job and --session are required")
    return args.job, args.session


def new_run_from_suite(suite_id: str, *, name: str | None, base_url: str, project: str, template: str | None,
                       tester: str, home: Path | None = None, browsers: list[str] | None = None) -> dict:
    """A run copied from a ready suite onto one environment (the console calls the same helper)."""
    cfg = config.load(home)
    return webtest_suite.create_run(webtest.runs_root(cfg), suite_id, name=name, base_url=base_url, project=project,
                                    template=template, tester=tester, home=home, report_lang=cfg.get("lang"),
                                    browsers=browsers)


def _suite_env() -> webtest_sources.Env:
    return webtest_sources.Env.from_config(config.load())


def _suite_folder(args: argparse.Namespace) -> Path:
    return webtest_suite.find_suite(webtest.runs_root(), args.suite)


def _suite_command(fn):
    """Suite commands print JSON; a broken case rule also prints every field's message."""
    wrapped = _webtest_command(fn)

    def run(args: argparse.Namespace) -> int:
        try:
            return wrapped(args)
        except webtest_suite.CaseError as exc:
            problems = getattr(exc, "problems", None) or {exc.case or "case": exc.errors}
            raise webtest.WebtestError(f"{exc} ({json.dumps(problems, ensure_ascii=False)})") from None
        except webtest_sources.SourceError as exc:
            raise webtest.WebtestError(f"{exc.code}: {exc}") from None
    return run


@_suite_command
def _cmd_webtest_new(args: argparse.Namespace) -> dict:
    return new_run_from_suite(args.suite, name=args.name, base_url=args.base_url, project=args.project,
                              template=args.template, tester=args.tester, browsers=args.browser)


def _figma_rows(args: argparse.Namespace, source: dict) -> list[dict]:
    if source.get("kind") != "figma" or not source.get("file") or not source.get("node"):
        raise webtest.WebtestError("this source is not a Figma table")
    try:
        context = Path(args.context).read_text(encoding="utf-8")
        metadata = Path(args.metadata).read_text(encoding="utf-8")
    except (OSError, ValueError) as exc:
        raise webtest.WebtestError(f"cannot read a saved Figma result: {type(exc).__name__}") from None
    try:
        return figma_table.parse(context, metadata, file_key=source["file"], table_node=source["node"])
    except figma_table.TableError as exc:
        raise webtest.WebtestError(f"read the table row by row: {exc}") from None


def _suite_generate_job(args: argparse.Namespace) -> str:
    """The open suite-generate job of this agent session that writes ``--suite``."""
    job, session = _job_args(args)
    info = console_client.Reader().job(job, session)
    if info.get("kind") != "suite-generate" or info.get("suite") != args.suite:
        raise webtest.WebtestError(f"job {job} does not generate suite {args.suite}")
    return job


@_suite_command
def _cmd_webtest_table(args: argparse.Namespace) -> dict:
    job = _suite_generate_job(args)
    folder = _suite_folder(args)
    rows = _figma_rows(args, webtest_suite.load(folder).get("source") or {})
    return webtest_suite.stage_rows(folder, rows, Path(args.captures) if args.captures else None, job)


@_webtest_command
def _cmd_webtest_recover(args: argparse.Namespace) -> dict:
    job, session = _job_args(args)
    return webtest.recover(_run_folder(args), console_client.Reader(), job, session)


@_webtest_command
def _cmd_webtest_next(args: argparse.Namespace) -> dict:
    job, session = _job_args(args)
    return webtest.next_row(_run_folder(args), console_client.Reader(), job, session)


@_webtest_command
def _cmd_webtest_row(args: argparse.Namespace) -> dict:
    return webtest.record_row(_run_folder(args), args.row, _read_json_file(args.result, "result"))


@_webtest_command
def _cmd_webtest_evidence(args: argparse.Namespace) -> dict:
    folder = _run_folder(args)
    if args.file:
        return webtest.copy_file_evidence(folder, args.row, Path(args.file))
    images = webtest.server_images_dir(None, folder.name)
    try:
        found = [p for p in images.iterdir() if p.is_file() and p.stem == args.from_image]
    except OSError:
        found = []
    if not webtest.IMAGE_ID_RE.match(args.from_image or "") or len(found) != 1:
        raise webtest.WebtestError("no uploaded image with that id for this run")
    return webtest.add_evidence(folder, args.row, found[0].read_bytes(), "tester")


@_webtest_command
def _cmd_webtest_requeue(args: argparse.Namespace) -> dict:
    return webtest.requeue(_run_folder(args), args.row, args.reason, signed_out=args.signed_out)


@_webtest_command
def _cmd_webtest_park(args: argparse.Namespace) -> dict:
    return webtest.park(_run_folder(args), args.row, _read_json_file(args.question, "question"))


@_webtest_command
def _cmd_webtest_resolve(args: argparse.Namespace) -> dict:
    job, session = _job_args(args)
    folder = _run_folder(args)
    wait = (args.timeout if args.timeout is not None else 100.0) if args.wait else None
    return webtest.resolve(folder, console_client.Reader(), job, session,
                           webtest.server_images_dir(None, folder.name), wait=wait)


@_webtest_command
def _cmd_webtest_signed_in(args: argparse.Namespace) -> dict:
    job, session = _job_args(args)
    return webtest.signed_in(_run_folder(args), console_client.Reader(), job, session, args.scenario)


@_webtest_command
def _cmd_webtest_close(args: argparse.Namespace) -> dict:
    return webtest.close(_run_folder(args), console_client.Reader().job_open, stopped=args.stopped)


@_webtest_command
def _cmd_webtest_status(args: argparse.Namespace) -> dict:
    return webtest.status(_run_folder(args))


@_webtest_command
def _cmd_webtest_columns(args: argparse.Namespace) -> dict:
    folder = _run_folder(args)
    return webtest_export.columns_view(folder, webtest.load(folder), args.template)


@_webtest_command
def _cmd_webtest_export(args: argparse.Namespace) -> dict:
    folder = _run_folder(args)
    if args.apply_pending:
        job, session = _job_args(args)
        webtest.resolve(folder, console_client.Reader(), job, session, webtest.server_images_dir(None, folder.name))
    return webtest_export.export(folder, webtest.load(folder))


# web test suites ------------------------------------------------------------------------------


@_suite_command
def _cmd_suite_new(args: argparse.Namespace) -> dict:
    payload = _read_json_file(args.input, "source input") if args.input else {}
    if not isinstance(payload, dict):
        raise webtest.WebtestError("the source input file must hold a JSON object")
    upload = Path(args.file) if args.file else None
    if upload is not None:
        payload.setdefault("file_name", upload.name)
    if args.figma_url:
        payload["figma_url"] = args.figma_url
    if args.ticket:
        payload["ticket"] = args.ticket
    return webtest_suite.new_suite(webtest.runs_root(), name=args.name, kind=args.kind, payload=payload,
                                   env=_suite_env(), project=args.project, case_lang=args.case_lang, upload=upload)


@_suite_command
def _cmd_suite_show(args: argparse.Namespace) -> dict:
    return webtest_suite.show(_suite_folder(args), _suite_env())


@_suite_command
def _cmd_suite_list(_args: argparse.Namespace) -> dict:
    out = []
    for _sid, folder in sorted(webtest_suite.list_suites(webtest.runs_root()).items()):
        try:
            out.append(webtest_suite.summary(webtest_suite.load(folder)))
        except webtest.WebtestError:
            continue
    return {"suites": out}


# The command line is the agent's: its case edits follow the agent's rules, and any edit sends a ready
# suite back to review. Only the tester confirms a suite, in the console.
@_suite_command
def _cmd_suite_case_add(args: argparse.Namespace) -> dict:
    return webtest_suite.add_case(_suite_folder(args), _read_json_file(args.file, "case"), by="agent")


@_suite_command
def _cmd_suite_case_update(args: argparse.Namespace) -> dict:
    return webtest_suite.update_case(_suite_folder(args), args.case, _read_json_file(args.file, "case"), by="agent")


@_suite_command
def _cmd_suite_case_delete(args: argparse.Namespace) -> dict:
    return webtest_suite.delete_cases(_suite_folder(args), list(args.case))


@_suite_command
def _cmd_suite_stage(args: argparse.Namespace) -> dict:
    job, session = _job_args(args)
    cases = _read_json_file(args.file, "stage")
    if not isinstance(cases, list):
        raise webtest.WebtestError('the stage file must be a list of cases: [{"content": ...}, ...]')
    return console_client.suite_stage(args.suite, job, session, cases)


@_suite_command
def _cmd_suite_generated(args: argparse.Namespace) -> dict:
    job, session = _job_args(args)
    return console_client.suite_generated(args.suite, job, session)


@_webtest_command
def _cmd_login_scenario_list(args: argparse.Namespace) -> dict:
    return {"project": args.project, "scenarios": login_scenarios.list_scenarios(None, args.project)}


@_webtest_command
def _cmd_login_scenario_save(args: argparse.Namespace) -> dict:
    return login_scenarios.save_draft(None, args.project, _read_json_file(args.file, "scenario"))


@_webtest_command
def _cmd_login_scenario_remove(args: argparse.Namespace) -> dict:
    return login_scenarios.remove(None, login_scenarios.check_name(args.project, "project"),
                                  login_scenarios.check_name(args.name, "scenario name"))


def _add_webtest_parser(sub) -> None:
    def cmd(name: str, fn, help_text: str, *, run: bool = True, job: bool = False):
        p = sub.add_parser(name, help=help_text)
        if run:
            p.add_argument("--run", required=True, help="run id (W<yyyymmdd>-<hhmm>-<slug>)")
        if job:
            p.add_argument("--job", required=True, help="console job id")
            p.add_argument("--session", required=True, help="agent session id")
        p.set_defaults(func=fn)
        return p

    p = cmd("webtest-new", _cmd_webtest_new, "create a web test run from a ready suite, on one environment",
            run=False)
    p.add_argument("--suite", required=True, help="a ready suite to copy onto one environment")
    p.add_argument("--base-url", required=True, help="the environment's URL, on the project's hosts")
    p.add_argument("--project", required=True, help="the project of the Projects screen")
    p.add_argument("--template", help="the result template (default: the default template)")
    p.add_argument("--tester", required=True, help="the tester's name")
    p.add_argument("--name", help="run name (default: the suite's name)")
    p.add_argument("--browser", action="append", choices=webtest.BROWSERS,
                   help="a browser replay runs the rows in; repeat (default: chromium)")
    p = cmd("webtest-table", _cmd_webtest_table,
            "write the rows of one saved get_design_context of a Figma table as cases of a generating suite",
            run=False)
    p.add_argument("--suite", required=True, help="suite id of a generating Figma suite")
    p.add_argument("--job", required=True, help="the suite-generate job id")
    p.add_argument("--session", required=True, help="agent session id")
    p.add_argument("--context", required=True, help="the file Claude Code saved the get_design_context result to")
    p.add_argument("--metadata", required=True, help="the file Claude Code saved get_metadata of the table to")
    out = p.add_mutually_exclusive_group(required=True)
    out.add_argument("--urls", action="store_true", help="print the capture URLs of rows not staged yet")
    out.add_argument("--captures", help="folder of downloaded captures named <row>.png or <row>.jpg: stage the rows")
    cmd("webtest-recover", _cmd_webtest_recover, "requeue rows of finished jobs at the start of a run job", job=True)
    cmd("webtest-next", _cmd_webtest_next, "take the next queued row for the worker", job=True)
    p = cmd("webtest-row", _cmd_webtest_row, "record pass or fail for the running row")
    p.add_argument("--row", required=True)
    p.add_argument("--result", required=True, help='JSON file: {"verdict": "pass"|"fail", "actual", "url"}')
    p = cmd("webtest-evidence", _cmd_webtest_evidence, "copy an evidence image to the row's current attempt")
    p.add_argument("--row", required=True)
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="the path the Chrome tool reported for a saved screenshot")
    src.add_argument("--from-image", help="id of an image the tester uploaded in the console")
    p = cmd("webtest-requeue", _cmd_webtest_requeue, "blocked by the environment: back to the queue")
    p.add_argument("--row", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--signed-out", action="store_true", help="the page asked to sign in: clear the signed-in scenario")
    p = cmd("webtest-park", _cmd_webtest_park, "park the running row with a question for the tester")
    p.add_argument("--row", required=True)
    p.add_argument("--question", required=True, help='JSON file: {"body": "..."}')
    p = cmd("webtest-resolve", _cmd_webtest_resolve, "apply the tester's answers and results from the console",
            job=True)
    p.add_argument("--wait", action="store_true", help="hold until something new arrives")
    p.add_argument("--timeout", type=float, help="seconds to hold with --wait (default 100)")
    p = cmd("webtest-signed-in", _cmd_webtest_signed_in, "store the tester's sign-in answer for a scenario", job=True)
    p.add_argument("--scenario", required=True)
    p = cmd("webtest-close", _cmd_webtest_close, "turn every open row into not-run with its reason")
    p.add_argument("--stopped", action="store_true", help="the tester ended the run")
    cmd("webtest-status", _cmd_webtest_status, "counts by state and the rows")
    p = cmd("webtest-columns", _cmd_webtest_columns, "first-guess column plan with three sample rows")
    p.add_argument("--template", help="registered template (default: the run's)")
    p = cmd("webtest-export", _cmd_webtest_export, "write a new workbook and a Markdown report")
    p.add_argument("--apply-pending", action="store_true", help="apply the tester's pending results first")
    p.add_argument("--job")
    p.add_argument("--session")

    def suite_cmd(name: str, fn, help_text: str, *, suite: bool = True):
        p = sub.add_parser(name, help=help_text)
        if suite:
            p.add_argument("--suite", required=True, help="suite id (S<yyyymmdd>-<hhmm>-<slug>)")
        p.set_defaults(func=fn)
        return p

    p = suite_cmd("suite-new", _cmd_suite_new, "create a test suite from a source (figma, backlog, excel, manual)",
                  suite=False)
    p.add_argument("--name", required=True)
    p.add_argument("--kind", required=True, choices=list(webtest_sources.kinds()))
    p.add_argument("--project", help="project of the Projects & hosts screen")
    p.add_argument("--case-lang", choices=list(webtest_suite.CASE_LANGS), help="language the cases are written in")
    p.add_argument("--figma-url", help="figma: the table's design URL with a node-id")
    p.add_argument("--ticket", help="backlog: the ticket whose latest survey report the cases come from")
    p.add_argument("--file", help="excel: the workbook to read")
    p.add_argument("--input", help='JSON file with the source input (e.g. {"template": ..., "sheet": ...})')
    suite_cmd("suite-show", _cmd_suite_show, "a suite with its cases and its coverage of the source rows")
    suite_cmd("suite-list", _cmd_suite_list, "every suite with its state and case count", suite=False)
    p = suite_cmd("suite-case-add", _cmd_suite_case_add, "add a case to a suite")
    p.add_argument("--file", required=True, help='JSON file: {"content", "steps", "expected", "class", ...}')
    p = suite_cmd("suite-case-update", _cmd_suite_case_update, "change fields of one case")
    p.add_argument("--case", required=True)
    p.add_argument("--file", required=True, help="JSON file with the fields to change")
    p = suite_cmd("suite-case-delete", _cmd_suite_case_delete, "delete cases of a suite")
    p.add_argument("--case", required=True, action="append", help="case id; repeat for several")
    p = suite_cmd("suite-stage", _cmd_suite_stage, "write cases of a suite from its open suite-generate job")
    p.add_argument("--job", required=True, help="the suite-generate job id")
    p.add_argument("--session", required=True, help="agent session id")
    p.add_argument("--file", required=True,
                   help='JSON file: [{"case"?, "content", "trace", "class", "runner", "scenario", "screen", ...}]')
    p = suite_cmd("suite-generated", _cmd_suite_generated, "every case is written: hand the suite to the tester")
    p.add_argument("--job", required=True, help="the suite-generate job id")
    p.add_argument("--session", required=True, help="agent session id")

    p = cmd("login-scenario-list", _cmd_login_scenario_list, "a project's login scenarios and their approval",
            run=False)
    p.add_argument("--project", required=True)
    p = cmd("login-scenario-save", _cmd_login_scenario_save,
            "save a login checklist draft; the tester approves it in the console", run=False)
    p.add_argument("--project", required=True)
    p.add_argument("--file", required=True,
                   help='JSON file: {"name", "label", "login_url", "signout_url", "steps", "signed_in_check", '
                        '"account_hint"}')
    p = cmd("login-scenario-remove", _cmd_login_scenario_remove, "remove a login scenario", run=False)
    p.add_argument("--project", required=True)
    p.add_argument("--name", required=True)


# record once, replay with Playwright, Login Recipes ---------------------------------------------
def _mode_job(args: argparse.Namespace, mode: str) -> str:
    """The open webtest-run job of this session for ``--run`` in ``mode`` (record or replay)."""
    job, session = _job_args(args)
    view = console_client.Reader().job(job, session)
    params = view.get("params") or {}
    if (view.get("kind") != "webtest-run" or view.get("state") not in ("running", "needs-input")
            or params.get("run") != args.run or params.get("mode") != mode):
        raise webtest.WebtestError(f"job {job} is not an open {mode} job of this session for run {args.run}")
    return job


@_webtest_command
def _cmd_record_start(args: argparse.Namespace) -> dict:
    _mode_job(args, "record")
    return webtest_record.start(_run_folder(args))


@_webtest_command
def _cmd_record_open(args: argparse.Namespace) -> dict:
    return webtest_record.open_row(_run_folder(args), args.row, restart=args.restart)


@_webtest_command
def _cmd_record_step(args: argparse.Namespace) -> dict:
    return webtest_record.step(_run_folder(args), args.row, _read_json_file(args.step, "step"))


@_webtest_command
def _cmd_record_done(args: argparse.Namespace) -> dict:
    return webtest_record.done(_run_folder(args), args.row)


@_webtest_command
def _cmd_record_give_up(args: argparse.Namespace) -> dict:
    return webtest_record.give_up(_run_folder(args), args.row, args.reason)


@_webtest_command
def _cmd_record_finish(args: argparse.Namespace) -> dict:
    job = _mode_job(args, "record")
    return webtest_record.finish(_run_folder(args), job)


@_webtest_command
def _cmd_replay_plan(args: argparse.Namespace) -> dict:
    return webtest_replay.plan(_run_folder(args))


@_webtest_command
def _cmd_replay(args: argparse.Namespace) -> dict:
    # With --job: the console's replay job. Without: nobody at the console (a scheduler); see
    # webtest_replay.replay for what keeps it from racing a job on the same run.
    job = _mode_job(args, "replay") if args.job or args.session else None
    return webtest_replay.replay(_run_folder(args), job)


@_suite_command
def _cmd_replay_new(args: argparse.Namespace) -> dict:
    """For a scheduler: a new run from the suite, every row with a reviewed spec replayed, then exported
    when nothing is left open. Rows without a spec stay queued for a run in Chrome."""
    suite_folder = _suite_folder(args)
    spec = webtest_spec.load(suite_folder)
    if not webtest_spec.is_reviewed(spec):
        raise webtest.WebtestError("the suite's replay spec is not reviewed; review it on the suite's Replay spec tab")
    made = new_run_from_suite(args.suite, name=args.name, base_url=args.base_url, project=args.project,
                              template=args.template, tester=args.tester, browsers=args.browser)
    folder = webtest.find_run(webtest.runs_root(config.load()), made["run"])
    result = webtest_replay.replay(folder, None)
    out = {"run": made["run"], "counts": webtest.counts(webtest.load(folder)),
           "results": result["results"], "left": result["left"]}
    if args.export and not webtest.open_rows(webtest.load(folder)):
        webtest.close(folder, lambda _job: False)
        out["export"] = webtest_export.export(folder, webtest.load(folder))
    return out


@_webtest_command
def _cmd_spec_check(args: argparse.Namespace) -> dict:
    return webtest_replay.check(_run_folder(args))


@_webtest_command
def _cmd_spec_show(args: argparse.Namespace) -> dict:
    folder = _suite_folder(args)
    return webtest_spec.view(folder, webtest_suite.load(folder))


@_webtest_command
def _cmd_recipe_save(args: argparse.Namespace) -> dict:
    return login_recipe.save(None, args.project, args.scenario, _read_json_file(args.file, "recipe"))


@_webtest_command
def _cmd_recipe_show(args: argparse.Namespace) -> dict:
    return login_recipe.view(None, login_scenarios.check_name(args.project, "project"),
                             login_scenarios.check_name(args.scenario, "scenario"))


@_webtest_command
def _cmd_recipe_test(args: argparse.Namespace) -> dict:
    project = login_scenarios.check_name(args.project, "project")
    scenario = login_scenarios.check_name(args.scenario, "scenario")
    hosts = login_scenarios.get_project(None, project)
    result = webtest_live.test_recipe(None, project, scenario, hosts["hosts"] + hosts["signin_hosts"])
    return {**result, "recipe": login_recipe.view(None, project, scenario)}


def _cmd_profile_set(args: argparse.Namespace) -> int:
    """Typed by the tester in their own terminal: no echo, never from a pipe, never printed."""
    import getpass  # noqa: PLC0415

    if not sys.stdin.isatty():
        raise webtest.WebtestError("profile-set reads the values from your keyboard; run it in your own terminal")
    print("Only a dedicated test account of a staging environment goes in a profile.", file=sys.stderr)
    answer = input("Is this a dedicated staging test account? [y/N] ").strip().lower()
    if answer not in ("y", "yes"):
        raise webtest.WebtestError("nothing saved: use a dedicated staging test account")
    values = {}
    for key in args.key:
        values[key] = getpass.getpass(f"{key}: ")
    return _emit(login_recipe.set_profile(None, args.project, args.profile, values))


@_webtest_command
def _cmd_profile_list(args: argparse.Namespace) -> dict:
    return {"profiles": login_recipe.list_profiles(None, args.project)}


def _cmd_profile_remove(args: argparse.Namespace) -> int:
    return _emit(login_recipe.remove_profile(None, args.project, args.profile))


def _cmd_setup(args: argparse.Namespace) -> int:
    out = setup_check.check(webtest=args.webtest or bool(args.browser), browsers=args.browser, install=args.install)
    _emit(out)
    return 0 if out["ok"] else 1


def _add_replay_parser(sub) -> None:
    p = sub.add_parser("setup", help="check (and with --install, install) what testign needs on this computer")
    p.add_argument("--webtest", action="store_true", help="also check Playwright and Chromium for record and replay")
    p.add_argument("--browser", action="append", choices=webtest.BROWSERS, help="a browser to check; repeat")
    p.add_argument("--install", action="store_true",
                   help="pip install --user missing packages and playwright install missing browsers")
    p.set_defaults(func=_cmd_setup)

    def cmd(name: str, fn, help_text: str, *, run: bool = True, row: bool = False, job: bool = False):
        p = sub.add_parser(name, help=help_text)
        if run:
            p.add_argument("--run", required=True, help="run id (W<yyyymmdd>-<hhmm>-<slug>)")
        if row:
            p.add_argument("--row", required=True)
        if job:
            p.add_argument("--job", required=True, help="console job id")
            p.add_argument("--session", required=True, help="agent session id")
        p.set_defaults(func=fn)
        return p

    cmd("webtest-record-start", _cmd_record_start, "start recording the run's eligible rows (mode record)", job=True)
    p = cmd("webtest-record-open", _cmd_record_open, "replay a row's recorded steps and show the page", row=True)
    p.add_argument("--restart", action="store_true", help="drop the row's steps and record it again")
    p = cmd("webtest-record-step", _cmd_record_step, "try one step; a passing step is recorded", row=True)
    p.add_argument("--step", required=True, help='JSON file: {"action", "locator"?, "value"?, "timeout_ms"?}')
    cmd("webtest-record-done", _cmd_record_done, "close a row whose steps passed", row=True)
    p = cmd("webtest-record-give-up", _cmd_record_give_up, "leave a row out of the spec (it stays queued)", row=True)
    p.add_argument("--reason", required=True)
    cmd("webtest-record-finish", _cmd_record_finish, "save the spec and write the recorded rows' results", job=True)
    cmd("webtest-replay-plan", _cmd_replay_plan, "which queued rows a replay would run, and why not the others")
    p = cmd("webtest-replay", _cmd_replay,
            "replay the queued rows from the suite's reviewed spec (mode replay job, or with no job for a scheduler)")
    p.add_argument("--job", help="console job id (mode replay); leave out when nobody is at the console")
    p.add_argument("--session", help="agent session id, with --job")
    p = cmd("webtest-replay-new", _cmd_replay_new,
            "for a scheduler: a new run from a suite with a reviewed spec, replayed (and exported)", run=False)
    p.add_argument("--suite", required=True)
    p.add_argument("--base-url", required=True)
    p.add_argument("--project", required=True)
    p.add_argument("--tester", required=True, help="the name the run is recorded under")
    p.add_argument("--template")
    p.add_argument("--name", help="run name (default: the suite's name)")
    p.add_argument("--browser", action="append", choices=webtest.BROWSERS, help="repeat (default: chromium)")
    p.add_argument("--export", action="store_true", help="close and export the run when no row is left open")
    cmd("webtest-spec-check", _cmd_spec_check, "replay the whole spec on this run's environment; writes no result")
    p = cmd("webtest-spec-show", _cmd_spec_show, "a suite's spec beside its cases", run=False)
    p.add_argument("--suite", required=True)
    for name, fn, text in (("login-recipe-save", _cmd_recipe_save, "save a scenario's sign-in steps (placeholders only)"),
                           ("login-recipe-show", _cmd_recipe_show, "a recipe, its test and approval (never a value)"),
                           ("login-recipe-test", _cmd_recipe_test, "sign in with the recipe and save the session")):
        p = cmd(name, fn, text, run=False)
        p.add_argument("--project", required=True)
        p.add_argument("--scenario", required=True)
        if name == "login-recipe-save":
            p.add_argument("--file", required=True, help='JSON file: {"profile", "login_url", "steps"}')
    p = cmd("profile-set", _cmd_profile_set, "the tester types a staging test account's values (own terminal only)",
            run=False)
    p.add_argument("--project", required=True)
    p.add_argument("--profile", required=True)
    p.add_argument("--key", action="append", required=True, help="a value to type, such as username; repeat")
    p = cmd("profile-list", _cmd_profile_list, "a project's profiles and their keys (never a value)", run=False)
    p.add_argument("--project", required=True)
    p = cmd("profile-remove", _cmd_profile_remove, "delete a profile", run=False)
    p.add_argument("--project", required=True)
    p.add_argument("--profile", required=True)


def _add_console_parser(sub) -> None:
    cp = sub.add_parser("console", help="local console in the browser (start, open, status, stop)")
    csub = cp.add_subparsers(dest="console_command", required=True,
                             metavar="{start,open,status,stop,wait,claim,progress,ask,done,approval,queue}")

    st = csub.add_parser("start", help="start the console server, or reuse the running one, and open the browser")
    st.add_argument("--no-browser", action="store_true", help="do not open a browser (use `console open` later)")
    st.add_argument("--skip-cloud-check", action="store_true", help="start even in a cloud session")
    st.set_defaults(func=_cmd_console_start)

    op = csub.add_parser("open", help="open the console in the browser with a fresh single-use link")
    op.add_argument("--print", action="store_true", help="print the single-use URL instead of opening a browser")
    op.set_defaults(func=_cmd_console_open)

    ss = csub.add_parser("status", help="whether the console server is running")
    ss.set_defaults(func=_cmd_console_status)

    sp = csub.add_parser("stop", help="stop the console server")
    sp.add_argument("--force", action="store_true", help="stop even while jobs are open (they fail)")
    sp.set_defaults(func=_cmd_console_stop)

    held_help = "seconds to hold the call (default 100, inside the 2-minute Bash limit; server cap 540)"
    wt = csub.add_parser("wait", help="hold until the console offers a job (agent side)")
    wt.add_argument("--session", required=True, help="session id printed by `console start`")
    wt.add_argument("--timeout", type=float, help=held_help)
    wt.set_defaults(func=_cmd_console_wait)

    cl = csub.add_parser("claim", help="take the offered job (agent side)")
    cl.add_argument("job")
    cl.add_argument("--session", required=True)
    cl.set_defaults(func=_cmd_console_claim)

    pg = csub.add_parser("progress", help="report a step of the running job (agent side)")
    pg.add_argument("job")
    pg.add_argument("--session", required=True)
    pg.add_argument("--message", required=True, help="one line in the job's ui_lang")
    pg.set_defaults(func=_cmd_console_progress)

    ca = csub.add_parser("capabilities", help="tell the console which tools this session has (agent side)")
    ca.add_argument("--session", required=True)
    ca.add_argument("--has", action="append", choices=["chrome", "figma", "backlog"],
                    help="a tool this session has: Claude in Chrome, a Figma MCP server, a Backlog MCP server; repeat")
    ca.set_defaults(func=_cmd_console_capabilities)

    ak = csub.add_parser("ask", help="ask the tester through the console and hold for the answer (agent side)")
    ak.add_argument("job")
    ak.add_argument("--session", required=True)
    src = ak.add_mutually_exclusive_group(required=True)
    src.add_argument("--question", help="ask file (questions or review-rows)")
    src.add_argument("--from-preview", help="wiki-append-preview output: confirm-diff, or paste-pages in manual mode")
    ak.add_argument("--timeout", type=float, help=held_help)
    ak.set_defaults(func=_cmd_console_ask)

    dn = csub.add_parser("done", help="close the job with a result (agent side)")
    dn.add_argument("job")
    dn.add_argument("--session", required=True)
    dn.add_argument("--result", required=True, choices=["done", "failed"])
    dn.add_argument("--report", help="short result summary (Markdown) shown in the console, in the job's ui_lang")
    dn.set_defaults(func=_cmd_console_done)

    ap = csub.add_parser("approval", help="the wiki approval the tester confirmed for this job (agent side)")
    ap.add_argument("job")
    ap.add_argument("--session", required=True)
    ap.set_defaults(func=_cmd_console_approval)

    qu = csub.add_parser("queue", help="queue a suite-generate or webtest-run job from the chat (agent side)")
    qu.add_argument("--file", required=True,
                    help='JSON file: {"kind": "suite-generate"|"webtest-run", "ui_lang", ...the kind\'s fields}')
    qu.set_defaults(func=_cmd_console_queue)

    sv = csub.add_parser("serve")
    sv.add_argument("--port", type=int)
    sv.add_argument("--instance")
    sv.add_argument("--home")
    sv.add_argument("--foreground", action="store_true",
                    help="run in this process (for the harness's background mode)")
    sv.set_defaults(func=_cmd_console_serve)


def _cmd_guard(args: argparse.Namespace) -> int:
    if args.guard_command == "enable":
        return _emit(git_guard.enable(args.repo))
    if args.guard_command == "disable":
        return _emit(git_guard.disable(args.repo))
    return _emit(git_guard.status(args.repo))


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
    tr.add_argument("--purpose", choices=list(templates.PURPOSES), default="testcase",
                    help="testcase (needs the 備考/trace column) or webtest (web test run export)")
    tr.set_defaults(func=_cmd_template_register)

    tl = sub.add_parser("template-list", help="list registered templates with their purpose")
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
    wu.add_argument("--job", help="console job id: refuse unless the tester confirmed this approval in the console")
    wu.add_argument("--session", help="agent session id (with --job)")
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

    gd = sub.add_parser("guard", help="the git write guard for customer repositories (enable, disable, status)")
    gsub = gd.add_subparsers(dest="guard_command", required=True)
    for name, text in (("enable", "put the repository holding --repo on the guard list"),
                       ("disable", "take the repository off the guard list"),
                       ("status", "show the guard list; with --repo, whether that repository is on it")):
        g = gsub.add_parser(name, help=text)
        g.add_argument("--repo", required=name != "status", help="a folder inside the customer repository")
        g.set_defaults(func=_cmd_guard)

    _add_webtest_parser(sub)
    _add_replay_parser(sub)
    _add_console_parser(sub)
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
        lifecycle.ConsoleError,
        ValueError,
    ) as exc:
        print(f"testign: {exc}", file=sys.stderr)
        return 2
