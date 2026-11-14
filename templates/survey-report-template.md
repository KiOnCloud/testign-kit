---
ticket: <TICKET-ID>
repo: <repo name or path>
master_ref: <master branch name or SHA as given>
develop_ref: <develop branch name or SHA as given>
merge_base: <merge-base SHA>
develop_head: <develop HEAD SHA>
revision: <N>
previous: <file name of revision N-1 | null>
plugin_version: <testign version>
lang: <vi|ja|en>
generated_at: <ISO 8601 timestamp>
cache_root: <scout cache root commit | null>
cache_feature: <scout cache feature slug | null>
---

<!--
SURVEY REPORT TEMPLATE — hướng dẫn cho agent (không render)
Quy tắc viết report nằm ở ${CLAUDE_PLUGIN_ROOT}/references/rules.md. Đọc file đó trước khi điền.
Frontmatter là hợp đồng giữa các bước (survey → close → testcase): giữ đủ các field, ghi SHA đầy đủ.
-->

# [<TICKET-ID>] Survey report — <tên chức năng>

> **Production (master):** `<merge-base hash>` · **Phase này (develop):** `<HEAD hash>` · **Ngày:** <YYYY-MM-DD> · **Lang:** <vi|ja|en>
> **Spec nguồn:** <link backlog> · <link Figma frame>

---

## 1. Tóm tắt

- **Ticket thay đổi gì:** <1–2 câu, ngôn ngữ nghiệp vụ>
- **Kết luận:** <🔴 Chờ QA trước khi viết test case | 🟡 Viết được, còn điểm mở | 🟢 Clear>
- **Finding:** <n> Blocking · <n> Major · <n> Minor — QA Dev: <n> · QA BrSE/khách: <n>
- **Chặn test case:** <n> Block · <n> Partial
- **Regression cần chú ý:** <màn/flow chính, tối đa 3>

---

## 2. Việc cần làm ngay

| ID | QA | Tóm tắt vấn đề | Mức | Chặn test case? |
|---|---|---|---|---|
| Q1 | <Dev (#ticket liên quan) \| BrSE/khách> | <vấn đề trong 1–2 câu> | <🔴 Blocking \| 🟠 Major \| 🟡 Minor> | <Block \| Partial \| No> |

<!-- Sắp xếp: Block trước, rồi theo Mức. -->

---

## 3. Hiện trạng chức năng

| ID | Hành vi | Production (master) | Phase này (develop) | Spec yêu cầu | Lệch? |
|---|---|---|---|---|---|
| B1 | <hành vi> | <đang chạy thế nào> | <➖ Không đổi \| đã đổi thế nào (#ticket)> | <spec nói gì \| Không nhắc tới> | <✅ Khớp \| ⚠️ Q-ID> |

<!--
Nếu ticket đổi state/flow: thêm diagram Mermaid before/after.

```mermaid
stateDiagram-v2
  direction LR
  state "Production" as P { ... }
  state "Sau thay đổi" as D { ... }
```
-->

---

## 4. Chi tiết finding

### Q1 · <F1–F5 tên loại> · <fact | intent> · <Mức> · Chặn test case: <Block | Partial | No>

- **Hiện trạng:** <hành vi hiện tại trên màn hình> `[nguồn]`
- **Spec:** <trích/diễn giải spec> `[nguồn]`
- **Vấn đề:** <chỗ lệch / chỗ mơ hồ>
- **Cách kiểm chứng trên staging:**
  1. <bước tester tự quan sát được>
  2. <...>
- **Ảnh hưởng test case:** <nhóm case phát sinh / mất đi / đổi expected tuỳ câu trả lời>
- **Liên quan:** <B-ID, R-ID>
- **Câu hỏi:** <câu hỏi theo ngôn ngữ report>
- **Câu hỏi (ja, draft cho BrSE):** <chỉ khi QA = BrSE/khách>

<!-- Lặp block cho Q2, Q3, ... -->

---

## 5. Phạm vi ảnh hưởng (regression)

| ID | Màn / flow | Lý do bị ảnh hưởng | Mức | Nguồn |
|---|---|---|---|---|
| R1 | <tên màn, label JP nguyên văn> | <dùng chung logic X / ticket #... cùng phase đổi Y> | <Cao \| Trung bình \| Thấp> | <[code] \| [suy luận]> |

---

## 6. Coverage & độ tin cậy

- ✅ **Đã khảo sát:** <entry point, component, API, service, bảng DB>
- ⛔ **Chưa đọc được:** <stored procedure, config, batch job, master data>
  → các kết luận liên quan: <B-ID / Q-ID / R-ID> chỉ ở mức `[suy luận]`
- 🔍 **Grep không ra:** <label / anchor không tìm thấy trong source>
- **Decisions log đã tham chiếu:** <có, D-ID ... | không có>
- **Scout cache:** <hit | partial (đọc lại: B-ID …) | miss (lý do)>

---

## 7. Coverage test case

<!-- Điền SAU khi sinh test case. Mỗi TC ghi ID nguồn (B*/R*) ở cột 備考. -->

| Chỉ số | Giá trị |
|---|---|
| Tổng test case | <n> |
| Dòng B*/R* đã có TC | <n>/<n> |

- **Gaps** (dòng có lệch/ảnh hưởng nhưng chưa có TC): <B-ID, R-ID … | Không có>
- **Orphans** (TC không gắn dòng nào — thừa, hoặc report thiếu dòng): <TC-ID … | Không có>
- **Chờ QA** (TC tạm theo giả định, cần cập nhật khi có trả lời): <TC-ID → Q-ID>

---

## 8. Phụ lục cho dev

| Ref | Vị trí code | Commit / ticket |
|---|---|---|
| Q1 / B1 | `<path/File.cs:line>` | `<hash>` (#<ticket>) |

**Commit develop trong scope, nhóm theo ticket:**
- #<ticket>: `<hash>`, `<hash>` — <1 dòng mô tả>

---

<details>
<summary>Chú giải</summary>

**Loại finding**
| Mã | Ý nghĩa |
|---|---|
| F1 | Mâu thuẫn trong chính spec (backlog ≠ Figma) |
| F2 | Spec lệch Production — spec im lặng / mâu thuẫn với hành vi hiện tại |
| F3 | Spec lệch develop — ticket khác cùng phase đã đổi cùng chỗ |
| F4 | Ảnh hưởng ngoài scope spec — logic dùng chung |
| F5 | Agent không xác định được (SP, config, batch…) |

**Mức:** 🔴 Blocking — sai là sai nghiệp vụ cốt lõi · 🟠 Major — gây bug rõ ràng · 🟡 Minor — hiển thị, wording

**Chặn test case?**
| Giá trị | Ý nghĩa |
|---|---|
| Block | Câu trả lời quyết định nhóm case tồn tại hay không → chưa viết được vùng này |
| Partial | Viết được phần còn lại, để placeholder cho nhóm bị ảnh hưởng |
| No | Viết được ngay, câu trả lời chỉ đổi expected value |

**Nguồn:** `[code]` đọc từ source · `[khách chốt]` Q&A/decisions log · `[wiki]` tài liệu thiết kế · `[observed]` quan sát trên staging · `[suy luận]` agent suy ra, chưa kiểm chứng

**fact / intent:** fact = hệ thống *đang* làm gì (Dev trả lời) · intent = hệ thống *nên* làm gì (BrSE/khách trả lời)

</details>
