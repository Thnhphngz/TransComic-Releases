# Automation — compact panel, pinned actions và responsive table

> Lượt refinement tiếp theo đã khôi phục CapCut thủ công, tinh giản Sidebar và hoàn thiện empty state/header/drop folder: [báo cáo mới nhất](ui-restore-capcut.md).

## A. Layout

**READY FOR USER ACCEPTANCE** — source tiếp tục trên v1.2.0, HEAD `322cf50`. Đợt này chỉ sửa UI, test và hướng dẫn; giữ các thay đổi Automation đã có.

- `AutomationPage.columns`: stretch **70:30**, khe 14 logical px, không có `QSplitter`. Minimum trái/phải vẫn 280/300; cửa sổ hẹp ưu tiên minimum control, không tăng minimum của cửa sổ chính.
- Panel phải không lấy thêm chiều rộng từ sizeHint. Cấu hình dùng 6/8/9 hàng tùy bề rộng; cuộn dọc riêng khi thiếu chiều cao. Desktop 1672×941 hiển thị đủ preview ba project.
- Bảng gồm ba `GroupTable` **nằm cạnh nhau**, không có overlay: checkbox trái, nội dung giữa, thao tác phải. Dùng chung model, selection model, chiều cao hàng, header và pixel offset dọc. Cột thao tác có cả gutter scrollbar nên nút **×** không bị khuất khi có hàng trăm nhóm hoặc Sidebar mở rộng.
- Cột nội dung được phân bổ lại theo viewport; đường dẫn/số lượng co trước, tooltip giữ nội dung đầy đủ. Header có nhãn gọn ở khung hẹp. Khi không đủ không gian, chỉ phần giữa cuộn ngang; checkbox và Ảnh / Dịch / × đứng yên.

## B. Đủ 10 mục điều chỉnh

| Mục | Kết quả |
| --- | --- |
| 1. Panel phải nhỏ hơn | Đổi 62:38 thành 70:30; bố trí lại cấu hình theo chiều rộng thật. |
| 2. Project / sửa tên luôn hiện | Preview cao cố định 120 px, cuộn riêng. Separate: mỗi nhóm một project; merged: một project; split: các part. Sửa tên vẫn đi qua `part_names` và khóa repository hiện có. Chuyển mode không tạo project. |
| 3. Trạng thái/thời gian | Cùng hàng Tiến độ tổng thể, bên phải; màu theo state. Nhãn dài được xuống dòng trong vùng của nó. Đã kiểm tra sáu trạng thái được yêu cầu. |
| 4. Thống kê nhóm | Đưa dưới badge ở header trái; không lặp dưới card tiến độ. Vòng tròn vẫn hiển thị X/Y nhóm. |
| 5. Toolbar | **Thêm tài liệu → Kiểm tra lại → Bắt đầu/Tiếp tục → Dừng an toàn**; bốn cột hoặc hai cột, cùng cao 36 px. |
| 6. Không mất thao tác | Hai view cố định hai mép; hit testing lấy stable ID của model. Ba nút vẫn nhận click sau scroll/filter, cả Sidebar mở/thu gọn. Tab đi qua ba vùng rồi ra cấu hình, không mắc vòng focus. |
| 7. Cuộn ngang | Đổi mặc định ScrollPerItem thành **ScrollPerPixel**, singleStep 24 px. Nhận pixel delta ngang và Shift+wheel; không animation/quán tính. Không resize header khi cuộn. Chỉ hiện track ngang khi cần, gutter giữa ba view đồng bộ. |
| 8. Số part giữ slot | Không ẩn cell; disabled ngoài split hoặc khi cấu hình đang khóa, vẫn đọc được. Đổi mode không đổi geometry các field/preview/card. |
| 9. Compact progress cards | Icon + tên, số liệu nổi bật, thanh 5 px; màu xanh lá/xanh dương/tím. Ring 88×94 giữ tỷ lệ hình tròn. Panel dưới 400 px xếp ba stage gọn theo chiều dọc bên trái ring. |
| 10. Visual consistency | Giữ Liquid Glass/theme chung, card gradient nhẹ/viền mảnh; giảm spacing cấu hình. Đường dẫn CapCut elide giữa khi không focus, tooltip và text chỉnh sửa vẫn đầy đủ. |

### Widget/source đã sửa

- [automation_page.py](../transcomic/ui/automation_page.py): header, toolbar, responsive grid, `GroupTable`/`GroupModel`, pinned views, scroll và preview visibility.
- [automation_widgets.py](../transcomic/ui/automation_widgets.py): ring nhỏ hơn và `ElidingPathEdit` chỉ thay cách vẽ đường dẫn khi không focus.
- [test_automation_ui.py](../tests/test_automation_ui.py): cập nhật expectation cho yêu cầu mới, chuyển hit testing sang view cố định đúng.
- [test_automation_refinement_ui.py](../tests/test_automation_refinement_ui.py): regression mới cho các tình huống bên dưới.

Không sửa controller, validation, repository, scheduler, retry, engine Kokoro hoặc exporter trong đợt refinement. Tám file worker vẫn byte-identical với snapshot v1.2.0. Không build, version bump, commit, push hay publish.

