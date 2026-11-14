# Handoff — AI agent hỗ trợ Tester: Spec survey → QA → Test case

> Nguồn: phiên thiết kế 2026-11-14. Đi kèm: `../templates/survey-report-template.md` (template report đầy đủ).
> Mục tiêu file này: đủ context để tiếp tục trong project **CCV - Tester support** mà không phải dựng lại từ đầu.

---

## 1. Tóm tắt

Agent đọc source ở hai nhánh **master (Production)** và **develop (phase hiện tại)** để nắm hiện trạng chức năng. Sau đó đối chiếu với spec của ticket, sinh ra **QA đã phân luồng** (Dev hoặc BrSE/khách) và một **survey report** để tester hình dung được. Tester clear nghiệp vụ dựa trên report rồi viết thẳng test case. Mỗi test case trỏ ngược về một dòng ID trong report để kiểm coverage.

---

## 2. Bối cảnh (đã xác nhận)

- Công ty Nhật, offshore. Tester chủ yếu làm manual testing.
- Spec đến từ backlog và Figma.
- Test case viết trong Excel theo rule tương đối đơn giản: mô tả, step, expected, ảnh evidence.
- Quy trình hiện tại: **clear nghiệp vụ → viết thẳng test case**, không có bước 観点 riêng.
- Codebase legacy lớn. Ticket là phần thay đổi trên hành vi đang chạy, không phải spec độc lập.
- **Nguồn context duy nhất là source code.** Kết quả scout của dev không được lưu lại, và không phải dev nào cũng scout.
- Nhánh: `master` là base của mỗi phase, tương đương Production. `develop` chứa các thay đổi của phase hiện tại.
- Công cụ AI: chỉ có Claude (và DeepSeek), không có Copilot.

---

## 3. Các quyết định đã chốt

| # | Quyết định | Lý do |
|---|---|---|
| D1 | Spec QA phải dựa trên hiện trạng code, không chỉ dựa trên spec | Không có context hiện trạng thì chỉ bắt được mâu thuẫn trong chính spec, bỏ sót xung đột với logic đang chạy |
| D2 | Scout là **bước tự động của hệ thống cho mọi ticket**, không dựa vào thói quen của dev | Scout của dev không được lưu và không đồng đều |
| D3 | Khảo sát master (merge-base) để biết hành vi Production, diff develop để biết phase này đã đổi gì | Diff giới hạn phạm vi đọc nên rẻ hơn và ít ảo giác hơn scout tự do. Chỗ master/develop/spec lệch nhau là nguồn Q&A giá trị nhất |
| D4 | Phân luồng QA: **fact → Dev, intent → BrSE/khách**. Câu hỏi lai: Dev xác nhận fact trước, rồi mới escalate | Hỏi dev về ý đồ thì dev trả lời bằng code, tức code tự xác nhận chính nó |
| D5 | Không thêm bước 観点. Các dòng B\*/R\* trong report đóng vai trò lớp review được | Giữ nguyên quy trình với khách. Leader review 20 dòng report thay vì 80 test case |
| D6 | Mỗi test case ghi ID nguồn (B\*/R\*) vào cột 備考. Agent kiểm gaps/orphans | Không đổi template Excel của khách mà vẫn kiểm được coverage |
| D7 | Ngôn ngữ report: mặc định vi, thứ tự ưu tiên vi → ja → en. Câu hỏi gửi BrSE/khách luôn kèm bản nháp ja. Label UI giữ nguyên văn tiếng Nhật | Đích đến quyết định ngôn ngữ của câu hỏi. Tester cần đối chiếu label với màn hình |
| D8 | Report viết theo **hành vi trên màn hình**. Code ref chỉ nằm ở phụ lục | Người đọc là tester, không phải dev |

**Đã loại:**
- Dùng artifact scout của dev làm nguồn: không khả thi (xem D2).
- Thêm bước 観点 riêng: không cần (xem D5).

---

## 4. Flow

1. **Lấy scope từ spec.** Trích điểm neo: tên màn, label tiếng Nhật trong Figma, API, thuật ngữ nghiệp vụ. Đây chỉ là điểm xuất phát.
2. **Khảo sát source.**
   - Locate code từ chữ trên UI: grep label tiếng Nhật trong i18n/resource hoặc chuỗi hardcode → component → API → service → DB.
   - master (merge-base) → hành vi Production.
   - `git diff master...develop` (dùng merge-base, **không dùng two-dot**) → thay đổi của phase, nhóm theo ticket ID.
   - **Bắt buộc mở rộng sang callers** và logic dùng chung. Đưa migration và config vào phạm vi diff.
   - Ghim commit hash. Output là brief kèm mục coverage.
3. **Đối chiếu spec với brief → finding F1–F5**, mỗi finding gắn nhãn fact/intent (không chắc thì xếp là intent).
4. **Phân luồng QA** theo D4. Tester review trước khi gửi; agent không gửi output thô.
5. **Khép vòng.** Câu trả lời của khách ghi vào decisions log, cập nhật report và test case.
6. **Sinh test case** sau khi đã clear. Mỗi case có ref B\*/R\*. Agent kiểm gaps/orphans (O(R+T)).
7. *(Sau khi ticket đã code)* So diff riêng của ticket với spec: code làm mà spec không nói có thể là side effect; spec có mà diff không chạm có thể là thiếu implement.

