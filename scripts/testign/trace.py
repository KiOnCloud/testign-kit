"""Trace check between survey report rows and test cases, and report section 7."""

from __future__ import annotations


def gaps(report_rows: list[dict], cases: list[dict]) -> list[str]:
    """Report rows that need a case (deviation or impact) but no case traces to them."""
    covered = {i for c in cases for i in c["trace"]}
    return [r["id"] for r in report_rows if r["needs_case"] and r["id"] not in covered]


def orphans(report_rows: list[dict], cases: list[dict]) -> list[str]:
    """Cases with no valid B*/R* ID: no ID at all, or only IDs that are not in the report."""
    known = {r["id"] for r in report_rows}
    return [c["id"] for c in cases if not any(i in known for i in c["trace"])]


def waiting(cases: list[dict]) -> list[tuple[str, list[str]]]:
    return [(c["id"], c["questions"]) for c in cases if c.get("questions")]


def summarize(report_rows: list[dict], cases: list[dict]) -> dict:
    covered = {i for c in cases for i in c["trace"]}
    with_case = [r["id"] for r in report_rows if r["id"] in covered]
    return {
        "total_cases": len(cases),
        "rows_total": len(report_rows),
        "rows_with_case": len(with_case),
        "gaps": gaps(report_rows, cases),
        "orphans": orphans(report_rows, cases),
        "waiting": [{"case": c, "questions": q} for c, q in waiting(cases)],
    }


def section7(summary: dict, workbook_name: str, sheet: str) -> str:
    def listing(items: list[str]) -> str:
        return ", ".join(items) if items else "Không có"

    waiting_text = (
        ", ".join(f"{w['case']} → {', '.join(w['questions'])}" for w in summary["waiting"])
        if summary["waiting"]
        else "Không có"
    )
    return (
        "\n"
        f"_Nguồn: `{workbook_name}` · sheet `{sheet}`_\n\n"
        "| Chỉ số | Giá trị |\n"
        "|---|---|\n"
        f"| Tổng test case | {summary['total_cases']} |\n"
        f"| Dòng B*/R* đã có TC | {summary['rows_with_case']}/{summary['rows_total']} |\n\n"
        f"- **Gaps** (dòng có lệch/ảnh hưởng nhưng chưa có TC): {listing(summary['gaps'])}\n"
        f"- **Orphans** (TC không gắn dòng nào — thừa, hoặc report thiếu dòng): {listing(summary['orphans'])}\n"
        f"- **Chờ QA** (TC tạm theo giả định, cần cập nhật khi có trả lời): {waiting_text}\n\n"
        "---\n\n"
    )
