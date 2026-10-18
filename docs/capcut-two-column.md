# CapCut — bố cục danh sách nhóm / chi tiết media

19/10/2026 · Source **v1.1.0** · Chưa phát hành.

## A. Layout và sidebar chính

Trang CapCut hiện gồm header và ba nút quản lý ở trên; QSplitter ngang chứa danh sách nhóm trái và một inspector phải; thiết lập xuất trải ngang bên dưới. Không còn accordion, bảng trong từng thẻ, nút Mở tất cả/Thu gọn tất cả hoặc tab chi tiết. Chưa chọn nhóm thì bảng rỗng và có hướng dẫn; không có nhóm thì hiện **Chưa có nhóm nào. Nhấn Thêm nhóm để bắt đầu.**

Không sửa `MainWindow`, sidebar, navigation, icon, branding hoặc layout các trang khác. Hash `transcomic/ui/main.py` khớp snapshot trước sửa. Regression kiểm đủ 9 nút, icon không rỗng và pixel icon không đổi khi Dịch ↔ CapCut; sidebar thu gọn/mở lại và nhóm đang chọn vẫn giữ trong phiên. Không tạo navigation ngang như ảnh minh họa.

Splitter mặc định khoảng **27% / 73%**, hai pane không được collapse hoàn toàn, tối thiểu 220 / 310 logical px. Handle riêng rộng 7 px, không chồng lên pane. Kéo splitter giữ tỷ lệ trong phiên; không thêm persistence mới cho tỷ lệ hoặc lựa chọn nhóm.

## B. Danh sách nhóm

`QListView` + `GroupListModel` + proxy tìm kiếm + delegate vẽ thẻ, không tạo QWidget cho mỗi nhóm hoặc media row. Hàng nhóm cao 86 logical px, tên 15 px / DemiBold, số thứ tự từ thứ tự thật trong manager, số ảnh/voice/cặp và trạng thái. Không lặp hai đường dẫn dài trên mỗi hàng; tooltip giữ tên/đường dẫn đầy đủ.

- Tìm theo tên hoặc đường dẫn, không phân biệt hoa thường. Chỉ lọc hiển thị, không thay manager/order/planner. Summary được cache khi dữ liệu đổi; gõ tìm nhóm không dựng lại summary hoặc model media.
- Chọn bằng chuột/phím dùng ID nhóm, không dùng index hiển thị làm ID. Nhóm bị lọc khỏi danh sách hoặc bị xóa → bỏ selection, xóa dữ liệu/preview cũ và về empty state; không tự chọn nhóm khác ngoài ý muốn.
- Sửa, lên, xuống, xóa và sort ảnh nằm trong header inspector. Lên/xuống theo manager thật, kể cả danh sách đang lọc. Không quét lại chỉ vì chọn nhóm; sửa/sort vẫn dùng luồng scan hiện có.
- Khi scan, vẫn chọn/xem nhóm khác được; nút thay đổi nhóm và cấu hình bị khóa. Sau khi scan trả kết quả, inspector cập nhật đúng ID hiện tại. Clear All vẫn xác nhận với Hủy mặc định; không xóa media/project và không cho clear khi export.

## C. Bảng chi tiết và tài nguyên

Một `GroupDetails`, một `PairModel` và proxy hiển thị dùng chung cho toàn workspace. Đổi nhóm reset search/lọc file/selection/preview cũ và dừng audio. Cập nhật cùng nhóm không reset scan/model nếu snapshot không đổi.

Các cột mặc định: **STT / Ảnh / Tên ảnh / File audio / Thời lượng / Trạng thái**. STT là số cặp từ source model; đây chỉ là trình bày, không đổi mapping. Nút **Ngày tạo** mở cột Date created hiện có, giữ timestamp/tooltip và không dùng Date modified thay thế. Tìm file và Chỉ hàng lỗi giữ proxy cũ. Thời lượng vẫn hiển thị `mm:ss.mmm`; microseconds nguồn không đổi.

