# CapCut — sửa editor tên project và viền panel xuất

19/10/2026 · Source v1.1.0 · Chưa phát hành.

## A. Nguyên nhân đã tái hiện

Preview dùng hàng 23 logical px; ô editor thực tế cao 22 px sau grid line. Delegate mặc định tạo QLineEdit và kế thừa stylesheet nhập liệu toàn ứng dụng: border 1 px, padding dọc 6 px và ngang 9 px. Đo bằng `QStyle.SE_LineEditContents` cho vùng chữ **362×8 px**, trong khi font Segoe UI cao **17 px**; editor yêu cầu sizeHint cao 33 px. Chữ/caret bị cắt trong vùng nội dung, không phải hai bản dịch hoặc tên bị nhân đôi trong model.

Ảnh trước sửa ghi lại ngay khi editor đang mở: [Light 100%](../artifacts/capcut-editor-border/before/light-100-editing-panel.png). Số đo: [trước](../artifacts/capcut-editor-border/before/editor-light-100.json).

Panel trước dùng chung selector `QFrame#card`; viền Light `#E7D8CE`, Dark `#554138` quá gần màu nền. Preview cũng dùng selector của bảng chi tiết media, chưa có phân biệt riêng cho vùng cấu hình xuất.

## B. Cách sửa

- `ProjectNameDelegate` chỉ áp dụng cho preview chia part, kế thừa cơ chế bỏ focus rectangle trắng của `RowDelegate`. Editor vẫn là QLineEdit chuẩn, dùng commit/close của Qt và các hàm lưu tên hiện có.
- Editor phủ đúng rect của cell, nền opaque theo theme, padding `0 3px`, text margins bằng 0, căn trái và giữa theo chiều dọc. Góc vuông trong cell giúp phủ kín vùng chữ DisplayRole phía dưới; không thêm lớp chữ hay custom paint cho nội dung nhập.
- Viền editor 1 px, đổi sang accent khi focus. Selection tiếp tục dùng palette accent của ứng dụng; không đổi xử lý bàn phím, validation, tên mặc định hay persistence.
- Vùng chữ sau sửa **374×20 px**, đủ font 17 px. Editor vẫn cao 22 px và hàng vẫn **23 px**, ở cả scale 1 và 1,5. Không tăng chiều cao bảng để che lỗi.

## C. Viền khung

| Thành phần | Light | Dark | Độ dày / góc |
|---|---|---|---|
| Panel `capcutExportPanel` | `#B59B8B` | `#806657` | 1 logical px / 15 px |
| Preview `capcutSplitPreview` | `#B59B8B` | `#806657` | 1 logical px / 4 px |
| Divider hàng | `#E7D8CE` | `#554138` | Grid line hiện có |
| Header | nền `#F7F1ED` | nền `#3A2D27` | Divider dưới cùng màu viền preview |
| Editor focus | `#9B552C` | `#D88A4E` | 1 logical px / góc vuông trong cell |

Giữ nguyên margin panel `(10,7,10,7)`, spacing 4 và bố cục các ô/nút ở cả ba mode. Panel vẫn cố định dưới danh sách nhóm. Chỉ preview chia part xuất hiện/ẩn theo mode hiện có. Scale 150% dùng 1 logical px tương ứng 1,5 physical px, do Qt raster hóa.

## D. Screenshot

Các ảnh dùng dữ liệu ảnh/WAV tổng hợp, DB riêng, font Segoe UI Windows, Qt offscreen/software. Ảnh editor được chụp khi có focus và caret vị trí 12; tắt nhấp nháy caret riêng trong script capture để bằng chứng không phụ thuộc thời điểm chụp.

| Theme / scale | Toàn trang, đang nhập | Editor + toàn panel | Selection | Cửa sổ hẹp | Đang xuất/disabled |
|---|---|---|---|---|---|
| Light 100% | [Ảnh](../artifacts/capcut-editor-border/after/light-100-editing-full.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-100-editing-panel.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-100-editing-selection.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-100-settings-narrow.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-100-settings-disabled.png) |
| Dark 100% | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-editing-full.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-editing-panel.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-editing-selection.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-settings-narrow.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-settings-disabled.png) |
| Light 150% | [Ảnh](../artifacts/capcut-editor-border/after/light-150-editing-full.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-150-editing-panel.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-150-editing-selection.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-150-settings-narrow.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-150-settings-disabled.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-editing-full.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-editing-panel.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-editing-selection.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-settings-narrow.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-settings-disabled.png) |

