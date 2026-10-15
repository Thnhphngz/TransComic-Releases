# Khôi phục toolbar một hàng — source 1.0.2

## Bố cục chuẩn và phạm vi

Đã đối chiếu `git show aed0d45:transcomic/ui/workspace_v2.py`, tại `setup_v2` và `adapt_v2_toolbar`, trước hai tính năng cảnh báo chưa commit. Bản Git đặt năm nút trực tiếp trong `file_actions`. Lấy cấu trúc đó làm chuẩn, giữ các sửa lỗi và tính năng mới đang có. Bổ sung ràng buộc không wrap ngay cả dưới ngưỡng 460 của bố cục cũ, theo yêu cầu mới.

Không chạy release, đổi version, commit, API thật, truy cập DB người dùng hoặc sửa logic dịch/mapping/export validation. Các sửa backend chưa commit từ đợt trước được giữ nguyên.

## Widget/layout đã sửa

- `workspace_v2.setup_v2`: bỏ wrapper VBox `export_folder_group`; đưa `folder_button` về `file_actions`, ngay sau `export_many_button`. Cả năm nút luôn ở row 0, đúng thứ tự nhập tài liệu → nhập thư mục → xuất tài liệu → xuất hàng loạt → mở thư mục xuất. Cột phụ mở panel vẫn dùng cơ chế ẩn/hiện cũ.
- Đặt `validation_badges` vào bên phải hàng tiêu đề đang có, dùng QHBoxLayout với margin 0, spacing 4; hai badge cùng hàng. Không thêm hàng header hay overlay.
- Năm nút dùng chung chiều cao bằng size hint lớn nhất trong nhóm để mép trên/dưới trùng nhau; giữ màu, vai trò, signal và phong cách Glass. Các cột chia đều không gian. Tên đầy đủ giữ nguyên, chỉ elide phần vẽ khi hẹp; tooltip giữ tên đầy đủ.
- `adapt_v2_toolbar`: bỏ di chuyển các nút sang hàng thứ hai, giới hạn chiều rộng nhóm badge theo vùng dịch hiện tại, kể cả resize trong cùng breakpoint. Những điều chỉnh responsive khác giữ nguyên.
- `glass.CompactStatusButton`: badge cao 24 logical pixel, vẽ elide khi hẹp, tooltip và accessible name giữ đầy đủ trạng thái. Màu và hover kế thừa GlassButton. Không thay đổi dữ liệu hay điều kiện tính cảnh báo.
- `LineCheck`, `PeriodWarning`: chỉ đổi lớp nút nền sang CompactStatusButton. Logic quét, cập nhật, điều hướng và popup giữ nguyên. PeriodWarning tiếp tục tự ẩn khi không có dấu chấm; LineCheck mở rộng trong vùng bên phải mà không đẩy hàng nút.

## Regression và bằng chứng

`tests/test_toolbar_layout.py` kiểm tra Light/Dark, resize qua 1500/1100/900/1250/950 logical pixel, panel tài liệu mở/đóng; năm nút có cùng y/chiều cao, đúng thứ tự, nằm trong vùng hiển thị; hai badge cùng y phía trên, căn phải; rect không chồng nhau và `childAt` tại tâm khớp widget thực sự nhận click.

Test cũng so sánh header khi nhóm badge hiện/ẩn: chênh lệch cho phép tối đa 4 logical pixel, không có thêm hàng. Kiểm tra hover, click thực tế mở đúng từng popup, Esc đóng, dữ liệu không đổi, cảnh báo dấu chấm biến mất khi sửa hết mà không dịch chuyển năm nút.

`test_line_check_ui` cập nhật assertion cũ từ ba tầng sang hai badge cùng hàng. `test_final_workflow` kiểm tra folder_button nằm trực tiếp trong grid. Regression popup dấu chấm, kiểm tra dòng, năm sửa UI, GUI và workspace được chạy lại bằng fixture riêng, không dùng dữ liệu thật.

Kết quả cuối được ghi tại `artifacts/toolbar-layout/`; ảnh `before100/`, `before150/` chụp trước sửa, `dpi100/`, `dpi125/`, `dpi150/` chụp sau sửa bằng Windows native. Mỗi thư mục có `light.png`, `dark.png` toàn bộ cửa sổ và `display.json` xác nhận DPR. Các ảnh dùng dữ liệu minh họa tổng hợp.

| Windows native | PASS | FAIL | SKIP | DPR thực tế |
|---|---:|---:|---:|---:|
| Light/Dark, DPI 100% | 54 | 0 | 0 | 1,0 |
| Light/Dark, DPI 125% | 54 | 0 | 0 | 1,25 |
| Light/Dark, DPI 150% | 54 | 0 | 0 | 1,5 |

54 case gồm 6 case toolbar mới và 48 case kiểm tra dòng/popup dấu chấm/năm sửa UI. Số lượt chạy lặp ở ba DPI không phải số test độc lập. Không chạy lại full suite trong đợt chỉ sửa bố cục này; kết quả full 1.035 PASS trước đó thuộc đợt triển khai kiểm tra dòng.

Regression liên quan cuối: `test_toolbar_layout.py`, `test_gui.py`, `test_workspace_v2.py`, `test_final_workflow.py` đạt **65 PASS, 0 FAIL, 0 SKIP** trong 35,99 giây, dùng offscreen và mock HTTP. Bộ này bao gồm kiểm tra resize tự động qua event của cửa sổ, thao tác GUI, workspace và export cũ. XML/log tại `related.xml`/`related.log`; `acceptance.json` tổng hợp kết quả. `git diff --check` đạt. Phiên bản/HEAD và các script release không đổi.

### Ảnh toàn bộ cửa sổ để đối chiếu

| DPI | Trước sửa | Sau sửa |
|---|---|---|
| 100% Light | [Trước](../artifacts/toolbar-layout/before100/light.png) | [Sau](../artifacts/toolbar-layout/dpi100/light.png) |
| 100% Dark | [Trước](../artifacts/toolbar-layout/before100/dark.png) | [Sau](../artifacts/toolbar-layout/dpi100/dark.png) |
| 150% Light | [Trước](../artifacts/toolbar-layout/before150/light.png) | [Sau](../artifacts/toolbar-layout/dpi150/light.png) |
| 150% Dark | [Trước](../artifacts/toolbar-layout/before150/dark.png) | [Sau](../artifacts/toolbar-layout/dpi150/dark.png) |

Ảnh sau cho thấy khu vực thiết lập dịch và bảng nội dung bắt đầu cao hơn, nhờ bỏ hai tầng badge bên trong hàng chức năng. Không thêm hàng trống, spacer dọc hoặc vùng click overlay. Tại cửa sổ hẹp, elide chỉ ảnh hưởng phần vẽ chữ; popup và tên đầy đủ trong tooltip vẫn giữ nguyên.
