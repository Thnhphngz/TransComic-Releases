# Hoàn thiện giao diện và cảnh báo bản dịch — source 1.0.2

Mục 5 đã được mở rộng sau đợt nghiệm thu này: xem [popup danh sách dòng có dấu chấm](period-popup-workflow.md). Các số kiểm thử bên dưới là bằng chứng của đợt đầu; phần bổ sung có báo cáo riêng.

Yêu cầu: attachment `3e917b9e-b51a-43a6-9363-f9b010d6b9dd`, ngày 15/10/2026.
Đây là thay đổi mã nguồn chưa commit; không phải đợt phát hành.

## A. Năm hạng mục

| Hạng mục | Nguyên nhân / phát hiện | Mã sửa và kết quả |
|---|---|---|
| Sidebar thu gọn | `GlassButton.paintEvent` vẫn dành khoảng cách cho chữ khi text rỗng; SVG API còn có lề trong suốt bất đối xứng. Brand row chưa có alignment riêng khi ẩn chữ. | `ui/glass.py`: nhánh icon-only căn giữa, `centered_icon()` căn vùng alpha trong canvas hiện có. `WorkspaceV2Mixin.update_branding()` căn logo và dùng icon đã chuẩn hóa chỉ khi thu gọn. Giữ layout/icon gốc khi mở rộng, kích thước nút, màu, hover và checked. |
| Dấu × tài liệu | Phát hiện trường hợp `visualRect.width=230` nhưng viewport chỉ rộng 192 ở panel hẹp; size hint cố định và cache kích thước của QListView có thể đặt vùng thao tác ngoài phần nhìn thấy. Paint và hit test trước đây nhận rect từ hai nơi. | `DocumentDelegate.sizeHint/card_rect/paint`, `DropList.hit_action/mouseDoubleClickEvent`, `DocumentsPanel`: cùng dùng viewport logic, Adjust khi resize, không nhân/chia tọa độ chuột theo DPR. Giữ hàng 112 logical px và hitbox 32×32. Không tạo widget cho mỗi thẻ. |
| Xóa Gemini key | Modal confirmation chạy event loop; refresh `clear()` hủy QListWidgetItem được giữ trước modal. | `Stage2Mixin.edit_gemini_key()` sao chép ID trước modal, bỏ tham chiếu item; guard thao tác lồng nhau cho add/delete/reorder, refresh trong finally. `refresh_gemini_keys()` dùng QSignalBlocker. Key biến mất trong modal được xử lý bằng lỗi storage hiện có. |
| MiMo Kira | Registry chỉ có `coding-mimo-v2.6-flash`, thiếu model thường. | `models.py`: thêm `MiMo V2.6 Flash` → `mimo-v2.6-flash` ở cuối danh sách để giữ thứ tự model cũ. Dùng mapping/lưu settings hiện có, không đổi default, base URL hoặc key. |
| Cảnh báo dấu chấm | Chưa có indicator dành riêng cho ASCII period. | Module mới `ui/period_warning.py`, `PeriodWarning.schedule/recount`; tích hợp trong `WorkspaceV2Mixin.setup_v2/adapt_v2_toolbar/refresh_document_panel`. Không thay đổi bản dịch hoặc trạng thái dịch. |

**Giới hạn chẩn đoán ×:** đã tái hiện lỗi chiều rộng viewport nêu trên và kiểm thử click đúng glyph render. Chưa tái hiện riêng hiện tượng chỉ click góc dưới phải trên laptop 1; không khẳng định đã xác định mọi khác biệt của máy đó. Cần kiểm tra lại trên laptop 1 bằng mã nguồn mới.

## B. Kiểm thử và bằng chứng

- Regression mới: `tests/test_ui_five_fixes.py`; mọi tài liệu và Gemini key đều là fixture tự tạo trong storage riêng.
- Native GUI dùng Qt platform `windows`, ba process độc lập. DPR đo thực tế: **1.0 / 1.25 / 1.5**, tương ứng scale **0.8 / 1 / 1.2** trên màn hình Windows hiện tại.
- DPI 100%: **24 PASS, 0 FAIL, 0 SKIP**; DPI 125%: **24 PASS, 0 FAIL, 0 SKIP**.
- DPI 150%: **24 PASS, 0 FAIL, 0 SKIP**, gồm cả bốn case provider mock: JSON đầy đủ/thiếu ID/504/timeout, mỗi case một send.
- Cả Light và Dark: kiểm tra bounds pixel thực của từng icon; lấy vị trí glyph × từ raster rồi QTest click vào viewport; resize/cuộn; badge không chồng nút thư mục ở cửa sổ 1400 và 950 logical px.
- Gemini: refresh trong confirmation, đổi selection, nested delete/reorder/add, cancel, rỗng, stale key, reorder hai chiều, mở lại MainWindow bằng cùng DB fixture. Không dùng Gemini API thật.
- Focused regression gồm các case từng phát hiện lỗi khởi tạo: **28 PASS, 0 FAIL, 0 SKIP**; thêm một case long-row GUI đã qua sau sửa assertion. Đã thêm guard để refresh chạy trong lúc dựng workspace không truy cập badge chưa tồn tại; fixture mới kiểm tra không có `gui_error` ngay khi mở MainWindow. Cập nhật assertion layout cũ trong `test_final_workflow.py` và `test_gui.py` để kiểm tra wrapper chứa badge + nút thư mục và tọa độ chung trên editor; vẫn giữ kiểm tra thứ tự, không chồng lấn và fit trong cửa sổ.
- GUI smoke bằng source ở cả ba DPI: **3/3 PASS**, Light/Dark, TXT/DOCX, render/export DOCX, giữ nguồn, search/replace/undo, clear queue, update UI mock, SRT placeholder, Safe Exit deadline 900 ms và process exit. Profile được launcher cô lập; **0 real HTTP, 0 installer process**.
- Bằng chứng: `artifacts/ui-five-fixes/dpi100.xml`, `dpi125.xml`, `dpi150.xml`; ảnh và `dpi.json` ở các thư mục cùng tên; `smoke100/report.json`, `smoke125/report.json`, `smoke150/report.json`.
- Full offline regression cuối: **970 PASS, 0 FAIL, 0 SKIP**, 264,84 giây. Kết quả tại `artifacts/ui-five-fixes/full-final.xml` và `full-final.log`. Các lượt dừng để sửa lỗi trong lúc phát triển không được tính là kết quả nghiệm thu.

