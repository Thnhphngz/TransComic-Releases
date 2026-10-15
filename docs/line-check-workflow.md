# Kiểm tra số dòng — hạng mục 6, source 1.0.2

**Cập nhật bố cục:** hàng nút và vị trí hai badge sau đợt này đã được tối ưu theo [toolbar-layout-1.0.2.md](toolbar-layout-1.0.2.md). Mô tả VBox bên dưới là bố cục của lần triển khai ban đầu; hiện hai badge nằm cạnh nhau trong hàng tiêu đề.

Theo yêu cầu `ba2e1b34-d53e-478c-8809-950e37e857a0`. Bổ sung trên các thay đổi giao diện và popup dấu chấm chưa commit của hai đợt trước. Không phát hành.

## Quy tắc đếm

- **TXT:** dùng `decode_txt/split_lines` hiện có. Một đơn vị là một dòng vật lý; giữ các dòng trống, khoảng trắng, dấu CRLF/LF/CR và trạng thái có/không dấu kết thúc. Ví dụ `A\n` có một dòng có dấu kết thúc, `A\n\n` có thêm một dòng trống. Không tự tạo dòng rỗng ảo sau newline cuối. File rỗng có 0 đơn vị và trạng thái trung tính.
- **DOCX:** dùng `inspect_docx` hiện có. Đơn vị là đoạn văn/segment có locator `paragraph:segment`; ngắt dòng, tab hoặc phần tử phân cách được mapper hiện tại giữ riêng. Có đoạn trống và đoạn trong bảng. Không đếm các hàng Word tự wrap trên trang. Cấu trúc Word chưa hỗ trợ vẫn bị từ chối bằng `UnsafeDocx` như trước.
- Tổng **Gốc** và **Vị trí dịch** tính mọi đơn vị, gồm dòng trống. **Thành công** chỉ tính nguồn cần dịch có bản dịch dùng được theo revision nguồn. Dòng trống/không có chữ theo quy tắc `translatable` được **giữ nguyên**, không giả làm kết quả dịch API. Chờ, đang xử lý và lỗi dịch được thống kê riêng.

## Ánh xạ và validation

`line_structure.validate_snapshot` chỉ đọc snapshot tách rời:

1. Đối chiếu checksum và các vị trí với bytes nhập gốc được lưu trong DB; không dựa vào file trên ổ đĩa có thể đã đổi.
2. Kiểm tra ID không rỗng/trùng, tài liệu sở hữu, ordinal, số vị trí, thứ tự, dấu kết thúc TXT và locator DOCX. `Store.units` dùng LEFT JOIN để việc mất mapping không làm dòng biến mất khỏi snapshot kiểm tra.
3. Nguồn chỉnh sửa hợp lệ dùng revision hiện có. Với variant ngôn ngữ cũ được tạo từ nguồn đã chỉnh sửa nhưng revision mới bắt đầu từ 0, dùng bằng chứng `line_edits` của source instance, không thêm migration hay sửa dữ liệu cũ.
4. Phát hiện CR/LF thực sự trong một đơn vị; không xem soft-wrap giao diện là lỗi. TXT còn chặn trực tiếp newline nhúng trong renderer, bên cạnh preflight chung.
5. `parse_line_response` dùng ID thay vì thứ tự trả về. Thiếu/thừa/trùng/sai ID, entry sai kiểu và xuống dòng đều có metadata `structure_errors` không chứa văn bản. ID trùng dù một entry có text sai kiểu cũng không được giữ giá trị mơ hồ.
6. Kira/Gemini cùng dùng parser và kiểm tra ID request trước HTTP. `Store.finish_batch` xác minh lần nữa trước normalize/lưu, không ghi xuyên tài liệu khi payload hỏng. Các phần hợp lệ được giữ; không tự ghép/tách nội dung hoặc gán theo vị trí trong response.
7. Snapshot gồm bằng chứng batch lỗi chưa được sửa. Lỗi mapping bị ưu tiên đỏ, kể cả còn dòng chờ. Khi sửa tay hoặc một lượt dịch mới thành công với revision mới, bằng chứng cũ được xem là đã vượt qua; không xóa lịch sử. HTTP 504/timeout đơn thuần không phải bằng chứng lỗi cấu trúc.

Không thêm request hoặc thay đổi chính sách retry của scheduler. Mọi thử nghiệm hạng mục này offline/mock.

## Thanh trạng thái và popup

