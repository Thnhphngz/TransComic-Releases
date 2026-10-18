# CapCut — thao tác Phát/Dừng và Xem ảnh trên từng hàng

19/10/2026 · Source **v1.1.0** · Chưa phát hành.

## A. Vị trí nút và hành vi

Bảng có đúng bảy cột hiển thị: **STT / Ảnh / Tên ảnh / File audio / Thời lượng / Trạng thái / Thao tác**. Cột cuối nằm bên phải Trạng thái, mỗi hàng có hai nút icon: tam giác Phát (hoặc vuông Dừng ở hàng đang phát) và icon Xem ảnh. Tooltip giải thích chức năng/lỗi; bàn phím có accessible text/description.

Đã bỏ hoàn toàn `play_button`, `preview_toggle` và layout toolbar cũ dưới bảng. Không giữ widget ẩn giả để thỏa các test cũ. Shared player được dùng cho playback nhưng không hiện bộ nút điều khiển trùng dưới bảng. Khi mở ảnh, vùng preview hiện có xuất hiện; nút × riêng của preview đóng vùng ảnh, không phải toolbar thao tác hàng.

Click nút không cần chọn hàng trước và không đổi current index/selection. Hit test và hình vẽ dùng chung `button_rects`, kiểm cả điểm nhấn/thả và ID cặp. Thả ở nút khác/hàng khác không kích hoạt hành động ban đầu. Cột thao tác và tên file không editable; không mở editor khi click/double click nút.

Keyboard: điều hướng đến cột Thao tác; **trái/phải** chọn Phát hoặc Xem ảnh; **Enter/Space** kích hoạt. Giữ điều hướng lên/xuống và focus/selection của bảng; không có focus rectangle trắng dày. Accessible text của ô đổi Phát/Dừng theo đúng hàng.

## B. Một shared player và ID ổn định

Giữ `CapcutPlayer`/`AudioPlayer` hiện có; không tạo player cho từng hàng. `play_audio(details, pair)` nhận cặp từ proxy→source thay vì phụ thuộc hàng đang chọn. Inspector giữ `audio_pair` và `playing_pair_id`, với ID cặp từ scan. Nút Dừng chỉ hiện khi:

- Shared player thuộc inspector này.
- Backend thực sự ở `PlayingState`.
- URL nguồn của player khớp URL chuẩn hóa của file audio trong cặp đó.

Phát hàng khác dừng nguồn trước qua stop chung rồi gửi audio mới. Tín hiệu state thay đổi cập nhật ô thao tác của ID cũ/mới, không reset model. Audio tự kết thúc trở về Phát. Signal lỗi gọi stop chung để bỏ nguồn và trạng thái ngay cả khi backend chưa tự chuyển StoppedState.

Đổi bộ lọc/tìm file sử dụng quy tắc **dừng audio**, xóa preview/selection cũ. Chuyển nhóm/trang, xóa nhóm, Clear All và đóng ứng dụng tiếp tục dừng/cleanup hiện có. Nếu proxy sắp xếp, trạng thái không chuyển sang file khác vì không lưu row index làm định danh.

Nút bị vô hiệu nếu thiếu media, nhiều media không xác định được một file, có lỗi hoặc file mất/đổi sau scan. Kiểm availability lazily theo hàng nhìn thấy, cache tối đa 256 mục; click kiểm file lại. Preview decode thất bại hiển thị lỗi và vô hiệu Xem ảnh cho cặp đó cho đến snapshot scan mới. Kết quả preview async chỉ được áp dụng khi path/size/mtime khớp file đang xem; đổi nhóm không nhận lại ảnh cũ.

Không sửa/copy file ảnh/voice để preview hoặc phát.

## C. Độ rộng cột và diện tích bảng

STT tiếp tục theo font/số chữ số; thumbnail 88, duration 100, status 100, actions 104 logical px. **File audio mặc định 140 px, Interactive** để người dùng kéo tăng/giảm. **Chỉ Tên ảnh Stretch** nhận chiều rộng dư. Tên file elide giữa để giữ phần extension, tooltip có đường dẫn đầy đủ. Header/splitter/sidebar giữ nguyên.

Đo cùng fixture, sidebar 200 px mở, cùng font/theme/scale:

| MainWindow logical | Audio trước → sau | Tên ảnh trước → sau | Viewport media trước → sau |
|---|---:|---:|---:|
| 1280×720 | 203 → 140 | 204 → 163 | 286 → 328 |
| 1600×900 | 363 → 140 | 364 → 483 | 324 → 366 |
| 1920×1080 | 523 → 140 | 524 → 803 | 504 → 546 |

Ở 1280×720, cột Thao tác mới cần 104 px nên Tên ảnh giảm 41 px dù audio đã co; tên vẫn elide/tooltip và hai nút không ra ngoài viewport ở splitter mặc định. Ở màn hình rộng, Tên ảnh nhận phần lớn diện tích tiết kiệm. Không tuyên bố mọi cột đều rộng hơn khi thêm một cột mới.