Không build installer mới: yêu cầu cho phép GUI smoke, và đợt này chỉ sửa source.

## C. Kira model và thử thật

- Nguồn Kira: [model detail](https://kiraai.vn/models/mimo-v2.6-flash/), [API docs](https://kiraai.vn/documents/).
- **1 GET** `/api/v1/models`: HTTP 200, danh sách có đúng ID `mimo-v2.6-flash`.
- **1 POST** `/api/v1/chat/completions`: HTTP 200; gửi đúng model trên, ba dòng tự tạo qua `KiraProvider.translate`, parser nhận đủ ID.
- Kết quả: `Hello`; `The weather is very nice today`; `Thank you for helping me`.
- Usage: **281 input + 53 output = 334 token**. Tổng **2 request / 3 dòng**, **0 retry**, không fallback model/key.
- Dùng giá gốc chưa giảm trên trang Kira: input 3.640đ/M, output 7.280đ/M; ước tính **1,40868đ**, khoảng **0,000070434 USD** với giả định bảo thủ 20.000đ/USD. Đây là ước tính theo usage; không phải hóa đơn thực tế.
- Reservation tạo độc quyền trước request: 2 request, 3 dòng, 2.574 token dự trù (input upper estimate 1.550 + output cap 1.024), chi phí upper estimate 0,000654836 USD; thấp hơn đồng thời mọi trần được cấp.
- Chỉ đọc hàng credential Kira từ DB ở chế độ read-only, giải mã trong RAM. Không đọc/gửi tài liệu hay lịch sử người dùng; không in/lưu key. Không gọi Gemini thật.
- Bằng chứng riêng: `artifacts/ui-five-fixes/live-reservation.json`, `request-1.reserved.json`, `request-2.reserved.json`, `live-result.json`; script `live_mimo_probe.py` từ chối chạy lại khi reservation đã tồn tại.

## D. Cảnh báo dấu chấm

- Phạm vi: tất cả `workspace_ids` hiện mở, gồm mọi biến thể ngôn ngữ của các file đó. Không phụ thuộc dòng chọn, bộ lọc bảng hoặc ngôn ngữ đang xem; không quét lịch sử đóng. Một hàng của một ngôn ngữ được tính là một bản dịch.
- SQL chỉ kiểm tra `instr(translation, '.') > 0`, không đọc cột nguồn; NULL/trống không tính. Có dấu chấm ở bản dịch đang lỗi hoặc chưa hoàn tất vẫn tính vì yêu cầu dựa trên nội dung.
- Cập nhật khi model dataChanged/modelReset, API queued updates, edit/autosave, native undo/redo, replace/undo, reload/open, workspace thêm/bỏ file và đổi ngôn ngữ. Các refresh dùng timer debounce 80 ms.
- Cache theo tổng thay đổi SQLite và tập workspace ID; progress poll không đổi dữ liệu sẽ không quét lại nội dung. Query theo chunk 500 ID, dưới store lock; không thêm schema/migration và không giữ bản sao bản dịch.
- Một QLabel đỏ duy nhất, trong VBox layout ngay trên nút “Mở thư mục xuất”, căn phải. Khi không còn dấu chấm thì ẩn. Wrapper đi cùng nút qua layout responsive; không dùng overlay/tọa độ tuyệt đối.
- Có test đầu/giữa/cuối/ellipsis, nhiều hàng/nhiều ngôn ngữ, source-only, NULL/trống, `!`, `?`, dấu Unicode `…`, API mock, thêm/xóa, native undo/redo, replace/undo, reload, đổi tài liệu/filter và đóng file. Đếm không sửa nội dung, không biến batch thành thất bại.

## E. Trạng thái bàn giao

- Đã sửa năm hạng mục và có kết quả thử thật Kira thành công trong quyền được cấp.
- Cần người dùng kiểm tra trực tiếp dấu × trên laptop 1 sau resize/thu gọn panel/DPI máy đó; test tự động không thay cho xác nhận phần cứng ấy.
- Source version vẫn **1.0.2**; không commit, tăng version, chạy BAT release/build-only, publish, sửa tag/journal, xóa build/backup hay đổi cơ chế Auto Release V2.
- Không đổi schema, tài liệu gốc, lịch sử, key hoặc settings thật. API thử có tiêu thụ usage/chi phí Kira như mục C.
- Các file đang sửa: `transcomic/models.py`, `transcomic/ui/documents_panel.py`, `glass.py`, `stage2.py`, `workspace_v2.py`, `tests/test_final_workflow.py`, `tests/test_gui.py`; file mới `transcomic/ui/period_warning.py`, `tests/test_ui_five_fixes.py` và báo cáo này. Artifacts nằm trong vùng đã được Git ignore.