Thumbnail lấy từ file fixture/source thực qua worker lazy có giới hạn; chỉ yêu cầu row đang nhìn thấy. **Xem ảnh** mở vùng preview lớn hơn thumbnail ngay trong inspector; không tải toàn bộ ảnh gốc vào RAM. Nghe voice/Dừng dùng player dùng chung hiện có, chỉ phát khi người dùng bấm. Đổi nhóm, đổi trang, xóa và đóng cửa sổ dừng player, xóa source/entries phù hợp.

Giữ hai worker thumbnail cấp trang, cache thumbnail 128 / pending tối đa 32, preview cache 2. Test 100 nhóm × 1.000 media row tổng hợp kiểm một inspector duy nhất, scroll đến cuối, lọc, chuyển nhanh nhiều nhóm, không thêm worker/player và shutdown/join worker an toàn. Không dùng `setIndexWidget` cho media.

## D. Thiết lập xuất

Giữ ba mode, tên chung, số part, custom name editor compact từ đợt trước, menu khôi phục tên mặc định, validation và persistence. Preview chia tối đa hai hàng nhìn thấy, cao không quá 94 logical px và cuộn đến các part khác. Form count/hướng dẫn ở trái, preview ở phải; không làm bảng media co theo số part.

Panel có viền 1 logical px theo theme, nút **Thu gọn/Mở rộng thiết lập**. Thu gọn chỉ ẩn form, không thay config; Xuất/Hủy/Mở thư mục xuất luôn giữ bên ngoài form. Khi trang thấp hơn 760 logical px, mặc định thu gọn để dành chỗ cho media; trang cao hơn tự mở lại. Sau khi người dùng bấm toggle, lựa chọn thủ công được giữ khi resize trong phiên.

Đã xuất mẫu offline bốn project bằng engine hiện có: `vote_1-6`, `vote_7-12`, `vote_13-16`, `vote_17-20`. Thư mục/metadata đúng tên; tổng 20 cặp từ 10 nhóm, source hash giữ nguyên. [Biên nhận](../artifacts/capcut-two-column/export-sample/acceptance-light-100.json), [project fixture](../artifacts/capcut-two-column/export-sample/demo-projects/split).

## E. Responsive / Light / Dark / DPI

Đo toàn MainWindow có sidebar chính mở 200 logical px, 10 nhóm, split 4. Cả Light/Dark và scale 1/1,5 có cùng geometry logical:

| MainWindow logical | Cột trái / phải | Panel xuất | Viewport media | Trạng thái thiết lập |
|---|---:|---:|---:|---|
| 1280×720 | 285 / 760 | 82 | 272 | Mặc định thu gọn form |
| 1600×900 | 372 / 993 | 244 | 290 | Mở đầy đủ |
| 1920×1080 | 460 / 1225 | 244 | 470 | Mở đầy đủ |

Đường dẫn elide với tooltip/copy đầy đủ; header/action flow xuống hàng khi không đủ chỗ. Table có horizontal scroll nếu không đủ chiều ngang; cột ngày tạo ẩn mặc định nhưng vẫn mở được. Nếu chủ động mở toàn bộ form ở cửa sổ thấp, bảng còn ít chỗ hơn; người dùng thu gọn lại để xem media.

Các độ phân giải trên là **logical pixels của Qt**, không mặc nhiên là độ phân giải vật lý màn hình. Ở scale 150%, ảnh tương ứng 1920×1080, 2400×1350, 2880×1620 physical pixels. Ví dụ ảnh `dark-150-1280x720.png` thực tế rộng 1920×1080 px. Các file `metrics-*.json` ghi cả hai kích thước, tránh nhầm lẫn. Giữ nguyên minimum size toàn ứng dụng; chưa bảo đảm fit một màn hình vật lý 1280×720 ở scale 150%.

## F. Regression