Toolbar được bỏ giúp viewport tăng **42 logical px** ở cả ba kích thước; không thay chiều cao media row 62 px. [Số đo trước/sau](../artifacts/capcut-row-actions/layout-comparison.json). Các số đo giống nhau ở Light/Dark và scale 100%/150% trong tọa độ logical.

## D. Hiệu năng

- `ActionDelegate` kế thừa `RowDelegate`, vẽ trực tiếp bằng QPainter, giữ style focus/selection cũ. `ActionTable` xử lý hit/hover/pressed/tooltip/keyboard; không `setCellWidget`, `setIndexWidget` hay persistent editor.
- Một `ActionPairModel` kế thừa nguồn media hiện có, thêm cột thao tác; proxy loại cột ngày tạo khỏi giao diện. Metadata Date created trong source model và sort `created` vẫn giữ.
- ID→source row được lập khi load snapshot. Repaint trạng thái audio chỉ target ô action của hàng cũ/mới, accessible role cũng phát `dataChanged` đúng ô. Thumbnail async vẫn cập nhật cột thumbnail độc lập; không nhầm các signal thumbnail với reset playback.
- Test 10/184/1.000 hàng giữ số QWidget trong inspector không tăng theo số hàng, một player, hai worker thumbnail cấp trang, cache thumbnail ≤128/pending ≤32, availability ≤256. Cuộn tới cuối và click hàng cuối đúng ID, lọc/sort không reset model vì phát/dừng.

## E. Screenshot Light/Dark và DPI

Toàn MainWindow có sidebar thật; ảnh cận bảng cho thấy nút nằm trong từng hàng:

| Theme / scale | Toàn cửa sổ 1600×900 logical | Cận bảng | Hàng 1 Dừng, hàng khác Phát |
|---|---|---|---|
| Dark 100% | [Ảnh](../artifacts/capcut-row-actions/after/dark-100-1600x900.png) | [Ảnh](../artifacts/capcut-row-actions/after/dark-100-1600x900-table.png) | [Ảnh](../artifacts/capcut-row-actions/after/dark-100-row-playing-table.png) |
| Light 100% | [Ảnh](../artifacts/capcut-row-actions/after/light-100-1600x900.png) | [Ảnh](../artifacts/capcut-row-actions/after/light-100-1600x900-table.png) | [Ảnh](../artifacts/capcut-row-actions/after/light-100-row-playing-table.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-row-actions/after/dark-150-1600x900.png) | [Ảnh](../artifacts/capcut-row-actions/after/dark-150-1600x900-table.png) | [Ảnh](../artifacts/capcut-row-actions/after/dark-150-row-playing-table.png) |
| Light 150% | [Ảnh](../artifacts/capcut-row-actions/after/light-150-1600x900.png) | [Ảnh](../artifacts/capcut-row-actions/after/light-150-1600x900-table.png) | [Ảnh](../artifacts/capcut-row-actions/after/light-150-row-playing-table.png) |

Ảnh thêm: [Dark 1280×720](../artifacts/capcut-row-actions/after/dark-100-1280x720.png), [Dark 1920×1080](../artifacts/capcut-row-actions/after/dark-100-1920x1080.png), [sidebar thu gọn](../artifacts/capcut-row-actions/after/dark-100-sidebar-collapsed.png). Cả bốn theme/scale đều có ảnh ba kích thước, bảng cận cảnh, sidebar thu gọn, editor tên part, validation và export locked trong `after/`.

Ảnh trạng thái Dừng dùng backend mô phỏng tín hiệu để không phát audio trên máy host. Ảnh default dùng scan/thumbnail thực của file fixture. Đây không phải bằng chứng đã nghe audio qua loa.

Qt software/offscreen; kích thước là logical pixels. Scale 150% tạo ảnh physical lớn hơn 1,5 lần. Chưa nghiệm thu màn hình vật lý 1280×720 ở scale 150%, IME, screen reader thật hoặc kéo qua màn hình khác DPI. Nếu người dùng kéo pane media cực hẹp hoặc tự tăng column quá lớn, Qt có thể cần horizontal scroll; các cấu hình cửa sổ/splitter mặc định nêu trên giữ Thao tác trong viewport.

## F. Regression

- Focused GUI sau nối row actions: **88 PASS**, 65,78 giây.
- Regression toàn bộ CapCut 100%: **212 PASS**, 132,02 giây.
- Regression toàn bộ CapCut 150% cuối: **212 PASS**, 131,79 giây.
- Focused row actions cuối 100%: **17 PASS**, 13,91 giây; 150%: **17 PASS**, 15,17 giây. Case lỗi backend chưa tự dừng cũng được kiểm riêng ở 100%: **1 PASS**, 1,92 giây.