- Phạm vi thanh số dòng là **tài liệu/ngôn ngữ đang xem**; tooltip nói rõ phạm vi. Popup dấu chấm vẫn giữ phạm vi workspace như yêu cầu trước.
- **Xanh:** `✓ Gốc N · Dịch N` khi không có lỗi cấu trúc và mọi đơn vị cần dịch có kết quả dùng được. Không chỉ so sánh hai số.
- **Trung tính:** `◷ Gốc N · Đã dịch X/Y` khi còn dòng chưa hoàn thành. Tài liệu không có đơn vị cần dịch ghi `Giữ nguyên`; chưa mở tài liệu không báo 0/0 thành công.
- **Đỏ:** `⚠ Lỗi cấu trúc · X dòng`; ưu tiên hơn chưa dịch xong. Lỗi cấp tài liệu được ghi một mục riêng nếu không thể gắn với ID dòng có thật.
- Thanh nằm ngay trên cảnh báo dấu chấm trong cùng VBox layout phía trên nút thư mục xuất, không overlay. Mỗi thanh độc lập, có hover và tooltip Liquid Glass.
- Click mở **Kiểm tra số dòng**, tái sử dụng `PeriodDialog/PeriodRows/PeriodTable`. Tóm tắt số gốc, vị trí dịch, thành công, giữ nguyên, chờ, đang dịch, lỗi dịch và lỗi cấu trúc. Bảng liệt kê vấn đề với số gốc, thông báo và đoạn trích; có file/ngôn ngữ để tránh nhầm.
- Chọn mục đóng bảng rồi dùng chung điều hướng ID của popup dấu chấm để bỏ lọc nếu cần, cuộn và focus đúng ô. Không thêm highlight dấu chấm từ bảng cấu trúc. ID đã mất/khác phạm vi không được điều hướng sang dòng lân cận; mục không có dòng thật chỉ dùng để giải thích.
- Giữ nguyên editor/undo stack khi chuyển qua các bảng kiểm tra; cache có revision cũ không đè nội dung mới. Popup cập nhật khi API mock/sửa/undo/redo/replace/đổi tài liệu, có trạng thái trống. Khi khớp ghi `Không phát hiện lỗi cấu trúc dòng`.

## Bảo vệ xuất file

- `choose_export_plan`: preflight snapshot trước xác nhận đường dẫn; thông báo **Không thể xuất: phát hiện lỗi cấu trúc dòng.** Tài liệu hỏng bị loại khỏi kế hoạch; có thể mở bảng chi tiết của tài liệu đang xem. Các tài liệu hợp lệ khác vẫn xuất độc lập.
- `write_exports`: kiểm tra lại **đúng snapshot sẽ render**, trước render/mkdir/atomic write. Lỗi trả `blocked_structure`; file đích cũ không bị ghi đè, kể cả được truyền `existing='overwrite'` và `allow_incomplete=True`. Không sửa dữ liệu để vượt validation.
- Bản dịch còn thiếu vẫn bị chặn khi xuất hoàn chỉnh. UI có xác nhận mặc định **No**, nêu rõ chỉ xuất **bản nháp INCOMPLETE**; giữ khả năng draft và kiểm tra ngôn ngữ nguồn thay thế hiện có. Backend mặc định `allow_incomplete=False`.
- Dấu chấm tự nó không chặn xuất. Có test snapshot tách rời: sửa live sau khi chụp không đổi nội dung export đã xác nhận.

## File/function

| File | Trách nhiệm |
|---|---|
| `transcomic/line_structure.py` | `source_layout`, `validate_snapshot`, `LineReport`: quy tắc và báo cáo thuần dữ liệu |
| `transcomic/ui/line_check.py` | `LineCheck`: debounce, worker, cache, ba trạng thái, popup |
| `transcomic/ui/period_dialog.py` | Tái sử dụng bảng ảo cho cấu trúc, xử lý ordinal không có dòng |
| `transcomic/ui/period_warning.py` | `navigate_key`: điều hướng dùng chung, bảo toàn editor |
| `transcomic/ui/workspace_v2.py` | Bố trí hai thanh, nối signal/state |
| `transcomic/ui/model.py`, `main.py`, `glass.py` | Giữ undo khi focus popup, shutdown và màu success |
| `transcomic/providers.py`, `gemini.py` | Validation request, parser và diagnostics ID |
| `transcomic/storage.py` | `units`, `export_snapshot`, `finish_batch`: mapping/bằng chứng, kiểm tra trước lưu |
| `transcomic/documents.py`, `bulk.py`, `ui/exporting.py`, `ui/stage2.py` | Preflight và chặn ghi khi lỗi, thông báo GUI |
| `tests/test_line_structure.py`, `test_line_check_ui.py` | Regression mới |

## Hiệu năng và tương thích