| Lượt | Kết quả |
|---|---|
| Focused GUI sau kết nối chức năng, 100% | **109 PASS**, 85,39 giây |
| Selection/sidebar/scan mới, 100% | **7 PASS**, 4,74 giây |
| Toàn bộ CapCut, 100% | **174 PASS**, 101,18 giây |
| Toàn bộ CapCut, 150% | **174 PASS**, 107,76 giây |
| Focused cuối cho cache tìm nhóm/selection/geometry, 100% | **22 PASS**, 23,84 giây |
| Focused cuối cho cache tìm nhóm/selection/geometry, 150% | **22 PASS**, 20,95 giây |

Các lượt overlap, không cộng thành số test duy nhất. [JUnit 100%](../artifacts/capcut-two-column/regression-100.xml), [JUnit 150%](../artifacts/capcut-two-column/regression-150.xml), [focused cuối 100%](../artifacts/capcut-two-column/focused-final-100.xml), [focused cuối 150%](../artifacts/capcut-two-column/focused-final-150.xml). Các lượt cuối không có FAIL/ERROR/SKIP.

Coverage gồm: 0/1/10/20/100 nhóm; chọn, tìm, sửa, xóa, reorder, sort, restart/persistence; thay nhóm lúc scan; stale preview/generation; thumbnail, ảnh lớn, audio mock, ngày tạo, duration, filter; theme/resize/splitter/sidebar; custom name/Enter/Esc/clipboard/menu; validation; ba mode xuất; 10 nhóm → 3/4 part; planner 100/103/200 nhóm; cover từng part, MAU/timeline/gap 0/direct paths, không copy/sửa source, collision và lỗi/hủy giữa part giữ project hoàn tất.

Đã chuyển các assert accordion cũ sang hành vi chọn nhóm/inspector thật, không thêm skip hoặc giữ UI giả để thỏa test cũ. Các test exporter/planner/media/split backend giữ nguyên.

Lượt thử đầu phát triển gặp `QFont.setWeight(int)` không đúng signature PySide6, gây lỗi paint và một process pytest thoát access violation. Đã dùng enum `QFont.DemiBold/Normal`. Hai lỗi GUI khác đã sửa: Qt tự chọn nhóm khác khi lọc, và handle splitter làm hai border chồng 1 px. Các lượt regression cuối không tái hiện các lỗi này. Đây là test Qt software trong process, không chạy lại quy trình Sandbox/CUDA gây BSOD trước đây.

## G. Source

| File | Thay đổi |
|---|---|
| `transcomic/ui/capcut_workspace.py` | Model/proxy/delegate nhóm, splitter, inspector và chọn ID |
| `transcomic/ui/capcut_cards.py` | Bỏ accordion; dựng workspace; form xuất compact/toggle; một bảng media co giãn; cột STT/ngày tạo/preview |
| `transcomic/ui/capcut_page.py` | Nối selection/search/CRUD/scan/clear với một inspector; resize form |
| `transcomic/ui/theme.py` | Selector riêng cho pane/list/inspector/handle CapCut |
| `scripts/check_capcut_workspace.py` | Capture toàn MainWindow, scale/theme/size/sidebar/validation/busy |
| `scripts/check_capcut_source.py` | Chuyển capture/fixture acceptance cũ sang inspector mới |
| `tests/test_capcut_workspace.py` | Empty/selection/scan/sidebar/cache search |
| `tests/test_capcut_single_page.py` | Thay test accordion bằng two-column, CRUD/preview/player/100 nhóm/geometry |
| `tests/test_capcut_compact_clear.py` | Chuyển lookup widget; giữ regression Clear All/fencing/hash |
| `tests/test_capcut_ui.py` | Dùng bảng shared thay card details |
| `tests/test_capcut_import.py` | Chọn nhóm/sort/actions trong inspector mới |
| `tests/test_capcut_names_header.py` | Typography/path label inspector mới |
| `tests/test_capcut_editor_border.py` | Kiểm geometry theo parent mới của form |
| `docs/capcut-two-column.md` | Báo cáo này |

