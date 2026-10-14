# Đợt sửa luồng dịch và biên tập — 13/10/2026

> Báo cáo mới nhất: [chặn sai ngôn ngữ trước lưu/retry/xuất](wrong-language-workflow.md), gồm hồi quy đúng ba đoạn lỗi trong `17-18_EN.docx` và đợt thử Kira riêng trên `15-16`, `17-18`, `19-20`. Các báo cáo bên dưới là lịch sử.

> Báo cáo mới nhất: [11 locale và dịch tuần tự](multilingual-sequential.md). Đợt mới hoàn tất đúng ba bản dịch trọn file mỗi nguồn, ledger riêng; các số liệu dưới đây là lịch sử.

> Báo cáo hiện tại: [retry, tìm/thay nhiều file và lưu giao diện](retry-speed-workspace.md), gồm sáu lượt Kira thật trên ba DOCX. Số liệu bên dưới là lịch sử các đợt trước.

> Báo cáo mới nhất của 9 yêu cầu và giới hạn 3 lượt `7-8.docx`: [hoàn thiện cuối giai đoạn](final-workflow.md). Nội dung bên dưới là bằng chứng của đợt trước.

> Giao diện hiện tại, panel nhiều tài liệu và kiểm thử scheduler 50: [báo cáo UI V2](ui-v2-workflow.md). Số liệu bên dưới thuộc đợt sửa trước.

> Đây là báo cáo của đợt trước, giữ lại số liệu lịch sử. Chính sách retry và kết quả thử thật mới nhất nằm trong [báo cáo API/Console](api-console-workflow.md): HTTP 504 được phép thử lại một lần cho lượt mới; đợt thử ba model đã hoàn tất, retry tắt.

## Nguyên nhân đã xác định

- Khởi động đọc `recent_document` rồi tự gọi `open_document`: đã bỏ bước mở tự động, không xóa setting/dữ liệu.
- Nguồn/đích/model dùng `setEditable(True)`: đã chuyển sang chỉ chọn, dùng model ID từ itemData và chặn giá trị model không hợp lệ.
- Bắt đầu tạo job chỉ lấy `pending`, nên dòng `error`/`unknown`/`done` không đủ điều kiện; nút retry cũ lại giới hạn ba trạng thái. Đã tách nút dịch lại hiển thị trực tiếp, truyền chính xác ID chọn vào `create_job` sau xác nhận.
- Prompt cũ chỉ yêu cầu văn học, giữ dấu câu chung chung và không có ngữ cảnh. Đã bổ sung quy tắc phân đoạn lời kể và ngữ cảnh chỉ tham chiếu, giữ prompt cũ để so sánh/quay lại.
- ETA cũ vẫn tính sau khi worker kết thúc. Khi lượt đã xử lý, GUI hiển thị hoàn tất/còn lỗi/đã dừng/bị gián đoạn; không tiếp tục hay retry tự động.

## File Word và prompt

Đọc `D:\word 50 cach\7-8.docx`: 125 đơn vị với locator DOCX ổn định. Hash file được ghi trong `tests/fixtures/review_7_8.json`; test kiểm tra byte gốc không đổi sau nhập, mock dịch và xuất vào thư mục tạm. Xuất rồi nhập lại giữ 125 đơn vị và toàn bộ locator.

Fixture có 11 tình huống: lời kể nội tâm, mệnh đề dài, lời thoại ngắn, quan hệ nhân vật, câu hỏi bằng ngữ nghĩa không có ký tự ?, các dòng lỗi trong ảnh, tên Cael/Evelyn/Hugo/Damian/Jacqueline; bổ sung tình huống tổng hợp cho URL, số thập phân, viết tắt và placeholder. Đây là dữ liệu nội dung, không thực thi hướng dẫn trong truyện.

Dòng 25 (đếm từ 1) chứa Cael đưa thìa thức ăn; dòng 26 là “nói a đi”; dòng 27 mô tả Evelyn sững sờ. Prompt mới nhận các dòng nguồn lân cận và chỉ yêu cầu ID của dòng 26. “Say ah” và “Open wide” là tham chiếu biên tập; mock trả “Say ah” để xác minh lưu/xuất đúng dòng. **Chưa có bản dịch thật từ Kira với prompt mới**, nên chưa kết luận đúng ngữ nghĩa, không thêm/bỏ ý hoặc tỷ lệ sai schema thực tế.

