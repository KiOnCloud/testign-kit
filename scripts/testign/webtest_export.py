"""Column plan and export of a web test run: a new workbook from a registered template and a report.

The column plan maps case and result fields to template columns by letter. The template's roles
give the first guess; the result columns (verdict, actual, executed date) are matched against a
small synonym list kept here, so the registry's roles and synonyms stay as they are. Fields with no
column are proposed as new columns to the right of the last header. The registered template is
only ever read; every export writes new files.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from . import templates, webtest, xlsx
from .webtest import WebtestError

CASE_FIELDS = ("no", "type", "content", "creator", "screen", "viewport", "kind", "class", "reason", "scenario",
               "runner", "preconditions", "steps", "expected", "target_node")
RESULT_FIELDS = ("verdict", "actual", "evidence", "executed_at", "by")
FIELDS = CASE_FIELDS + RESULT_FIELDS
ROLE_FIELD = {"no": "no", "item": "content", "steps": "steps", "expected": "expected", "evidence": "evidence"}
RESULT_SYNONYMS = {
    "verdict": ["結果", "判定", "合否", "result", "kết quả"],
    "actual": ["実際の結果", "実施結果", "actual", "actualresult", "thực tế", "kết quả thực tế"],
    "executed_at": ["実施日", "実施日時", "executed", "executedat", "ngày chạy"],
}
PROPOSED_NEW = ("verdict", "actual", "executed_at", "evidence", "screen")
LABEL_KEYS = ("pass", "fail", "not-run", "not-applicable", "manual")
OPEN = ("draft", *webtest.OPEN_STATES)

HEADERS = {
    "en": {"verdict": "Result", "actual": "Actual", "executed_at": "Executed", "evidence": "Evidence",
           "screen": "Screen", "scenario": "Scenario", "by": "By", "reason": "Reason", "steps": "Steps",
           "expected": "Expected", "preconditions": "Preconditions", "kind": "Kind", "class": "Class",
           "runner": "Runner", "viewport": "Viewport", "type": "Type", "creator": "Creator",
           "target_node": "Figma node", "no": "No", "content": "Content"},
    "ja": {"verdict": "結果", "actual": "実際の結果", "executed_at": "実施日", "evidence": "エビデンス",
           "screen": "画面", "scenario": "ログインシナリオ", "by": "実施者", "reason": "理由", "steps": "手順",
           "expected": "期待結果", "preconditions": "前提条件", "kind": "種類", "class": "分類",
           "runner": "実施", "viewport": "表示幅", "type": "種別", "creator": "作成者",
           "target_node": "Figmaノード", "no": "No", "content": "内容"},
    "vi": {"verdict": "Kết quả", "actual": "Thực tế", "executed_at": "Ngày chạy", "evidence": "Bằng chứng",
           "screen": "Màn hình", "scenario": "Kịch bản đăng nhập", "by": "Người chạy", "reason": "Lý do",
           "steps": "Các bước", "expected": "Kết quả mong đợi", "preconditions": "Tiền điều kiện",
           "kind": "Loại", "class": "Phân loại", "runner": "Người chạy", "viewport": "Khổ màn hình",
           "type": "Kiểu", "creator": "Người tạo", "target_node": "Node Figma", "no": "No", "content": "Nội dung"},
}


def _norm(value: Any) -> str:
    return re.sub(r"[\s_　]+", "", str(value or "")).lower()


def _result_field(header: str) -> str | None:
    text = _norm(header)
    for field, names in RESULT_SYNONYMS.items():
        for name in names:
            n = _norm(name)
            if text == n or (len(n) > 2 and text.startswith(n)):
                return field
    return None


def _index(letter: str) -> int:
    return templates._col_index(letter)


def _letter(index: int) -> str:
    return templates._col_letter(index)


# the template's facts -------------------------------------------------------------------------
def sheet_facts(entry: dict) -> dict:
    """Headers, last header column, merged header ranges and list dropdowns of the template sheet."""
    wb = templates._openpyxl().load_workbook(entry["path"])
    if entry["sheet"] not in wb.sheetnames:
        raise WebtestError(f"sheet '{entry['sheet']}' is not in template {entry['name']}")
    ws = wb[entry["sheet"]]
    row = entry["header_row"]
    headers = {c.column_letter: str(c.value) for c in ws[row] if c.value not in (None, "")}
    last = max([_index(letter) for letter in headers] + [0])
    merged = [(str(m), m.min_col, m.max_col) for m in ws.merged_cells.ranges if m.min_row <= row <= m.max_row]
    lists = []
    for dv in ws.data_validations.dataValidation:
        if dv.type != "list" or not dv.formula1 or not dv.formula1.startswith('"'):
            continue
        options = [o.strip() for o in dv.formula1.strip('"').split(",") if o.strip()]
        cols = set()
        for rng in dv.sqref.ranges:
            if rng.max_row > row:
                cols.update(range(rng.min_col, rng.max_col + 1))
        lists.append({"cols": cols, "options": options})
    return {"headers": headers, "last": last, "merged": merged, "lists": lists}


def list_options(facts: dict, letter: str) -> list[str]:
    col = _index(letter)
    return next((d["options"] for d in facts["lists"] if col in d["cols"]), [])


def default_labels(options: list[str]) -> dict[str, str]:
    if len(options) >= 2:
        labels = {"pass": options[0], "fail": options[1]}
        for key, value in zip(("not-run", "not-applicable"), options[2:4]):
            labels[key] = value
        return labels
    return {"pass": "Pass", "fail": "Fail"}


def first_guess(entry: dict, facts: dict, lang: str = "en") -> dict:
    """The column plan before the tester edits it."""
    columns: list[dict] = []
    used_letters: set[str] = set()
    for role, letter in entry["columns"].items():
        field = ROLE_FIELD.get(role)
        if field:
            columns.append({"field": field, "letter": letter})
            used_letters.add(letter)
    have = {c["field"] for c in columns}
    for letter, text in sorted(facts["headers"].items(), key=lambda kv: _index(kv[0])):
        field = _result_field(text)
        if letter not in used_letters and field and field not in have:
            columns.append({"field": field, "letter": letter})
            used_letters.add(letter)
            have.add(field)
    next_col = facts["last"] + 1
    names = HEADERS.get(lang, HEADERS["en"])
    for field in PROPOSED_NEW:
        if field not in have:
            columns.append({"field": field, "letter": _letter(next_col), "header": names[field], "new": True})
            next_col += 1
    columns.sort(key=lambda c: _index(c["letter"]))
    verdict = next((c["letter"] for c in columns if c["field"] == "verdict" and not c.get("new")), None)
    options = list_options(facts, verdict) if verdict else []
    return {"template": entry["name"], "sheet": entry["sheet"], "header_row": entry["header_row"],
            "verdict_labels": default_labels(options), "verdict_options": options, "columns": columns}


# checks ---------------------------------------------------------------------------------------
def check_labels(labels: Any) -> dict[str, str]:
    if not isinstance(labels, dict):
        raise WebtestError("verdict_labels must be an object")
    out = {}
    for key, value in labels.items():
        if key not in LABEL_KEYS:
            raise WebtestError(f"verdict_labels has an unknown key {key!r}")
        if not isinstance(value, str) or not value.strip() or len(value) > 50:
            raise WebtestError(f"verdict label for {key} must be short text")
        out[key] = value.strip()
    if "pass" not in out or "fail" not in out:
        raise WebtestError("verdict_labels needs pass and fail")
    return out


def check_columns(columns: Any, facts: dict) -> list[dict]:
    """Known fields, each letter once, new columns right of the last header, content and verdict present."""
    if not isinstance(columns, list) or not columns:
        raise WebtestError("the column plan needs columns")
    out, letters, fields = [], set(), set()
    for col in columns:
        if not isinstance(col, dict) or col.get("field") not in FIELDS:
            raise WebtestError(f"unknown column field {col.get('field') if isinstance(col, dict) else col!r}")
        letter = str(col.get("letter") or "").strip().upper()
        if not re.fullmatch(r"[A-Z]{1,3}", letter):
            raise WebtestError(f"column {col['field']} needs a column letter")
        if letter in letters:
            raise WebtestError(f"column {letter} is used twice")
        if col["field"] in fields:
            raise WebtestError(f"field {col['field']} has two columns")
        letters.add(letter)
        fields.add(col["field"])
        item = {"field": col["field"], "letter": letter}
        if col.get("new"):
            header = col.get("header")
            if not isinstance(header, str) or not header.strip() or len(header) > 100:
                raise WebtestError(f"new column {letter} needs a header of 1 to 100 characters")
            if _index(letter) <= facts["last"]:
                raise WebtestError(f"new column {letter} must be to the right of the template's last header")
            for name, lo, hi in facts["merged"]:
                if lo <= _index(letter) <= hi:
                    raise WebtestError(f"new column {letter} falls in the merged header cells {name}; add the "
                                       "column in the template and register it again")
            item.update(header=header.strip(), new=True)
        elif letter not in facts["headers"]:
            raise WebtestError(f"column {letter} has no header in the template; mark it new with a header")
        out.append(item)
    for need in ("content", "verdict"):
        if need not in fields:
            raise WebtestError(f"the column plan needs a {need} column")
    return sorted(out, key=lambda c: _index(c["letter"]))


def _entry(name: str | None) -> dict:
    try:
        return templates.resolve(name)
    except templates.TemplateError as exc:
        raise WebtestError(str(exc)) from None


def confirmed_plan(run: dict, answer: dict) -> dict:
    """The column plan from the confirmed review table, checked against the template it names."""
    entry = _entry(answer.get("template") or run.get("template"))
    facts = sheet_facts(entry)
    return {"template": entry["name"], "sheet": entry["sheet"], "header_row": entry["header_row"],
            "verdict_labels": check_labels(answer.get("verdict_labels")),
            "columns": check_columns(answer.get("columns"), facts)}


# values ---------------------------------------------------------------------------------------
def verdict_text(case: dict, labels: dict[str, str]) -> str:
    state = case["state"]
    if state in ("pass", "fail"):
        return labels[state]
    if state == "self-run":
        return labels.get((case.get("result") or {}).get("verdict"), "")
    if state == "not-run":
        return labels.get("not-run", "Not run")
    if state == "not-applicable":
        return labels.get("not-applicable", "N/A")
    if state == "manual":
        return labels.get("manual") or labels.get("not-run") or "Manual"
    return ""


def value_for(case: dict, field: str, labels: dict[str, str]) -> Any:
    result = case.get("result") or {}
    if field == "no":
        return (case.get("source") or {}).get("no") or case["row"]
    if field == "screen":
        screen = case.get("screen") or {}
        name, url = screen.get("name") or "", screen.get("url") or ""
        return f"{name} ({url})" if name and url else name or url
    if field == "target_node":
        return (case.get("source") or {}).get("target_node") or ""
    if field == "verdict":
        return verdict_text(case, labels)
    if field == "actual":
        actual = result.get("actual") or ""
        if case["state"] == "not-run":
            reason = f"not-run: {case.get('not_run_reason')}"
            return f"{actual}\n({reason})" if actual else reason
        return actual
    if field == "evidence":
        return "\n".join(result.get("evidence") or [])
    if field == "executed_at":
        return str(result.get("executed_at") or "")[:10]
    if field == "by":
        return result.get("by") or ""
    value = case.get(field)
    return "" if value is None else value


def rows_for(cases: list[dict], plan: dict) -> list[dict[str, Any]]:
    labels = plan["verdict_labels"]
    return [{c["field"]: value_for(case, c["field"], labels) for c in plan["columns"]} for case in cases]


def samples(run: dict, plan: dict) -> list[dict]:
    """The first sure, the first choice and the first not-web row, as the review table shows them."""
    picked = []
    for cls in ("sure", "choice", "not-web"):
        case = next((c for c in run["cases"] if c.get("class") == cls), None)
        if case is not None:
            values = rows_for([case], plan)[0]
            picked.append({"row": case["row"], "class": cls,
                           "cells": {c["letter"]: str(values[c["field"]]) for c in plan["columns"]}})
    return picked


def review_lines(run: dict) -> list[dict]:
    return [{"row": c["row"], "no": str((c.get("source") or {}).get("no") or ""), "content": c.get("content") or "",
             "screen": (c.get("screen") or {}).get("url") or "", "screen_name": (c.get("screen") or {}).get("name") or "",
             "confidence": (c.get("screen") or {}).get("confidence") or "none", "class": c.get("class"),
             "kind": c.get("kind"), "reason": c.get("reason") or "", "runner": c.get("runner") or "none",
             "scenario": c.get("scenario"), "viewport": c.get("viewport") or "pc",
             "preconditions": c.get("preconditions") or "", "steps": c.get("steps") or "",
             "expected": c.get("expected") or "", "capture": c.get("capture")}
            for c in run["cases"]]


def columns_view(folder: Path, run: dict, template: str | None = None, *, ask: bool = False) -> dict:
    if not run["import"]["complete"]:
        raise WebtestError("import the run first")
    entry = _entry(template or run.get("template"))
    facts = sheet_facts(entry)
    plan = first_guess(entry, facts, run.get("report_lang") or "en")
    view = {"plan": plan, "headers": facts["headers"], "last_column": _letter(max(facts["last"], 1)),
            "samples": samples(run, plan)}
    if not ask:
        return view
    missing = [c["row"] for c in run["cases"] if not c.get("class")]
    if missing:
        raise WebtestError(f"rows without a class: {', '.join(missing[:10])}; run webtest-triage first")
    lines = review_lines(run)
    digest = webtest.cases_digest(run)
    # A new id whenever the rows or the proposal change: an ask id that was answered before hands back
    # its old answer, which would confirm a table the tester never saw.
    ask_id = hashlib.sha256(json.dumps([digest, lines], ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
    return {"type": "review-table", "id": f"review-{ask_id[:20]}", "run": run["id"], "template": entry["name"],
            "headers": facts["headers"], "last_column": view["last_column"], "columns": plan["columns"],
            "verdict_labels": plan["verdict_labels"], "verdict_options": plan["verdict_options"],
            "samples": view["samples"], "lines": lines, "digest": digest}


# export ---------------------------------------------------------------------------------------
REPORT = {
    "en": {"title": "Web test run report", "source": "Source", "base": "Base URL", "hosts": "Hosts",
           "project": "Project", "template": "Template", "confirmed": "Plan confirmed", "counts": "Counts",
           "state": "State", "count": "Rows", "fail": "Failed rows", "notrun": "Rows not run", "reason": "Reason",
           "self": "Rows run by the tester", "changed": "Rows whose class changed during the run",
           "visual": "Visual rows", "visual_note": "compared by the agent with the capture; spot-check them",
           "all": "All rows", "none": "None.", "draft": "Results are a draft for the tester to review.",
           "expected": "Expected", "actual": "Actual", "evidence": "Evidence", "verdict": "Result",
           "from": "From", "to": "To", "content": "Content", "scenario": "Scenario", "screen": "Screen",
           "class": "Class", "workbook": "Workbook"},
    "ja": {"title": "Webテスト実施レポート", "source": "ソース", "base": "ベースURL", "hosts": "対象ホスト",
           "project": "プロジェクト", "template": "テンプレート", "confirmed": "計画確認", "counts": "件数",
           "state": "状態", "count": "件数", "fail": "NGの行", "notrun": "未実施の行", "reason": "理由",
           "self": "テスターが実施した行", "changed": "実施中に分類が変わった行", "visual": "見た目の行",
           "visual_note": "エージェントがキャプチャと見比べた結果です。抜き取りで確認してください",
           "all": "全行", "none": "なし。", "draft": "結果はテスターが確認するための下書きです。",
           "expected": "期待結果", "actual": "実際の結果", "evidence": "エビデンス", "verdict": "結果",
           "from": "変更前", "to": "変更後", "content": "内容", "scenario": "シナリオ", "screen": "画面",
           "class": "分類", "workbook": "ワークブック"},
    "vi": {"title": "Báo cáo chạy test web", "source": "Nguồn", "base": "URL gốc", "hosts": "Host",
           "project": "Dự án", "template": "Template", "confirmed": "Kế hoạch đã xác nhận", "counts": "Số lượng",
           "state": "Trạng thái", "count": "Số dòng", "fail": "Các dòng fail", "notrun": "Các dòng không chạy",
           "reason": "Lý do", "self": "Các dòng tester tự chạy", "changed": "Các dòng đổi phân loại khi chạy",
           "visual": "Các dòng giao diện", "visual_note": "do agent so với ảnh chụp; hãy kiểm tra lại vài dòng",
           "all": "Tất cả các dòng", "none": "Không có.", "draft": "Kết quả là bản nháp để tester xem lại.",
           "expected": "Mong đợi", "actual": "Thực tế", "evidence": "Bằng chứng", "verdict": "Kết quả",
           "from": "Từ", "to": "Sang", "content": "Nội dung", "scenario": "Kịch bản", "screen": "Màn hình",
           "class": "Phân loại", "workbook": "Workbook"},
}


def _cell(value: Any) -> str:
    return str(value or "").replace("\r", "").replace("\n", "<br>").replace("|", "\\|")


def _table(head: list[str], rows: list[list[Any]]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(_cell(v) for v in row) + " |" for row in rows]
    return out


def report_markdown(run: dict, workbook_name: str) -> str:
    t = REPORT.get(run.get("report_lang") or "en", REPORT["en"])
    cases = run["cases"]
    src = run.get("source") or {}
    confirmed = run.get("confirmed") or {}
    lines = [f"# {t['title']}: {run.get('name') or run['id']}", "",
             f"- Run: `{run['id']}`",
             f"- {t['source']}: {src.get('url') or src.get('file') or ''}",
             f"- {t['base']}: {run.get('base_url') or ''}",
             f"- {t['hosts']}: {', '.join(run['hosts'])}",
             f"- {t['project']}: {run.get('project') or ''}",
             f"- {t['template']}: {(run.get('columns') or {}).get('template') or ''}",
             f"- {t['confirmed']}: {confirmed.get('at') or ''}",
             f"- {t['workbook']}: `{workbook_name}`", "", f"> {t['draft']}", "", f"## {t['counts']}", ""]
    lines += _table([t["state"], t["count"]], sorted(webtest.counts(run).items()))
    fails = [c for c in cases if c["state"] == "fail" or c["state"] == "self-run" and (c.get("result") or {}).get("verdict") == "fail"]
    lines += ["", f"## {t['fail']}", ""]
    lines += _table(["Row", "No", t["content"], t["expected"], t["actual"], t["evidence"]],
                    [[c["row"], value_for(c, "no", {}), c.get("content"), c.get("expected"),
                      (c.get("result") or {}).get("actual"), ", ".join((c.get("result") or {}).get("evidence") or [])]
                     for c in fails]) if fails else [t["none"]]
    notrun = [c for c in cases if c["state"] == "not-run"]
    lines += ["", f"## {t['notrun']}", ""]
    lines += _table(["Row", "No", t["content"], t["reason"]],
                    [[c["row"], value_for(c, "no", {}), c.get("content"), c.get("not_run_reason")] for c in notrun]
                    ) if notrun else [t["none"]]
    selfrun = [c for c in cases if c["state"] == "self-run"]
    lines += ["", f"## {t['self']}", ""]
    lines += _table(["Row", "No", t["verdict"], t["actual"], t["evidence"]],
                    [[c["row"], value_for(c, "no", {}), (c.get("result") or {}).get("verdict"),
                      (c.get("result") or {}).get("actual"), ", ".join((c.get("result") or {}).get("evidence") or [])]
                     for c in selfrun]) if selfrun else [t["none"]]
    changed = [c for c in cases if c.get("class_changed")]
    lines += ["", f"## {t['changed']}", ""]
    lines += _table(["Row", t["from"], t["to"]],
                    [[c["row"], c["class_changed"].get("from"), c["class_changed"].get("to")] for c in changed]
                    ) if changed else [t["none"]]
    visual = [c["row"] for c in cases if c.get("kind") == "visual" and c["state"] in ("pass", "fail")]
    lines += ["", f"## {t['visual']}", "", (f"{', '.join(visual)}: {t['visual_note']}" if visual else t["none"])]
    lines += ["", f"## {t['all']}", ""]
    lines += _table(["Row", "No", t["state"], t["class"], t["scenario"], t["screen"]],
                    [[c["row"], value_for(c, "no", {}), c["state"], c.get("class"), c.get("scenario"),
                      value_for(c, "screen", {})] for c in cases])
    return "\n".join(lines) + "\n"


def export(folder: Path, run: dict) -> dict:
    still_open = [c["row"] for c in run["cases"] if c["state"] in OPEN]
    if still_open:
        raise WebtestError(f"rows are still open ({', '.join(still_open[:10])}); close the run first")
    plan = run.get("columns")
    if not plan or not plan.get("columns"):
        raise WebtestError("the run has no confirmed column plan")
    entry = _entry(plan.get("template"))
    columns = {c["field"]: c["letter"] for c in plan["columns"]}
    new_headers = {c["letter"]: c["header"] for c in plan["columns"] if c.get("new")}
    written = xlsx.fill_columns(Path(entry["path"]), plan.get("sheet") or entry["sheet"],
                                int(plan.get("header_row") or entry["header_row"]), columns,
                                rows_for(run["cases"], plan), folder / f"{run['id']}.xlsx", new_headers)
    workbook = Path(written["path"])
    report_path = xlsx._unique(folder / f"{run['id']}-report.md")
    report_path.write_text(report_markdown(run, workbook.name), encoding="utf-8")
    run.setdefault("exports", []).append({"workbook": workbook.name, "report": report_path.name,
                                          "at": webtest.now_iso()})
    webtest.save(folder, run)
    return {"workbook": str(workbook), "report": str(report_path), "rows": len(run["cases"]),
            "counts": webtest.counts(run)}
