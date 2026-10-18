# CapCut — tinh chỉnh UI cuối và kiểm tra trước phát hành

19/10/2026 · Source **v1.1.0** · **Chưa build/phát hành**.

## A. UI đã thay đổi

Giữ sidebar chính, bố cục hai cột, danh sách nhóm/search/CRUD, thiết lập xuất và ba chế độ. Chỉ tinh chỉnh:

- STT theo số chữ số/font; không giãn theo bảng.
- Trạng thái gọn, chiều rộng cố định; tên ảnh/audio nhận khoảng trống dư.
- Bỏ khả năng hiển thị Ngày tạo: cột luôn ẩn, không còn nút bật cột. Metadata trong source model và chế độ sort `created` giữ nguyên.
- Toolbar media còn đúng **Phát/Dừng** và **Xem ảnh**.
- Pane nhóm giữ chiều rộng khi resize, vẫn kéo splitter được.
- Header nhóm ghép tên/thao tác/đường dẫn trên màn hình rộng; thống kê ngay bên dưới.
- Margin đầu trang 8 thay vì 12 logical px; spacing 4 thay vì 6.

## B. Kích thước cột trước/sau

Đo MainWindow có sidebar 200 logical px, 10 nhóm fixture, nhóm đang chọn 12 cặp, font Segoe UI Windows. Số đo giống nhau trong Light/Dark và scale 100%/150% ở tọa độ logical:

| Cửa sổ logical | STT trước → sau | Trạng thái trước → sau | Tên ảnh trước → sau | Audio trước → sau | Pane nhóm trước → sau |
|---|---:|---:|---:|---:|---:|
| 1280×720 | 78 → 33 | 182 → 100 | 140 → 204 | 140 → 203 | 285 → 285 |
| 1600×900 | 78 → 33 | 415 → 100 | 140 → 364 | 140 → 363 | 372 → 285 |
| 1920×1080 | 78 → 33 | 647 → 100 | 140 → 524 | 140 → 523 | 460 → 285 |

STT tính khi load snapshot nhóm: `max(fontWidth('9' × số chữ số lớn nhất) + 14, headerFontWidth('STT') + 12)`. Cần giữ đủ tiêu đề STT nên nhóm một chữ số không nhất thiết có cột nhỏ hơn nhóm hai chữ số. Test các giá trị 9, 99, 184, 999, 1.000, 10.000; đổi nhóm cập nhật lại width. Không resize-to-contents từng frame hoặc quét dữ liệu theo mỗi paint.

Cột Trạng thái trước dùng `stretchLastSection`, nhận gần hết chiều rộng dư. Nay cố định 100 logical px, hiển thị **Khớp / Thiếu ảnh / Thiếu voice / Lỗi file / Cần kiểm tra**; tooltip giữ nguyên nguyên nhân lỗi đầy đủ. Foreground xanh/đỏ theo palette; selection vẫn tuân thủ màu chọn của bảng. Không sửa matching/validation để rút ngắn nhãn.

Hai cột tên ảnh/audio dùng `QHeaderView.Stretch`; thumbnail, duration, STT và trạng thái không nhận phần tăng thêm. Ngày tạo vẫn tồn tại trong model phục vụ metadata/regression, nhưng người dùng không thể bật cột từ UI mới.

Pane nhóm dùng stretch factor 0, pane media 1. Mặc định khoảng 285 logical px, minimum 220; không khóa cứng. Kéo splitter vẫn hoạt động và chiều rộng do người dùng chọn giữ khi đổi nhóm/resize trong phiên. Không đổi sidebar chính hoặc persistence.

## C. Audio player

`GroupDetails.sync_audio` đọc **`QMediaPlayer.playbackState()`** của shared player. Chỉ khi đúng inspector sở hữu player và trạng thái **PlayingState** mới hiện biểu tượng vuông + Dừng. Trạng thái dừng/chưa phát/kết thúc/lỗi → biểu tượng tam giác + Phát; không dùng bộ đếm hoặc boolean phỏng đoán trạng thái.

Nút đăng ký `playbackStateChanged`, signal lỗi và signal đóng của player. Chuyển hàng/nhóm/trang, clear và shutdown vẫn dùng stop hiện có; một player duy nhất. Phát bị vô hiệu khi không chọn audio, thiếu audio, audio có lỗi hoặc file đã thay đổi/mất sau scan. Nhấn Dừng gọi stop chung; nhấn Phát gọi luồng kiểm file/player hiện có. Audio loading chưa thực sự phát thì chưa ghi Dừng.