[Regression 100%](../artifacts/capcut-row-actions/regression-100.xml), [regression cuối 150%](../artifacts/capcut-row-actions/regression-final-150.xml), [focused cuối 100%](../artifacts/capcut-row-actions/focused-final-100.xml), [focused cuối 150%](../artifacts/capcut-row-actions/focused-final-150.xml), [audio error cuối](../artifacts/capcut-row-actions/audio-error-final-100.xml). Các lượt cuối không có FAIL/ERROR/SKIP.

Case mới: click Phát/Dừng không chọn trước; hàng 2 dừng hàng 1; EndOfMedia/error; thiếu/corrupt/mất/đổi file; xem đúng ảnh 1/2 và đóng preview; decode null an toàn; mouse hover/pressed/thả khác nút; tooltip; Enter/Space/trái/phải; filter/sort/đổi nhóm/trang/đóng app; long audio extension; 10/184/1.000 hàng, widget/worker bounds; resize và user resize audio column.

Các test UI cũ được chuyển entry point từ button dưới bảng sang action index thật; source Date created vẫn kiểm trên model, seven visible columns kiểm trên proxy. Regression backend exporter/planner/media/split không thay đổi, gồm ba mode, template MAU, tracks/keyframes/animation, media order, gap 0, direct paths, source hash, collision/cancel/atomic staging, cover đúng part và custom names/persistence.

Lượt focused đầu có hai assert sai ở test: nhận `dataChanged` thumbnail async như playback, và QTest mouseMove tới đúng tọa độ con trỏ cũ không phát event. Đã tách signal thumbnail và di chuyển con trỏ ra ngoài trước kiểm hover; không bỏ/skip test.

Lượt regression 150% đầu có **210 PASS / 2 FAIL** tại assert hover của Light/Dark: `QTest.mouseMove` thao tác con trỏ OS không cung cấp tọa độ mong đợi khi cửa sổ offscreen vượt virtual screen ở scale 1,5. Đã gửi `QMouseEvent.MouseMove` thực qua viewport trong tọa độ logical để kiểm handler hover/pressed; click/release/keyboard vẫn dùng event Qt. Hai case không bị bỏ qua. Lượt focused 150% sau sửa test đã PASS cả 17 case.

Không chạy API thật, TTS/inference, CapCut thật, Sandbox hoặc CUDA/GPU. Audio backend mô phỏng có state/signal/source; chưa nghiệm thu âm thanh/codec/device vật lý. Các lượt có overlap, không cộng thành số test duy nhất.

## G. Source và bảo toàn engine

| File | Thay đổi trong đợt này |
|---|---|
| `transcomic/ui/capcut_actions.py` | Model bổ sung action, delegate, table hit/keyboard/tooltip và preview close |
| `transcomic/ui/capcut_cards.py` | Proxy 7 cột, bỏ toolbar, row actions/ID/state/preview/availability, widths |
| `transcomic/ui/capcut_page.py` | Playback nhận pair tường minh, shared player ẩn, sync/error cleanup |
| `tests/test_capcut_row_actions.py` | 17 tests mới cho hành động theo hàng và hiệu năng |
| `tests/test_capcut_final_polish.py` | Chuyển columns/availability, thay test toggle cũ bằng test row actions đầy đủ |
| `tests/test_capcut_single_page.py` | Entry point action và model/proxy metadata |
| `tests/test_capcut_compact_clear.py` | Mapping duration/date và entry point audio |
| `tests/test_capcut_ui.py` | Entry point audio theo hàng |
| `tests/test_capcut_import.py` | Kiểm số cột hiển thị qua proxy |
| `scripts/check_capcut_workspace.py` | Capture cận bảng, đo action column, snapshot trạng thái Dừng offline |
| `docs/capcut-row-actions.md` | Báo cáo này |

[Hash/AST đối chiếu](../artifacts/capcut-row-actions/protected-verification.json): **16 file giữ nguyên hash**, gồm backend/template, sidebar/MainWindow, workspace/header/splitter, theme, media model/cache, tên part/delegate, player TTS, version/pyproject. **13 hàm Page giữ nguyên AST**, gồm export snapshot/worker, scan/generation completion, Clear All, sort/persistence, cancel/shutdown. `CapcutPlayer` không bị viết lại. [Diff UI](../artifacts/capcut-row-actions/ui-changes.diff); snapshot UI/tests đầu đợt lưu cùng artifact.

## H. Trạng thái

**READY FOR USER ACCEPTANCE — source v1.1.0, chưa phát hành.** Giới hạn audio thiết bị và desktop/DPI vật lý ghi ở E/F. Giữ v1.1.0; không build, tăng version, commit/push/publish, sửa driver hoặc media người dùng. Không tự phát hành sau nghiệm thu source.