**Phân loại finding**
| Mã | Ý nghĩa | QA mặc định |
|---|---|---|
| F1 | Mâu thuẫn trong chính spec (backlog ≠ Figma) | BrSE/khách |
| F2 | Spec lệch Production (im lặng hoặc mâu thuẫn với hành vi hiện tại) | BrSE/khách |
| F3 | Spec lệch develop (ticket khác cùng phase đã đổi cùng chỗ) | Dev, sau đó BrSE nếu cần |
| F4 | Ảnh hưởng ngoài scope spec (logic dùng chung) | Dev xác nhận, rồi BrSE |
| F5 | Agent không xác định được (SP, config, batch) | Dev |

---

## 5. Report

Xem `../templates/survey-report-template.md`. Cấu trúc:
1. Tóm tắt (kết luận 🔴/🟡/🟢, số finding, số câu chặn test case)
2. Việc cần làm ngay: `ID | QA | Tóm tắt vấn đề | Mức | Chặn test case?`
3. Hiện trạng chức năng: `ID (B*) | Hành vi | Production (master) | Phase này (develop) | Spec yêu cầu | Lệch?`
4. Chi tiết finding, có "Cách kiểm chứng trên staging" và câu hỏi ja cho BrSE
5. Phạm vi ảnh hưởng (R\*)
6. Coverage & độ tin cậy (đã đọc / chưa đọc được / grep không ra)
7. Coverage test case (gaps / orphans / chờ QA)
8. Phụ lục cho dev (file:line, commit theo ticket)

**Chặn test case?** — Block: câu trả lời quyết định nhóm case có tồn tại hay không · Partial: viết được phần còn lại · No: chỉ đổi expected value. Cột này tách riêng với cột Mức.

Nhãn nguồn: `[code]` `[khách chốt]` `[wiki]` `[observed]` `[suy luận]`.

---

## 6. Rủi ro đã nhận diện

| Rủi ro | Kịch bản | Chặn bằng |
|---|---|---|
| Two-dot diff | Hotfix trên master chưa back-merge, nên hiện ra như thể develop "xóa" validation → sinh Q&A sai | Diff theo merge-base (`...`) |
| Nhiễu đa ticket | Diff của phase trộn nhiều ticket, brief không biết thay đổi thuộc ticket nào | Nhóm commit theo ticket ID (cần convention) |
| Brief thiếu nhưng trông tự tin | Logic nằm trong SP, config, batch mà agent không lần tới → bỏ sót một nhánh | Mục coverage bắt buộc. Dev đọc brief khoảng 5 phút lúc kickoff |
| Code bị coi là chân lý | Bug hiện có bị hợp thức hóa thành spec | Tách fact/intent. Q&A loại F2 ở dạng xác nhận. Xây decisions log |
| Route nhầm intent sang dev | Câu hỏi nghiệp vụ không bao giờ đến khách → đến UAT thì thành bug | Không chắc thì mặc định intent |

---

## 7. Việc còn mở

- [ ] **Pilot (A):** tester hoặc AI team chạy agent trên repo read-only cho 1–2 ticket để tinh chỉnh prompt scout.
- [ ] **Kiểm chứng:** replay trên 2–3 ticket đã release của phase trước, xem report có chỉ ra vùng chứa các bug đã thực sự xảy ra không.
- [ ] **Đóng gói Skill:** prompt scout + rule (ngôn ngữ, F1–F5, phân luồng, nhãn nguồn) + template report.
- [ ] **Tự động hóa (B):** trigger khi ticket chuyển sang trạng thái kiểu "Ready for test design" → chạy Claude Code headless → post report vào ticket/wiki. Chưa chốt cơ chế trigger và nơi lưu.
- [ ] **Quyền truy cập repo** cho runner hoặc tester: cần kiểm tra ISMS/NDA với khách.
- [ ] **Convention commit message chứa ticket ID:** chưa biết team đã có hay chưa. Đây là điều kiện bắt buộc cho bước nhóm theo ticket.
- [ ] **Giả định chưa xác nhận:** ticket được code trên feature branch rồi merge vào develop. Nếu đúng, bước 7 của flow dùng `develop...feature/xxx`.
- [ ] **Decisions log:** chốt vị trí (repo hay wiki) và format .md.
- [ ] **Map cột mục 2 của report sang QA表 hiện có** của project để tester copy thẳng sang Excel.

**Tạm gác (giai đoạn sau):**
- Thực thi test bán tự động bằng Claude in Chrome kèm evidence. Rule cứng: không có screenshot thì không được đánh PASS.
- Draft 不具合報告 tiếng Nhật từ ghi chú và screenshot.
- So sánh Figma với màn hình thật (chỉ bắt lỗi text, element, state; không dùng ở mức pixel).

---

## 8. Liên quan

Bộ Claude checksheet cho tester: chương 1 (foundation, tour công cụ) đã xong. Flow trong file này là ứng viên cho chương 2 (workflow thật).