Biểu tượng tam giác/vuông được vẽ bằng QPainter theo DPR, tránh ký tự ▶ thành ô vuông ở một số backend/font. Text là `Phát`/`Dừng`; accessible name tương ứng `▶ Phát`/`■ Dừng`. Toolbar không có nút Dừng riêng/Ngày tạo. Shared player seek/volume hiện có vẫn được tái sử dụng; không sửa player TTS chung.

Test điều khiển backend mô phỏng có signal/state/source: phát, dừng, phát lại, EndOfMedia, lỗi decoder, chuyển hàng, chuyển nhóm, đổi trang, đóng app, một player duy nhất. Test riêng thiếu/corrupt/mất file. Đây là kiểm tra kết nối UI với state machine, **không phải nghiệm thu âm thanh qua loa hoặc codec thiết bị thật**.

## D. Header nhóm

Màn hình rộng: tên và thao tác nằm trái; hai path căn phải ở phần còn lại của cùng hàng. Thống kê nhóm nằm ngay dưới. Pane hẹp thì path xuống một hàng riêng có kiểm soát, tên/thao tác tiếp tục dùng flow layout khi cần; không đè lên nút.

Hai path dùng `PathLabel` có elide giữa, tooltip đầy đủ, text selectable và menu **Sao chép đường dẫn đầy đủ**. Clipboard nhận đường dẫn gốc, không kèm tiền tố `Ảnh:`/`Voice:` của nhãn. Test click menu thật kiểm clipboard full path rồi khôi phục clipboard trước test; lượt focused cuối của case này PASS ở cả hai scale. Không sửa đường dẫn thật hoặc cách xuất direct paths.

Breakpoint dùng logical width của pane, không theo physical screen. Tên dài/path dài elide, nút quản lý giữ trong inspector kể cả sidebar chính mở. Ở pane ≥1.000 logical px, path nằm phải; bên dưới ngưỡng đó được đưa xuống hàng.

## E. Khoảng trống đầu trang

Nguyên nhân nội bộ trang: `QVBoxLayout` CapCut có top margin 12 và spacing 6; không phải margin MainWindow hoặc title bar. Giảm riêng trang xuống **8 / 4 logical px**. Tiêu đề và totals vẫn căn giữa trong ResponsivePair, totals không bị nhân đôi. Không sửa global margin, native Windows title bar hoặc sidebar.

Đo trước/sau: header y **12 → 8**, khoảng header–toolbar **6 → 4**. Phần header nhóm cũng được gộp và giảm spacing nội bộ trang, giúp viewport media:

| Cửa sổ logical | Viewport media trước → sau |
|---|---:|
| 1280×720, form thu gọn | 272 → 286 |
| 1600×900, form mở | 290 → 324 |
| 1920×1080, form mở | 470 → 504 |

[Số đo đầy đủ trước/sau](../artifacts/capcut-final-polish/layout-comparison.json). Ảnh trước được dựng lại từ snapshot UI đầu đợt bằng subprocess riêng; không chép đè hoặc tạm hoàn tác source đang làm việc. Dữ liệu media/DB đều tổng hợp và cô lập.

## F. Light/Dark, responsive và screenshot

Ảnh **toàn MainWindow có sidebar thật**, gồm trước/sau, ba kích thước, scale 100%/150%; sidebar thu gọn, editor tên part, validation và export locked cũng được chụp.

| Theme / scale | Trước 1600×900 | Sau 1280×720 | Sau 1600×900 | Sau 1920×1080 | Sidebar thu gọn |
|---|---|---|---|---|---|
| Dark 100% | [Ảnh](../artifacts/capcut-final-polish/baseline/dark-100-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-100-1280x720.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-100-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-100-1920x1080.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-100-sidebar-collapsed.png) |
| Light 100% | [Ảnh](../artifacts/capcut-final-polish/baseline/light-100-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-100-1280x720.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-100-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-100-1920x1080.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-100-sidebar-collapsed.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-final-polish/baseline/dark-150-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-150-1280x720.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-150-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-150-1920x1080.png) | [Ảnh](../artifacts/capcut-final-polish/after/dark-150-sidebar-collapsed.png) |
| Light 150% | [Ảnh](../artifacts/capcut-final-polish/baseline/light-150-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-150-1280x720.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-150-1600x900.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-150-1920x1080.png) | [Ảnh](../artifacts/capcut-final-polish/after/light-150-sidebar-collapsed.png) |