[Đối chiếu hash/AST](../artifacts/capcut-two-column/protected-verification.json): **13 file giữ nguyên hash**, gồm backend CapCut, template MAU, `MainWindow`, media model/cache, custom name model/delegate, player, version và pyproject. **14 hàm Page giữ nguyên AST**, gồm export snapshot/worker, scan/generation completion, progress fencing, player, cancel, clear confirmation/guard, sort và save options. Clear workspace chỉ thay cleanup UI accordion bằng cleanup inspector; thứ tự save/cancel/generation/cache và rollback được kiểm hồi quy.

[Diff UI](../artifacts/capcut-two-column/ui-changes.diff); snapshot UI và test trước sửa lưu cùng thư mục artifact. Không thay Kira/Gemini/TTS/updater/history/editor dịch hay dữ liệu sản xuất.

## H. Screenshot toàn MainWindow

| Theme / scale | 1280×720 logical | 1600×900 logical | 1920×1080 logical | Sidebar thu gọn |
|---|---|---|---|---|
| Dark 100% | [Ảnh](../artifacts/capcut-two-column/dark-100-1280x720.png) | [Ảnh](../artifacts/capcut-two-column/dark-100-1600x900.png) | [Ảnh](../artifacts/capcut-two-column/dark-100-1920x1080.png) | [Ảnh](../artifacts/capcut-two-column/dark-100-sidebar-collapsed.png) |
| Light 100% | [Ảnh](../artifacts/capcut-two-column/light-100-1280x720.png) | [Ảnh](../artifacts/capcut-two-column/light-100-1600x900.png) | [Ảnh](../artifacts/capcut-two-column/light-100-1920x1080.png) | [Ảnh](../artifacts/capcut-two-column/light-100-sidebar-collapsed.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-two-column/dark-150-1280x720.png) | [Ảnh](../artifacts/capcut-two-column/dark-150-1600x900.png) | [Ảnh](../artifacts/capcut-two-column/dark-150-1920x1080.png) | [Ảnh](../artifacts/capcut-two-column/dark-150-sidebar-collapsed.png) |
| Light 150% | [Ảnh](../artifacts/capcut-two-column/light-150-1280x720.png) | [Ảnh](../artifacts/capcut-two-column/light-150-1600x900.png) | [Ảnh](../artifacts/capcut-two-column/light-150-1920x1080.png) | [Ảnh](../artifacts/capcut-two-column/light-150-sidebar-collapsed.png) |

Ảnh thêm: [editor tên đang có caret](../artifacts/capcut-two-column/dark-150-name-editor.png), [validation error](../artifacts/capcut-two-column/light-100-validation-error.png), [export locked](../artifacts/capcut-two-column/dark-100-export-locked.png), [720p mở form thủ công](../artifacts/capcut-two-column/dark-100-720-settings-open.png). Trạng thái busy trong capture được mô phỏng ở UI; worker export thật được chạy bằng fixture trong pytest và sample acceptance.

## I. Giới hạn

Qt software/offscreen trên Windows, font Segoe UI cục bộ, media/DB tổng hợp. Không mở CapCut thật, không nghe loa hoặc kiểm codec/output device vật lý, không thao tác IME trực tiếp hoặc kéo cửa sổ qua hai màn hình khác DPI. Cover vẫn được xác minh bằng file/metadata/pixel offline; cách CapCut hiển thị bìa không nghiệm thu thêm trong đợt này. Xem giới hạn physical resolution ở mục E.

Không build EXE/Installer, tăng version, commit/push/publish, API thật, driver, Sandbox hoặc GPU/CUDA. Những sửa đổi source có sẵn của nhiệm vụ trước được giữ nguyên.

## J. Trạng thái

**READY FOR USER ACCEPTANCE — source v1.1.0, chưa phát hành.** Giới hạn nghiệm thu desktop/physical resolution được ghi tại E và I.
