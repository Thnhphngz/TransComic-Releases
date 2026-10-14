# TransComic — Giao diện V2

Ngày kiểm tra: 13/10/2026. Thay đổi trực tiếp trên ứng dụng Python/PySide6 hiện có; giữ schema SQLite, snapshot TXT/DOCX, lịch sử, DPAPI, prompt, endpoint, ghép ID và guard revision. Không build EXE/installer. Không gọi Kira/Gemini thật trong đợt này. Gemini thật vẫn chưa được nghiệm thu; POST 404 trước đây không được gửi lại.

## A. Giao diện

- Sidebar rộng 200 px, thu gọn 72 px. Sáu trang riêng: Dịch, Hàng đợi, Lịch sử, API, Console, Cài đặt. Theme sáng/tối nằm dưới sidebar, thay đổi ngay và lưu SQLite; tooltip cho các nút khi thu gọn.
- Panel Tài liệu mặc định 260 px, có splitter đổi chiều rộng, nút thu gọn và nút mở lại. Danh sách dùng `QAbstractListModel`/delegate, không tạo widget riêng cho từng file. Scroll danh sách độc lập với bản thảo.
- Bỏ hoàn toàn dropdown workspace và nút Tùy chọn. Nhập tài liệu/thư mục, xuất đơn/hàng loạt, provider/model/nguồn/luồng, start/pause/stop, retry dòng chọn/dòng lỗi, cảnh báo, tìm/thay, filter và bỏ chọn đều hiển thị. Timeout/cỡ chữ/retry 504 chuyển vào Cài đặt.
- Toolbar đổi cách xếp khi cửa sổ hẹp. 900×580 vẫn có bảng cuộn, sửa ô đầy đủ và các thao tác trên màn hình. Cửa sổ nhỏ có ít dòng nhìn thấy hơn; thu gọn panel mở rộng hai cột bản thảo.
- Tiến độ từ worker được gom mỗi 40 ms để hạn chế repaint dồn dập. Đo chiều cao các dòng đang nhìn thấy và cập nhật ngay scrollbar trước repaint, tránh dịch chuyển khi API trả kết quả.

## B. Quản lý file

- Nhập nhiều TXT/DOCX hoặc kéo thả nhiều file, thư mục, thư mục con và hỗn hợp. Chỉ chấp nhận QUrl local, không nhận HTTP/URL host từ xa giả dạng file. Panel đổi viền/mô tả khi đang thả.
- Scanner duyệt bằng stack, sort tự nhiên, dedup đường dẫn đã resolve trong mỗi hành động; chặn vòng junction/symlink. Nhập lại vẫn có UUID mới. File hỏng/không hỗ trợ/thư mục rỗng được ghi vào tổng kết và xem qua Chi tiết nhập; không tự bật nhiều popup. Có thao tác nhập riêng/chọn encoding từ chi tiết.
- Test nhập **120 file trong một lần**, rồi nhập lại thành **121 thẻ độc lập**; kiểm tra một file DOCX hỏng, một file không hỗ trợ, một thư mục rỗng và vòng junction Windows.
- Thẻ file gom theo `source_instance`; các workspace ngôn ngữ vẫn có ID/line/revision riêng. Bấm X hoặc Bỏ các file đã chọn chỉ loại khỏi danh sách phiên làm việc. Khi đã dịch hoặc có job sống, phải xác nhận; job ẩn vẫn tiếp tục và có trong Hàng đợi. Không xóa snapshot, nguồn, bản dịch, lịch sử hay file xuất. Xóa vĩnh viễn vẫn thuộc thao tác riêng trong Lịch sử.

## C. Ngôn ngữ và biên tập

- Nguồn không cho nhập tùy ý, chỉ Việt/Anh/Indonesia. Chip EN/ID/VI chọn đích của lượt mới; nguồn tương ứng bị vô hiệu hóa, không cho bắt đầu nếu chưa chọn đích hợp lệ.
- Đang xem chỉ liệt kê các bản đã tạo của file hiện tại. Đổi ngôn ngữ hoặc file không tạo job/gửi request/tạm dừng lượt. Khi chuyển file, ưu tiên ngôn ngữ đang xem nếu file đó có bản tương ứng.
- Nhớ cuộn, checkbox dòng, ô đang sửa và vị trí caret theo document ID (tức theo file/ngôn ngữ). Flush sửa tay trước khi đổi; callback khôi phục kiểm tra document ID để không cuộn nhầm file.
- Kiểm thử EN/ID độc lập, chỉnh sửa tay được giữ trước phản hồi đến muộn, retry/cảnh báo/Search/Replace/Undo, TXT giữ encoding/EOL, DOCX giữ paragraph/table/locator.

## D. Logo