Ảnh trước ở 1280/1920 cũng lưu trong `baseline/` cùng quy tắc tên. Ở scale 150%, các kích thước trong bảng là **logical**: 1600×900 tạo ảnh 2400×1350 physical px. Không tuyên bố fit màn hình vật lý 1280×720 ở 150%; minimum size toàn ứng dụng giữ nguyên. Chưa kiểm kéo cửa sổ qua hai màn hình khác DPI.

## G. Regression và giới hạn

- Focused chức năng sau chỉnh UI: **43 PASS**, 32,73 giây.
- Toàn bộ CapCut ở 100%: **195 PASS**, 123,34 giây. Lượt này trước khi thay glyph bằng icon và thêm case mất file sau scan.
- Focused polish cuối ở 100%: **21 PASS**, 16,17 giây; 150%: **21 PASS**, 16,90 giây, kiểm icon/accessibility và mất file sau scan cùng các case mới.
- Toàn bộ CapCut 150% cuối: **196 PASS**, 119,56 giây sau sửa assert biểu tượng.

[Regression 100%](../artifacts/capcut-final-polish/regression-100.xml), [regression cuối 150%](../artifacts/capcut-final-polish/regression-final-150.xml), [focused cuối 100%](../artifacts/capcut-final-polish/polish-final-100.xml), [focused cuối 150%](../artifacts/capcut-final-polish/polish-final-150.xml). Các lượt cuối không có FAIL/ERROR/SKIP.

Giữ regression ba mode, chia nhóm/order/custom names/persistence, cover riêng từng part, template/timeline/keyframes/animation/gap 0/direct paths, không copy/sửa source, collision, atomic staging và hủy/lỗi giữa part. Không sửa các bài test backend exporter/planner/media. Các lượt overlap, không cộng lại thành số test duy nhất.

Lượt đầu test STT một chữ số chưa tính phần tiêu đề STT; đã sửa assert theo width cần cho cả header. Một lượt 150% có **1 FAIL / 195 PASS** do test còn mong đợi glyph trong `.text()` sau khi chuyển sang icon; đã chuyển kiểm sang accessible name. Không bỏ test hoặc thêm skip.

Test/capture CPU-only Qt offscreen/software, không API thật, inference, CUDA/GPU hoặc Sandbox. Không mở CapCut thật hoặc nghe audio thiết bị. Không chạy full regression toàn bộ app; phạm vi thay đổi giới hạn UI CapCut, player TTS dùng chung và backend được bảo vệ bằng hash/AST.

## H. Source thay đổi trong đợt này

| File | Thay đổi |
|---|---|
| `transcomic/ui/capcut_cards.py` | STT/columns/status display, bỏ toggle ngày tạo, một nút audio/icon và sync, top margin |
| `transcomic/ui/capcut_workspace.py` | Header path/tên/actions và pane nhóm không tự giãn |
| `transcomic/ui/capcut_page.py` | Nối signal player, đồng bộ nút sau stop; không sửa export/scan |
| `tests/test_capcut_final_polish.py` | 21 regression mới về columns/status/audio/path/header/splitter |
| `tests/test_capcut_single_page.py` | Kỳ vọng ngày tạo ẩn vĩnh viễn, vẫn giữ metadata/sort test |
| `tests/test_capcut_compact_clear.py` | Focus test dùng cột ảnh đang hiển thị |
| `tests/test_capcut_ui.py` | Bỏ truy cập nút Dừng riêng |
| `scripts/check_capcut_source.py` | Focus capture dùng cột ảnh thay ngày tạo |
| `scripts/check_capcut_workspace.py` | Output dir, số đo columns/header và chạy snapshot baseline trong subprocess |
| `docs/capcut-final-polish.md` | Báo cáo này |

[Diff UI so với snapshot đầu đợt](../artifacts/capcut-final-polish/ui-changes.diff). [Hash/AST](../artifacts/capcut-final-polish/protected-verification.json): **13 file không đổi**, gồm backend/template MAU, sidebar/MainWindow, player TTS, tên part, version/pyproject. **13 hàm Page giữ nguyên AST**, gồm scan/generation, export snapshot/worker, Clear All, sort, save options, cancel/shutdown. Chỉ hai hàm audio có thêm kết nối signal/sync UI. Không đổi logic Kira/Gemini/Kokoro/DOCX/TXT/history/updater hoặc source/media sản xuất.

## I. Kết luận

**READY FOR USER ACCEPTANCE — source v1.1.0, chưa phát hành.** Giữ v1.1.0; không build EXE/Installer, commit, push hoặc GitHub Release. Nghiệm thu source/UI không phải quyết định phát hành. Người dùng nghiệm thu audio thiết bị thật và tương tác desktop theo giới hạn tại F/G.