## C. Kiểm thử

| Lượt kiểm tra | PASS | FAIL | Bằng chứng |
| --- | ---: | ---: | --- |
| GUI ở DPI 100% | 45 | 0 | [gui-100.log](../artifacts/automation-refinement/gui-100.log) |
| GUI ở DPI 150% | 35 | 0 | [gui-150.log](../artifacts/automation-refinement/gui-150.log) |
| Chốt bảng/header/ảnh DPI 100% | 18 | 0 | [final-100.log](../artifacts/automation-refinement/final-100.log) |
| Chốt bảng/header/ảnh DPI 150% | 18 | 0 | [final-150.log](../artifacts/automation-refinement/final-150.log) |
| Tab/Backtab ra khỏi bảng | 1 | 0 | [keyboard-final.log](../artifacts/automation-refinement/keyboard-final.log) |
| Function-focused regression | 13 | 0 | [function-focused.log](../artifacts/automation-refinement/function-focused.log) |

Các lượt GUI có giao nhau, **không cộng thành số test duy nhất**: tổng cộng 47 GUI case khác nhau và 13 function case. Hai bài thực thi nút mới được kiểm tra bổ sung sau lượt 45 case.

- Light/Dark, DPR 1.0/1.5, Sidebar rộng 200 hoặc gọn 72; kích thước 900×580, 1200×780, 1672×941 và regression resize 1920×1080.
- 200 hàng mô phỏng trong model: căn Y ba view, cuộn dọc/ngang, click đủ ba nút, checkbox, filter/reset stable ID, bàn phím; không tạo 200 bộ media.
- Test nút thực: ghép folder qua dialog mock, mở đúng document Dịch, xóa metadata đúng nhóm sau filter. File/folder nguồn vẫn tồn tại, không có request hoặc inference phát sinh.
- Project editor đủ ba mode, đổi tên và khóa khi active; geometry ổn định, không tạo project chỉ vì xem/chuyển mode.
- Regression chức năng: preflight chặn dữ liệu lỗi; ba mode chạy qua mock HTTP/PCM và exporter MAU thật trong thư mục tạm; mapping/source không đổi, WAV và direct media paths hợp lệ; Safe Stop, request đang bay, retry giới hạn và mở lại checkpoint.
- Lượt đầu test mới tìm ra gutter thiếu bề rộng; lượt tiếp theo tìm ra spinbox bị ép ở panel 300 px. Đã sửa và các lượt chốt đều 0 FAIL.

Giới hạn: DPI được kiểm tra bằng Qt scaling, ảnh Qt offscreen. Đã mô phỏng delta trackpad và Shift+wheel, **chưa thử trackpad phần cứng** hoặc thay DPI desktop Windows trực tiếp. Không chạy GPU, Windows Sandbox hay dịch API thật; không kiểm thử lại ứng dụng CapCut thật trong lượt UI này.

## D. So sánh mockup và ảnh trước/sau

Đã mở đối chiếu [mockup gốc](../artifacts/automation-responsive/reference-candidate-44.png), ảnh trước, pass 1, pass 2 và ảnh chốt. Giữ palette nâu/cam, các thẻ stage màu riêng, vòng hoàn tất, badge và nút glass. Khác mockup có chủ đích: panel 30%, không có log/checklist cũ, giữ bộ chọn workset và các field nguồn/đích hiện có. Không sao chép các control của mockup mà engine hiện tại không dùng.

Ảnh desktop đều **1672×941 logical px**, Sidebar mở, cùng sáu nhóm đã hoàn tất 12/12 WAV, xuất ba part. Đường dẫn/thời gian của fixture có thể khác giữa lượt chạy.

| Ảnh | Dark | Light |
| --- | --- | --- |
| Trước, 100% | [Trước Dark](../artifacts/automation-refinement/before/polish-dark.png) | [Trước Light](../artifacts/automation-refinement/before/polish-light.png) |
| Sau, 100% | [Dark 100%](../artifacts/automation-refinement/gui-100/polish-dark.png) | [Light 100%](../artifacts/automation-refinement/gui-100/polish-light.png) |
| Sau, 150% | [Dark 150%](../artifacts/automation-refinement/gui-150/polish-dark.png) | [Light 150%](../artifacts/automation-refinement/gui-150/polish-light.png) |

Khung hẹp: [100%](../artifacts/automation-refinement/gui-100/responsive-narrow.png), [150%](../artifacts/automation-refinement/gui-150/responsive-narrow.png). Panel phải cuộn riêng, ring giữ lại, toolbar hai hàng, cột thao tác vẫn nhìn thấy.

Snapshot hai file UI trước sửa và [patch refinement](../artifacts/automation-refinement/changes.patch) được giữ trong artifacts để đối chiếu, không tạo Git commit.

## E. Trạng thái

**READY FOR USER ACCEPTANCE**. Không còn lỗi test về nút × bị khuất hoặc control bị ép vượt cell. Bước tiếp theo là người dùng xem giao diện trên máy và trackpad thực tế.
