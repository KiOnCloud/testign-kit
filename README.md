# testign-kit

> Tên ghép từ **test + design**, cố ý viết như vậy, không phải lỗi chính tả.

Bộ công cụ cho AI agent hỗ trợ manual tester. Agent khảo sát spec của ticket đối chiếu với source code (`master` = Production, `develop` = phase hiện tại), sinh QA đã phân luồng (fact → Dev, intent → BrSE/khách), và hỗ trợ viết test case có tham chiếu ngược về các ID B\*/R\* trong survey report.

## Cấu trúc

| File | Nội dung |
|---|---|
| [`templates/survey-report-template.md`](templates/survey-report-template.md) | Template survey report |

> Repo private. Nội dung liên quan đến dự án khách hàng Nhật (NDA/ISMS): không commit source code, spec hay dữ liệu thật của khách vào đây.
