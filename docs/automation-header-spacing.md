# Automation — thu gọn khoảng cách đầu trang

## Mới nhất — thay checkbox bằng STT gọn

- Bỏ checkbox và trạng thái checked ở model/delegate. Cột đầu là STT căn giữa, cố định bên trái; chiều rộng tính đúng theo nhãn STT hoặc số lớn nhất + 12 px padding, không stretch. Đã kiểm tra số 1 đến 10.000, cột chỉ nở khi thêm chữ số cần thiết.
- STT theo thứ tự toàn bộ nhóm hiện tại; lọc giữ số gốc, di chuyển/xóa nhóm cập nhật số liên tục. Bỏ tiền tố số trùng trước tên tài liệu.
- Click STT chỉ chọn/focus hàng; vẫn drop folder và mở Dịch bằng stable ID. Start/Resume không còn lấy một tập checked ẩn; engine/checkpoint và API backend giữ nguyên.
- GUI: **42 PASS ở 100%, 27 PASS ở 150%, 11 PASS liên quan Start/controls/drop**. Các lượt có giao nhau; không cộng thành số case riêng.
- Ảnh: [Dark 100%](../artifacts/automation-row-numbers/gui-100/automation-dark.png), [Light 100%](../artifacts/automation-row-numbers/gui-100/automation-light.png), [Dark 150%](../artifacts/automation-row-numbers/gui-150/automation-dark.png), [Light 150%](../artifacts/automation-row-numbers/gui-150/automation-light.png). Log và patch trong `artifacts/automation-row-numbers`.

Các phần tiếp theo là lịch sử các lượt trước.

## Mới nhất — giảm thêm 3 px và sửa bo góc bảng

- Khoảng cách giữa các hàng/margin trên **5 → 2 px**; header và khoảng cách giữa hai hàng toolbar **3 → 0 px**. Nút vẫn cao 36 px, khoảng cách ngang 6 px. Bảng cao **742 → 760 px**, thêm 18 logical px tại 1672×941.
- Thay ba khung bo riêng bằng `RoundedTableFrame`: một viền ngoài bán kính 12 px, vùng nội dung chung được clip theo đường bo. Header, nền viewport và scrollbar đều nằm trong cùng biên; các chỗ nối nội bộ để thẳng. Không còn góc vuông của header che đường bo hoặc góc bo riêng giữa các cột cố định.
- Clip được tính lại khi resize, không chặn vùng click của hàng/checkbox/actions. Không đổi model, scheduler, validation, database hoặc callback các nút.
- GUI: **40 case PASS ở mỗi mức 100%/150%** (100% gồm lượt 31 + 9; 150% một lượt 40). Có kiểm tra pixel bốn góc và mối nối header, bảng rỗng/có dữ liệu, resize, Sidebar, scroll, hit regions, bàn phím, empty-state drop và folder drop cả bảy ô.
- Ảnh bảng rỗng đúng tình huống người dùng báo: [Dark 100%](../artifacts/automation-rounded-table/gui-100/automation-empty-dark.png), [Light 100%](../artifacts/automation-rounded-table/gui-100/automation-empty-light.png), [Dark 150%](../artifacts/automation-rounded-table/gui-150/automation-empty-dark.png), [Light 150%](../artifacts/automation-rounded-table/gui-150/automation-empty-light.png).
- Ảnh có dữ liệu và log nằm trong `artifacts/automation-rounded-table`. Chụp Qt offscreen/scaling; không build, đổi version, commit/push hoặc release.

Các phần bên dưới ghi lại các lượt điều chỉnh trước.

## Điều chỉnh tiếp theo yêu cầu giảm thêm 2–3 px

- Khoảng cách các hàng và margin trên: **8 → 5 px** (giảm thêm 3 px).
- Khoảng cách trong header và giữa hai hàng toolbar: **5 → 3 px** (giảm thêm 2 px để không quá sát).
- Bốn nút vẫn cao 36 px, khoảng cách ngang 6 px. Bảng cao **725 → 742 px**, tăng thêm 17 px tại cửa sổ 1672×941.
- GUI tests: **14/14 PASS ở 100%, 14/14 PASS ở 150%**; kiểm tra Dark/Light, Sidebar mở/thu gọn, cửa sổ rộng/hẹp và nhãn nút không bị cắt/chồng.
- Ảnh mới: [Dark 100%](../artifacts/automation-spacing-tight/gui-100/automation-dark.png), [Light 100%](../artifacts/automation-spacing-tight/gui-100/automation-light.png), [Dark 150%](../artifacts/automation-spacing-tight/gui-150/automation-dark.png), [Light 150%](../artifacts/automation-spacing-tight/gui-150/automation-light.png).

Phần bên dưới ghi nhận lượt điều chỉnh trước.

Đã chỉnh trực tiếp trên source hiện tại, chỉ thay bốn khai báo layout trong `transcomic/ui/automation_page.py`.

| Khoảng cách | Trước | Sau | Mức giảm |
| --- | ---: | ---: | ---: |
| Giữa các hàng ở cột trái | 10 px | 8 px | 20% |
| Giữa các hàng của header | 6 px | 5 px | 16,7% |
| Giữa hai hàng toolbar khi cửa sổ hẹp | 6 px | 5 px | 16,7% |
| Margin trên của trang | 10 px | 8 px | 20% |

Giữ khoảng cách ngang các nút 6 px, bốn nút cao 36 px và phân bổ chiều rộng đều. Không có stretch/spacer dọc trước bảng; bảng vẫn nhận toàn bộ chiều cao còn lại. Hai cột 70:30, theme, control và callback giữ nguyên.

Ở cùng cửa sổ **1672×941 logical px**, Sidebar expanded, sáu nhóm fixture chưa chạy:

- Bảng cao **714 → 725 px**, tăng 11 px; mép trên bảng trong trang đi lên 11 px, gồm 9 px trong cột trái và 2 px margin ngoài.
- Hai theme và DPR 1.0/1.5 cho cùng geometry logical. Ảnh không dùng dữ liệu riêng hoặc gọi API.

## Kiểm thử

- DPI 100%: **14/14 PASS**, [log](../artifacts/automation-spacing/gui-100.log).
- DPI 150%: **21/21 PASS**, [log](../artifacts/automation-spacing/gui-150.log). Có giao nhau với lượt 100%; không cộng thành 35 case duy nhất.
- Kiểm tra 900×580, 1200×780, 1672×941; thêm regression resize 1920×1080 hiện có. Light/Dark, Sidebar mở/thu gọn, toolbar bốn hoặc hai cột, nhãn đầy đủ, nút đều cao/rộng, không chồng lấn, không spacer đầu trang, cột thao tác vẫn nhìn thấy.
- Chỉ chạy GUI tests. Không chạy engine, validation, export, API hoặc full regression. Không đổi SQLite/schema, phiên bản, build, commit/push hay release.

## Ảnh

| DPI | Dark | Light |
| --- | --- | --- |
| 100% | [Ảnh](../artifacts/automation-spacing/gui-100/automation-dark.png) | [Ảnh](../artifacts/automation-spacing/gui-100/automation-light.png) |
| 150% | [Ảnh](../artifacts/automation-spacing/gui-150/automation-dark.png) | [Ảnh](../artifacts/automation-spacing/gui-150/automation-light.png) |

[Trước sửa, Dark 100%](../artifacts/automation-spacing/before/automation-dark.png). Đã xem trực tiếp cả bốn ảnh sau sửa. DPI được kiểm tra bằng Qt scaling/offscreen, chưa đổi thiết lập DPI của desktop Windows thật.
