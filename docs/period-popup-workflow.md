# Danh sách dòng dịch có dấu chấm — bổ sung mục 5

Đợt sửa source 1.0.2, không phát hành. Mở rộng mục 5 của `ui-five-fixes-1.0.2.md`.

## Cách sử dụng

1. Nút đỏ `⚠ X dòng dịch có dấu chấm` vẫn nằm ngay trên **Mở thư mục xuất**. Có hover và tooltip, tự ẩn khi X = 0. Một dòng có nhiều dấu chấm chỉ tính một lần.
2. Nhấn nút mở dialog **Các dòng dịch có dấu chấm**. Bảng có **Dòng gốc**, **Bản dịch**, **Tài liệu · Ngôn ngữ**. Số gốc lấy từ `ordinal + 1`, giữ đúng khi lọc hoặc có dòng bị xóa.
3. Preview lấy đoạn quanh dấu chấm đầu tiên của dòng dài; tô đỏ dấu chấm ASCII. Dùng plain text, không diễn giải HTML có trong bản dịch.
4. Click mục hoặc dùng mũi tên + Enter: đóng popup, mở đúng file/ngôn ngữ trong workspace, bỏ lọc nếu cần, cuộn và focus ô dịch theo ID. Highlight đỏ dấu chấm bằng lớp selection, không sửa văn bản.
5. **Esc** hoặc **Đóng** chỉ đóng danh sách. Không tự nhảy tuần tự. Mục đã rời phạm vi không được dùng để mở lại lịch sử khác.

## Đồng bộ và bảo vệ dữ liệu

- Phạm vi: tất cả file/ngôn ngữ trong `workspace_ids` hiện mở, không phụ thuộc dòng chọn hay filter. Không đếm nguồn, NULL/trống hoặc lịch sử đóng.
- Model/view ảo, không tạo widget cho từng mục. Query theo chunk 500 ID; cache theo tổng thay đổi SQLite và tập workspace. Không query nội dung trong paint.
- Badge debounce 80 ms. Popup mở dùng timer 120 ms kiểm tra chữ ký; chỉ query lại khi dữ liệu/phạm vi thay đổi. Timer dừng khi popup đóng.
- Giữ selection bằng `(document_id, line_id)`. Đối chiếu ID giữa mouse press/release; nếu bảng đổi dưới con trỏ thì không chọn nhầm. Trước điều hướng luôn xác minh lại storage và workspace.
- Sửa hết dấu chấm: badge ẩn, popup đang mở hiển thị trạng thái trống an toàn. API, sửa tay, replace/undo, native undo/redo, reload, đổi tài liệu và bỏ file đều đồng bộ.
- Mở popup không đóng editor đang sửa. Điều hướng bằng popup giữ nguyên widget editor cùng undo stack trong RAM; khi quay lại chỉ tái sử dụng nếu nội dung và revision vẫn khớp storage. Không phục hồi bộ đệm cũ đè lên nội dung sửa bên ngoài. Bỏ bộ đệm khi file rời workspace.
- Không chuyển riêng QTextDocument giữa các editor: cách đó đã bị loại sau khi regression phát hiện lỗi vòng đời Qt. Giữ cả editor, tháo kết nối autosave cũ khi cất và nối lại với index mới khi dùng lại.
- Không thay truy vấn hay undo stack tìm/thay. Highlight dùng offset UTF-16 để đúng khi có emoji trước dấu chấm.

## File và trách nhiệm

| File | Thay đổi |
|---|---|
| `transcomic/ui/period_warning.py` | Nút, snapshot, cache, xác minh ID, điều hướng, giữ editor và highlight |
| `transcomic/ui/period_dialog.py` | Dialog, model bảng, preview, click/keyboard và trạng thái trống |
| `transcomic/ui/model.py` | Paint highlight, bảo toàn editor/undo và phục hồi có kiểm tra revision |
| `transcomic/ui/main.py` | Đóng popup, dừng timer và hủy điều hướng chờ trước khi đóng storage |
| `transcomic/ui/glass.py` | Role cảnh báo đỏ, giữ hover Liquid Glass |
| `tests/test_period_dialog.py` | Regression mới |
| `tests/test_ui_five_fixes.py` | Kiểm tra cache SQL phù hợp truy vấn có alias |

## Kiểm thử

- Đầu/giữa/cuối/ellipsis, đếm theo dòng, nhiều dòng, đoạn dài và plain text.
- Click mở, số gốc, ID, Esc/Đóng, không đổi dữ liệu.
- Dòng 2.005 trong tài liệu 2.200 dòng đang lọc: cuộn/focus đúng.
- File/ngôn ngữ khác có cùng số dòng; callback restore scroll/editor không ghi đè đích điều hướng mới.
- API mock cập nhật, đổi nội dung khi popup mở, hết dấu chấm, đóng file, dòng bị xóa; snapshot đổi giữa mouse press/release.
- Undo/redo sau Esc, chọn cùng ô, đổi ô và đổi tài liệu; replace/undo; từ chối cache revision cũ.
- Đóng ứng dụng khi popup mở hoặc khi vừa chọn mục và callback điều hướng chưa chạy: không dùng storage/widget sau khi đóng.
- 3.000 mục, Light/Dark, scrollbar, kích thước giới hạn theo màn hình; không query lại nội dung theo paint/timer khi dữ liệu không đổi.

Kết quả và ảnh tại `artifacts/period-popup/`, tách khỏi bằng chứng đợt trước:

- Native Windows: **40 PASS, 0 FAIL, 0 SKIP ở mỗi DPI 100%, 125%, 150%** (DPR đo được 1.0/1.25/1.5), gồm cả Light/Dark, 16 case popup và 24 regression của năm hạng mục trước. XML: `dpi100.xml`, `dpi125.xml`, `dpi150.xml`.
- GUI source smoke: **3/3 PASS**, cả ba DPI và hai theme, TXT/DOCX/export, tìm/thay/undo, queue clear, SRT placeholder và Safe Exit 900 ms; process thoát được launcher xác minh. Mỗi lượt dùng profile riêng, 0 real HTTP, 0 installer process. Xem `smoke100/report.json`, `smoke125/report.json`, `smoke150/report.json`.
- Ảnh `dpi100/popup-False.png`, `dpi150/popup-True.png` và ảnh editor cùng thư mục. Ảnh QWidget không bao gồm thanh tiêu đề native Windows; tiêu đề dialog được regression đối chiếu chính xác.
- Full offline regression: **986 PASS, 0 FAIL, 0 SKIP**, 293,44 giây; kết quả ở `full.xml` và `full.log`. Bản tổng hợp máy đọc được: `acceptance.json`.

## Phạm vi bàn giao

Không gọi API thật trong phần bổ sung này. Không đổi version, schema, key, tài liệu gốc, release journal hoặc Auto Release; không commit/publish. Các thay đổi năm hạng mục trước vẫn được giữ trong workspace.