- Kiểm tra UI chạy trên worker, debounce 100 ms; chỉ nhận kết quả cho đúng tài liệu. Cache source layout, chữ ký SQLite và tài liệu; không kiểm tra lại theo paint/mouse move. Worker kết thúc được loại khỏi danh sách tracking trước lượt sau.
- Đã thử tài liệu 5.000 dòng với heartbeat Qt khi cố ý làm chậm worker; event loop vẫn chạy. Bảng vấn đề dùng model/view ảo.
- Đo trên fixture 10.000 đơn vị: snapshot ~41 ms, parse source ~8,4 ms, validation ~36,1 ms trên máy thử. Đây là số đo cục bộ, không phải cam kết tốc độ máy khác; xem `artifacts/line-check/performance.json`. Validation không ghi DB.
- Test DB fixture mở lại theo schema 8 hiện có: ID/bản dịch/schema không đổi, không phát sinh ghi từ validation. Không mở DB người dùng để kiểm thử.
- Khi đóng ứng dụng: dừng timer/popup, bỏ kết quả worker tới muộn; không truy cập storage đã đóng. Safe Exit được kiểm tra trong GUI smoke.

## Kiểm thử và giới hạn

Kết quả cuối được lưu tại `artifacts/line-check/`:

| Kiểm thử | PASS | FAIL | SKIP | Bằng chứng |
|---|---:|---:|---:|---|
| Full offline trên mã cuối | 1.035 | 0 | 0 | `full-final.xml`, `full-final.log`; 308,59 giây |
| Windows native, Light/Dark, DPI 100% | 88 | 0 | 0 | `dpi100.xml`, `dpi100/` |
| Windows native, Light/Dark, DPI 125% | 88 | 0 | 0 | `dpi125.xml`, `dpi125/` |
| Windows native, Light/Dark, DPI 150% | 88 | 0 | 0 | `dpi150.xml`, `dpi150/` |
| GUI smoke từ source, ba DPI | 3 lượt | 0 | 0 | `smoke100/report.json`, `smoke125/report.json`, `smoke150/report.json` |

Full suite gồm 49 case mới trong `test_line_structure.py` và `test_line_check_ui.py`, bên cạnh regression của năm hạng mục và popup dấu chấm trước đó. Matrix native có 88 case mỗi DPI; case backend về response thành công rỗng được bổ sung sau matrix và đã nằm trong full suite cuối. Không cộng các lượt chạy lặp lại thành số test độc lập.

Các tình huống đã kiểm tra: đủ/thiếu/thừa/trùng/sai ID, response đảo thứ tự, newline thật và soft-wrap, TXT trống/CRLF/LF/CR, DOCX nhiều đoạn/đoạn trống/mất locator; ba trạng thái và cập nhật popup đang mở; điều hướng dòng 2.005 trong 2.500 dòng khi có bộ lọc; ID đã xóa/đổi tài liệu; sửa/undo/redo/thay thế; giữ kết quả hợp lệ của batch lỗi; chặn export trước ghi đè, bản nháp có xác nhận, xuất nhiều file độc lập và snapshot không đổi khi dữ liệu live thay đổi. Test DB fixture mở lại kiểm tra tương thích dữ liệu cũ; không dùng DB thật.

GUI smoke là ứng dụng source trên Windows, không phải một bản EXE mới. Mỗi lượt dùng profile riêng, kiểm tra TXT/DOCX, Light/Dark, tìm/thay/undo và Safe Exit; launcher quan sát process thoát thành công. HTTP bị mock, không tạo installer process. Ảnh `editor-False/True.png` và `popup-False/True.png` nằm trong từng thư mục DPI; `dpi.json` ghi DPR thực tế 1,0/1,25/1,5. `acceptance.json` tổng hợp XML, smoke, hiệu năng và trạng thái phiên bản/HEAD.

Không thể chứng minh ngữ nghĩa bằng đếm dòng: response đủ đúng ID nhưng gán nội dung nhầm về mặt nghĩa vẫn cần người đọc kiểm tra. Việc thay toàn bộ ID nhất quán bên ngoài DB hoặc sửa đồng thời snapshot/checksum/lịch sử vượt khỏi bằng chứng cấu trúc còn lưu cũng không thể tự phục hồi đáng tin cậy. Với dữ liệu cũ thiếu bằng chứng, UI không giả báo đã sửa hay tự tạo mapping.

Giữ source **1.0.2**. Không commit, Auto Release, tăng version, publish, sửa journal/tag, xóa backup/artifacts hoặc thay đổi dữ liệu thật. Các thay đổi chưa commit của năm hạng mục trước vẫn được giữ.
