# testign shared rules

Every testign skill reads this file before it does anything. These rules are written only here.
The "Chú giải" block at the end of `templates/survey-report-template.md` is the reader-facing copy
of the definitions below and must stay in sync with them.

## 1. Ngôn ngữ

- Report: theo ngôn ngữ được chỉ định (`--lang`, rồi `lang` trong config); nếu không chỉ định → vi > ja > en.
- Câu hỏi route BrSE/khách: LUÔN kèm bản nháp ja, bất kể ngôn ngữ report.
- Label UI giữ nguyên văn tiếng Nhật (vd 「確定」ボタン), không dịch.
- Identifier code, tên file, commit: giữ tiếng Anh.

## 2. Nguồn sự thật và git

- Production = `master` tại merge-base. Phase này = `develop`.
- Diff luôn dùng merge-base: `git diff master...develop` (ba chấm), nhóm commit theo ticket ID.
  Không dùng diff hai chấm: hotfix chưa merge sang develop sẽ hiện thành "xoá" giả.
- Git chỉ đọc. Chỉ dùng `git show <ref>:<path>`, `git diff`, `git log`, `git merge-base`,
  `git grep <ref>`, `git rev-parse`. Không bao giờ `checkout`, `switch`, `reset`, `stash`, `pull`,
  `commit` hay sửa working tree, index, refs của repo khách. `git fetch` chỉ chạy khi tester truyền `--fetch`.
- Ref có thể là tên branch hoặc SHA. Report luôn ghi lại SHA đã dùng (frontmatter).

## 3. Cách viết

- Mô tả bằng HÀNH VI TRÊN MÀN HÌNH. Tham chiếu code chỉ đặt ở mục 8 (Phụ lục cho dev).
- Mọi khẳng định gắn nhãn nguồn:
  - `[code]` đọc từ source
  - `[khách chốt]` Q&A / decisions log
  - `[wiki]` tài liệu thiết kế
  - `[observed]` quan sát trên staging
  - `[suy luận]` agent suy ra, chưa kiểm chứng
- Không bịa coverage: phần chưa đọc được phải liệt kê ở mục 6. Stored procedure, config DB, batch job
  và master data luôn ở mức `[suy luận]` và nằm trong "Chưa đọc được", trừ khi đã có `[khách chốt]`.
- Bỏ placeholder `<...>` khi điền; xoá dòng/mục không có dữ liệu thay vì để trống,
  trừ mục 1, 2, 3, 6 (luôn có).

## 4. fact / intent và route câu hỏi

- fact = hệ thống *đang* làm gì → Dev trả lời.
- intent = hệ thống *nên* làm gì → BrSE/khách trả lời.
- Mỗi finding gắn nhãn fact | intent. Không chắc → intent.
- Lai → Dev xác nhận fact trước, sau đó escalate intent lên BrSE/khách kèm fact đã xác nhận.
  Hỏi Dev về intent chỉ nhận được code tự xác nhận chính nó.

## 5. Loại finding

| Mã | Ý nghĩa |
|---|---|
| F1 | Mâu thuẫn trong chính spec (backlog ≠ Figma) |
| F2 | Spec lệch Production — spec im lặng / mâu thuẫn với hành vi hiện tại |
| F3 | Spec lệch develop — ticket khác cùng phase đã đổi cùng chỗ |
| F4 | Ảnh hưởng ngoài scope spec — logic dùng chung |
| F5 | Agent không xác định được (SP, config, batch…) |

## 6. Mức

- 🔴 Blocking — sai là sai nghiệp vụ cốt lõi
- 🟠 Major — gây bug rõ ràng
- 🟡 Minor — hiển thị, wording

## 7. Chặn test case?

| Giá trị | Ý nghĩa |
|---|---|
| Block | Câu trả lời quyết định nhóm case tồn tại hay không → chưa viết được vùng này |
| Partial | Viết được phần còn lại, để placeholder cho nhóm bị ảnh hưởng |
| No | Viết được ngay, câu trả lời chỉ đổi expected value |

Trong mục 2 của report: sắp xếp Block trước, rồi theo Mức.

## 8. ID dòng và trace

- `B*` = hành vi (mục 3), `R*` = phạm vi regression (mục 5), `Q*` = câu hỏi (mục 2, 4).
- Mỗi test case ghi ID nguồn (`B*`/`R*`) ở cột 備考. Không có ID → orphan.
- ID đã phát hành trong một revision không được đổi nghĩa ở revision sau; dòng bị bỏ thì ghi rõ là bỏ.

## 9. Report revisions

- Tên file: `<output_dir>/<TICKET>/<TICKET>-survey-r<N>.md` (config `output_dir`, mặc định `~/Downloads`).
  File test case, brief và facts của ticket cũng nằm trong `<output_dir>/<TICKET>/`.
- Report mới luôn được lưu qua `report-save` (validate + đánh số revision), không ghi file report trực tiếp.
- Mọi lệnh mặc định đọc revision cao nhất và không bao giờ ghi đè một revision có sẵn;
  thay đổi luôn tạo `r<N+1>` với `previous` trỏ về file cũ.

## 10. Gọi Python

Logic xác định (git, config, report, xlsx) nằm trong package `scripts/testign/`. Skill gọi qua một
entry point duy nhất:

```bash
<python> "${CLAUDE_PLUGIN_ROOT}/scripts/run.py" <subcommand> [args]
```

`${CLAUDE_PLUGIN_ROOT}` được Claude Code thay khi load skill; biến này không có sẵn trong Bash, nên
luôn dùng đường dẫn đã được thay trong nội dung skill.

Chọn `<python>` một lần mỗi phiên: thử lần lượt `python3`, `py -3`, `python` với `--version` và dùng
lệnh đầu tiên báo Python ≥ 3.10. Trên Windows, `python3` có thể là alias của Microsoft Store và không
chạy được; khi đó chuyển sang `py -3`. Nếu không có lệnh nào dùng được, dừng lại và báo tester cài
Python ≥ 3.10 (xem README), không tự làm thay bằng tay.

`run.py` tự kiểm tra phiên bản và in lỗi rõ ràng nếu Python quá cũ.
