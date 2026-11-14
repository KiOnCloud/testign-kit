"""Write a made-up survey report revision that follows the report template's section layout."""

from __future__ import annotations

from pathlib import Path

BODY = """
# [DEMO-1] Survey report — 注文確定

## 1. Tóm tắt

- **Ticket thay đổi gì:** Trừ giảm giá khi tính tổng tiền.

---

## 2. Việc cần làm ngay

| ID | QA | Tóm tắt vấn đề | Mức | Chặn test case? |
|---|---|---|---|---|
| Q1 | BrSE/khách | Giảm giá có áp dụng cho 請求書 không | 🟠 Major | Partial |

---

## 3. Hiện trạng chức năng

| ID | Hành vi | Production (master) | Phase này (develop) | Spec yêu cầu | Lệch? |
|---|---|---|---|---|---|
| B1 | Bấm 「確定」 | Hiện màn xác nhận `[code]` | ➖ Không đổi | Không nhắc tới | ✅ Khớp |
| B2 | Tổng tiền | Tiền hàng + thuế `[code]` | Trừ giảm giá (#DEMO-1) | Trừ giảm giá | ✅ Khớp |
| B3 | Làm tròn | Làm tròn xuống `[suy luận]` | ➖ Không đổi | Làm tròn lên | ⚠️ Q1 |

---

## 4. Chi tiết finding

### Q1 · F4 · intent · 🟠 Major · Chặn test case: Partial

- **Hiện trạng:** 請求書 dùng chung CalcTotal `[code]`
- **Câu hỏi:** Giảm giá có áp dụng cho 請求書 không?
- **Câu hỏi (ja, draft cho BrSE):** 割引は請求書にも適用されますか？

---

## 5. Phạm vi ảnh hưởng (regression)

| ID | Màn / flow | Lý do bị ảnh hưởng | Mức | Nguồn |
|---|---|---|---|---|
| R1 | 請求書 | Dùng chung CalcTotal | Cao | [code] |
| R2 | 「ポイント利用」 | Ticket DEMO-2 cùng phase | Trung bình | [suy luận] |

---

## 6. Coverage & độ tin cậy

- ✅ **Đã khảo sát:** OrderConfirm, OrderService
- ⛔ **Chưa đọc được:** Không có

---

## 7. Coverage test case

<!-- Điền SAU khi sinh test case. -->

| Chỉ số | Giá trị |
|---|---|
| Tổng test case | <n> |

---

## 8. Phụ lục cho dev

| Ref | Vị trí code | Commit / ticket |
|---|---|---|
| B1 | `src/screens/OrderConfirm.cs:6` | |
| B2 / R1 | `src/services/OrderService.cs:7` | `abc1234` (#DEMO-1) |
| R1 | `src/reports/Invoice.cs` | |
"""


def write_report(folder: Path, repo: Path, develop_head: str, merge_base: str, revision: int = 1) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"DEMO-1-survey-r{revision}.md"
    front = "\n".join(
        [
            "---",
            "ticket: DEMO-1",
            f"repo: {repo.as_posix()}",
            "master_ref: master",
            "develop_ref: develop",
            f"merge_base: {merge_base}",
            f"develop_head: {develop_head}",
            f"revision: {revision}",
            "previous: null",
            "plugin_version: 0.1.0",
            "lang: vi",
            "generated_at: 2026-01-01T00:00:00+00:00",
            "---",
        ]
    )
    path.write_text(front + "\n" + BODY, encoding="utf-8", newline="\n")
    return path