| Theme / scale | Từng nhóm riêng | Gộp một project | Chia nhiều project |
|---|---|---|---|
| Light 100% | [Ảnh](../artifacts/capcut-editor-border/after/light-100-settings-0.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-100-settings-1.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-100-settings-2.png) |
| Dark 100% | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-settings-0.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-settings-1.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-100-settings-2.png) |
| Light 150% | [Ảnh](../artifacts/capcut-editor-border/after/light-150-settings-0.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-150-settings-1.png) | [Ảnh](../artifacts/capcut-editor-border/after/light-150-settings-2.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-settings-0.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-settings-1.png) | [Ảnh](../artifacts/capcut-editor-border/after/dark-150-settings-2.png) |

## E. Kiểm thử

- Focused editor + tên/header, scale 100%: **51 PASS**, 54,88 giây. [JUnit](../artifacts/capcut-editor-border/focused-100.xml).
- Regression toàn bộ CapCut, scale 100%: **165 PASS**, 112,31 giây. [JUnit](../artifacts/capcut-editor-border/regression-100.xml).
- GUI scale 150%: **107 PASS**, 104,15 giây. [JUnit](../artifacts/capcut-editor-border/gui-150.xml). Các lượt có overlap; không cộng lại thành số test duy nhất. Không có FAIL trong ba lượt cuối.

Các case mới kiểm event Qt thật: nhấp đúp mở đúng một editor, rect vừa cell, content đủ font, hàng không tăng; tên ngắn/dài/Việt/Unicode; Ctrl+A, paste/copy, gõ liên tục, Backspace/Delete, caret, Enter/Esc và chuyển hàng. Kiểm ba mode đổi lặp lại, 2/10 part, cửa sổ 950/1400 logical px, Light/Dark, border pixel thật, các control nằm trong panel, disabled/busy và đổi theme khi đang sửa.

Regression hiện có kiểm tên không hợp lệ/trùng, menu tên mặc định, đóng/mở lại DB riêng, tên thư mục và metadata khi xuất fixture; planner/thứ tự/cover/timeline/direct paths, nguồn không đổi, không ghi đè, hủy/lỗi giữa part và ba mode xuất. Không dùng API, inference hoặc media thật của người dùng.

## F. Source và phạm vi

| File | Thay đổi trong đợt này |
|---|---|
| `transcomic/ui/capcut_plan.py` | Thêm delegate editor riêng; model giữ nguyên |
| `transcomic/ui/capcut_cards.py` | Cài delegate và objectName riêng cho panel/preview |
| `transcomic/ui/theme.py` | QSS có scope cho ba widget trên |
| `tests/test_capcut_editor_border.py` | Regression nhập liệu, rect/content và panel |
| `scripts/check_capcut_source.py` | Nhánh capture editor đang nhập, selection và panel từng mode; chỉ bật qua biến môi trường |
| `docs/capcut-editor-border.md` | Báo cáo này |

[Diff UI so với snapshot đầu đợt](../artifacts/capcut-editor-border/ui-changes.diff). [Hash đối chiếu](../artifacts/capcut-editor-border/protected-verification.json): 11 file không đổi, gồm toàn bộ backend CapCut, template MAU, page/worker, bảng media chung, version và pyproject. AST của `SplitPlanModel` cũng khớp bản trước sửa. Những thay đổi có sẵn của nhiệm vụ trước được giữ nguyên.

## G. Trạng thái

**READY FOR USER ACCEPTANCE — source v1.1.0, chưa phát hành.**

Chưa kiểm kéo cửa sổ giữa hai màn hình khác DPI hoặc tương tác IME trực tiếp trên desktop; Unicode được kiểm qua clipboard Qt. Không mở CapCut thật để nghiệm thu bìa, và không thay cơ chế bìa. Không build, tăng version, commit, push, publish, Sandbox hoặc GPU/CUDA.