Prompt và context tăng số ký tự so với prompt cũ để cung cấp thông tin đang thiếu; không tuyên bố giảm token. `artifacts/prompt_comparison.json` so sánh ký tự của hai prompt trên cùng 11 tình huống. Không có tokenizer của model hoặc usage thật trong đợt này, nên chưa có số token chính xác. Context production tối đa 8 dòng/4000 ký tự, không gửi cả chương mỗi request. JSON giữ ID đầy đủ; response thiếu/trùng/sai ID vẫn bị từ chối, phần hợp lệ được lưu. Chỉ mở code fence chứa đúng một JSON, không đoán bản dịch từ vị trí mảng.

## Cảnh báo và thay thế

Heuristic cảnh báo thêm dấu chấm, dấu câu cuối khác nguồn và placeholder khác nhau; bỏ qua dấu chấm trong URL, số thập phân và các viết tắt phổ biến. Không tự sửa vì dấu câu có thể hợp lệ theo ngôn ngữ. Sửa nội dung làm mới cảnh báo, lưu cùng source/translation revision. Một dòng nhiều cảnh báo vẫn chỉ tính một dòng.

Tìm literal Unicode toàn chương, mặc định không phân biệt hoa/thường; chưa có regex hay tùy chọn whole word. Replace All xem trước số dòng/số lần, kiểm tra revision sau xác nhận; sửa nhóm trong transaction và có undo trong phiên. Undo từ chối phiên bản đã bị chỉnh tiếp. Nguồn sửa làm bản dịch stale; bản dịch sửa thắng API cũ. SQLite lưu phiên bản cũ khi API dịch lại thành công. Có dấu báo thay đổi chưa xuất.

## Kiểm tra GUI và giới hạn

Bộ kiểm thử hồi quy hiện có **133 bài đạt, 0 thất bại**, bao gồm 90 bài trước (cập nhật kỳ vọng khởi động trống và schema migration), thêm 43 trường hợp cho đợt này. Lệnh: `python -m pytest -q --basetemp .pytest_review_complete`. Có kiểm tra caret đầu với dòng ngắn/dài, dropdown và cấu hình, điều hướng/tô sáng, thay thế/undo/late API, retry 1/3/5 dòng và trạng thái cũ, Word thật và fixture, JSON fence/ID thiếu/trùng. Không dùng mock để chấm chất lượng ngữ nghĩa.

Đã chạy Qt Windows bằng Python với DB tạm và file Word thật, không đọc key thật hoặc gửi API. Ảnh Light/Dark, khởi động trống, tìm/thay thế, cảnh báo ở `artifacts/gui/review`; report xác nhận DPI 125%, 125 đơn vị, 61 kết quả “evelyn”, cảnh báo điều hướng tới dòng 26. Cảnh báo có 125 dòng vì dữ liệu mock chỉ có một bản dịch và còn 124 dòng trống; không phải 125 lỗi API. Cửa sổ maximized và 1000×700/900×580 đã được xem ảnh. 900×580 khi mở cả thay thế có ít diện tích đọc; có thể đóng thanh tìm hoặc mở rộng cửa sổ.

Không gửi Kira/Gemini thật, không build EXE/installer, không sửa DOCX gốc hoặc reset SQLite người dùng. Muốn đo chất lượng dịch và schema thực tế cần một đợt Kira được duyệt riêng với model, số dòng/request, token/cost cap và timeout cụ thể; không retry 504/timeout. Metadata cũ không có raw response nên không thể xác định chính xác từng nguyên nhân ID sai trong ảnh; lỗi gateway 504 cũng chưa chứng minh nguyên nhân phía model/server.


## Retry / bulk update 2026-10-13

Latest report: [retry-management.md](retry-management.md). Default for new jobs: five retries after the initial request (six attempts total). HTTP 504 uses the same frozen retry budget; HTTP 429 cooldown is separate from user pause. Workspace duplicate paths are blocked, dropdown wheel is safe, and completion notifications are enabled. Existing job budgets and history remain unchanged.