- Asset SVG tự thiết kế: hai bong bóng dịch và chữ T, bảng màu đồng/kem/espresso. Không dùng asset bên thứ ba.
- `transcomic-main.svg`, `transcomic-light.svg`, `transcomic-dark.svg`, `transcomic-sidebar.svg`, `transcomic-small.svg`; bộ icon điều hướng `nav-*.svg` cũng tự tạo.
- Dùng logo cho sidebar rộng/thu gọn, QMainWindow/QApplication icon, title bar/taskbar, tray và hộp thoại thoát. QIcon có phiên bản nhỏ 16/20/24 px; asset có thể sửa trực tiếp bằng trình biên tập SVG. Không tạo EXE để áp dụng logo.

## E. Scheduler

- Store và UI chấp nhận Kira 1–50, mặc định 30 nếu chưa lưu. Chuyển sang Gemini rồi về Kira không làm mất cấu hình Kira. Gemini tiếp tục dùng quota/cap riêng; UI khai báo concurrency Gemini tối đa 30 và chỉ cho dùng phần đã xác minh, mặc định 1.
- Giữ pool HTTP/worker chung toàn run; round robin giữa file/ngôn ngữ, không nhân concurrency theo file/đích và không gửi song song bằng cách đổi key Gemini.
- Mock kiểm tra **1/10/30/40/50** (giữ cả mức cũ 3/7): peak đúng trần, retry 504 đúng một lần, ID/context không trộn, stop lưu các request đang gửi và giữ phần chưa gửi pending. Các kiểm thử pause/resume/recovery/request budget cũ tiếp tục chạy.

## F. Kiểm thử và bằng chứng

**248/248 bài kiểm thử đạt, 0 thất bại** trong lượt `pytest` xác minh cuối (55,98 s). Bao gồm toàn bộ 227 bài cũ và các trường hợp mới/mở rộng, cả drop trên cửa sổ chính, editor trống và viewport bản thảo. Lệnh:

```powershell
python -m pytest -q --basetemp .pytest_v2_complete
python -X utf8 -m scripts.ui_v2_gui_smoke
python run_transcomic.py
```

Smoke chạy entry point thật `run_transcomic.py`, platform `windows`, LOCALAPPDATA riêng, HTTP `MockTransport`; không mở/sửa DB hay API key thật. Mỗi mức DPI: 5 file TXT/DOCX qua drag/drop → 10 workspace EN/ID, 300 POST mock, peak 50, pause/resume, chuyển file/ngôn ngữ, sửa tay, splitter/thu gọn/maximized/theme, bỏ file lúc job đang paused và xác minh job ẩn hoàn tất. Xuất 8 workspace còn nhìn thấy sau khi bỏ một file (hai bản ngôn ngữ); giữ nguyên cả 5 file nguồn.

- [DPI 100%](../artifacts/gui/v2/100/report.json)
- [DPI 125%](../artifacts/gui/v2/125/report.json)
- [DPI 150%](../artifacts/gui/v2/150/report.json)
- [Ảnh sáng 900×580](../artifacts/gui/v2/125/light-900.png)
- [Ảnh tối 900×580](../artifacts/gui/v2/125/dark-900.png)
- [Ảnh maximized](../artifacts/gui/v2/125/maximized.png)
- [Hàng đợi](../artifacts/gui/v2/125/queue.png), [API](../artifacts/gui/v2/125/api.png), [Console](../artifacts/gui/v2/125/console.png), [thoát](../artifacts/gui/v2/125/exit-dialog.png)
- [Hộp thoại nhập theo theme](../artifacts/gui/v2/125/import-dialog.png)

Ở màn hình vật lý 1920×1080, DPI 150% làm Windows giới hạn client yêu cầu 1200×720 xuống **1200×703** để chừa khung cửa sổ. Report ghi cả requested/actual; 900×580 đạt nguyên kích thước. Mock kiểm chứng luồng dữ liệu, không đo chất lượng dịch hay throughput của API thật. Không có nghiệm thu Gemini thật mới hoặc bản build mới.

### File chính

- `transcomic/ui/workspace_v2.py`: bố cục, target/view, trạng thái editor và bỏ file khỏi workspace.
- `transcomic/ui/documents_panel.py`: virtual list/model/delegate, tìm và drag/drop.
- `transcomic/ui/main.py`, `stage2.py`, `theme.py`, `exit_dialog.py`: tích hợp, queue riêng, cấu hình và branding.
- `transcomic/storage.py`, `bulk.py`: cap theo provider, scanner an toàn; giữ nguyên schema.
- `tests/test_workspace_v2.py`, `test_stage2_bulk.py`, `test_console_policy.py`: kiểm thử mới và mở rộng cap. Một test choice-only cũ được sửa để đặt tường minh cặp VI→VI cần kiểm tra, vì mặc định UI V2 là VI→EN; không bỏ kiểm tra noneditable/invalid model.
- `scripts/ui_v2_gui_smoke.py`: bằng chứng native Windows chỉ dùng HTTP giả lập.
