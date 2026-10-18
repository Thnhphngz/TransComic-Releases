# CapCut — tên từng part, thống kê header và typography nhóm

19/10/2026 · Source **v1.1.0** · Chưa phát hành.

## A. Tên project tùy chỉnh

Nhấp đúp ô **Project** trong preview để sửa trực tiếp; Enter xác nhận, Esc hủy lượt sửa hiện tại. Các cột **Các nhóm/Số nhóm** chỉ đọc. Tooltip giữ toàn bộ tên, lỗi và các nhóm được phân bổ. Chuột phải chọn **Dùng tên mặc định** để khôi phục riêng part đó.

Tên tùy chỉnh lưu trong `capcut_workspace_v1.custom_names`, khóa là chuỗi số part (`"1"`, `"2"`…), không phải ID/tên nhóm. Settings cũ thiếu trường này dùng tên tự động. Đổi tên chung chỉ cập nhật part tự động. Khi 4→3→4, tên part 1–3 giữ nguyên và tên part 4 được khôi phục. Đổi thứ tự nhóm chỉ thay phân bổ, không chuyển tên part sang part khác.

Tên lỗi được giữ như bản nháp để người dùng sửa, có màu/cảnh báo và chặn xuất. Planner kiểm lại trước khi worker chạy. Không tự sanitize hoặc cắt ngắn tên tùy chỉnh:

- Không chấp nhận rỗng/chỉ khoảng trắng, ký tự cấm của Windows, control characters, tên reserved như CON/PRN/AUX/NUL/COM1/LPT9 kể cả extension.
- Giới hạn 80 ký tự theo quy tắc tên project hiện có; báo lỗi thay vì cắt ngầm. Không bắt đầu/kết thúc bằng khoảng trắng hoặc dấu chấm, vì sanitizer cũ sẽ làm thay đổi các tên đó.
- Tên Unicode/tiếng Việt hợp lệ được giữ nguyên. Tên trùng giữa các part bị chặn, gồm khác hoa/thường và Unicode tương đương sau NFC. Đây chỉ là khóa đối chiếu, không normalize tên thực tế khi ghi.
- Project đã có trên đĩa tiếp tục dùng hậu tố collision `_2`, `_3`… như engine cũ; không ghi đè.

Khi bắt đầu xuất, editor đang mở được commit, chốt bản sao tên từng part cùng mode/count/output và các scan bất biến. Preview bị khóa trong lúc worker chạy. Esc đã hủy không bị commit lại từ editor chờ Qt xóa. Tên được truyền tới cùng planner ở preview và exporter.

Đã xuất mẫu tổng hợp thành đúng các thư mục/metadata:

| Tên project | Nhóm | Số cặp |
|---|---|---:|
| `vote_1-6` | 1–3 | 6 |
| `vote_7-12` | 4–6 | 6 |
| `vote_13-16` | 7–8 | 4 |
| `vote_17-20` | 9–10 | 4 |

Xem [project mẫu](../artifacts/capcut-names-header/custom/demo-projects/split) và [ảnh tên tùy chỉnh](../artifacts/capcut-names-header/custom/light-100-collapsed.png). Tên là nhãn do người dùng đặt, không tự suy diễn khoảng chương từ tên đó.

## B. Header

`totals` đã thực sự chuyển vào `page_header`, là widget bên phải tiêu đề. Toolbar nằm dưới header; không còn bản thống kê riêng dưới các nút hoặc bản thống kê trùng. Cửa sổ rộng hiển thị cùng hàng; vùng header hẹp hơn 950 logical pixels chuyển thống kê xuống **dưới tiêu đề, trước toolbar**. Cho phép wrap để không mất số lỗi, tooltip giữ đầy đủ.

- **Ready:** tất cả nhóm có scan hợp lệ, điều kiện mode và tên part hợp lệ → xanh lá, bold 700, icon circle/check.
- **Review:** nhóm/media lỗi, scan thất bại hoặc tên part không hợp lệ → đỏ, bold 700, circle/alert. Số mục lỗi gồm lỗi nhóm/media, lỗi tên và lỗi scan tổng thể.
- **Empty:** chưa có nhóm → trung tính.
- **Scanning/pending:** clock/check indicator, màu trung tính, không ghi Sẵn sàng. Một nhóm ở mode chia cũng không ghi Sẵn sàng vì chưa đủ hai nhóm.

Icon vẽ bằng Qt painter nhỏ theo palette, không phụ thuộc font biểu tượng, không thêm animation timer/worker. Scan thất bại có tooltip lỗi, không giữ badge xanh từ lượt trước.

| Theme / scale | Trước | Sau | Sau, cửa sổ hẹp |
|---|---|---|---|
| Light 100% | [Ảnh](../artifacts/capcut-names-header/before/light-100-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/light-100-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/light-100-narrow.png) |
| Dark 100% | [Ảnh](../artifacts/capcut-names-header/before/dark-100-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/dark-100-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/dark-100-narrow.png) |
| Light 150% | [Ảnh](../artifacts/capcut-names-header/before/light-150-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/light-150-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/light-150-narrow.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-names-header/before/dark-150-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/dark-150-collapsed.png) | [Ảnh](../artifacts/capcut-names-header/after/dark-150-narrow.png) |

## C. Typography đo thực tế

Đối chiếu MainWindow 1400×1000, sidebar 200 logical pixels, 10 nhóm, 4 part, cùng theme/font/scale. Đọc font sau polish từ widget, không chỉ dựa vào chuỗi stylesheet.

| Chỉ số | Trước | Sau |
|---|---:|---:|
| Tên nhóm: pixel size (logical) | 13 | **15** |
| Tên nhóm: Qt font weight | 400, Normal | **600, DemiBold** |
| Chiều cao thẻ thu gọn | 114 | **114** |
| Chiều cao viewport danh sách | 522 | **545** |
| Nhóm nhìn thấy trọn vẹn | 4 | **4** |
| Nhóm có phần trong viewport | 5 | **5** |

Số nhóm trọn vẹn chưa tăng ở kích thước mẫu này; phần nhóm thứ 5 thấy được nhiều hơn nhờ thêm 23 logical pixels. Các số đo trên giống nhau trong cả bốn cấu hình Light/Dark × scale 100%/150%; xem [typography-comparison.json](../artifacts/capcut-names-header/typography-comparison.json).

Chỉ selector `QLabel#capcutGroupName` đổi typography. Số thứ tự và tên cùng một nhãn, màu ink theo theme, không đổi font toàn ứng dụng hoặc thêm padding. Tên dài vẫn elide/tooltip, accordion và toolbar thẻ giữ nguyên.

## D. Tests

- Regression toàn bộ CapCut: **147 PASS**, 89,66 giây; gồm ba mode, chia đều, cover đúng part, timeline/gap/direct paths, nguồn giữ nguyên, collision/cancel/staging, accordion và Clear All.
- GUI scale 150%: **89 PASS**, 81,90 giây, gồm Light/Dark, rộng/hẹp và các case tên/header mới.
- Focused cuối: **36 PASS**, 30,13 giây, kiểm toàn bộ file tính năng mới sau các case bổ sung. Các lượt có overlap, không cộng lại thành số test duy nhất.
- Các case bổ sung cuối đều PASS: stale model index sau đổi count; một nhóm ở mode chia không Ready; export commit editor đang mở; Esc không hồi sinh tên đã hủy; scan failure đếm một lỗi và đổi trạng thái.
- Enter/Esc và menu mặc định dùng event Qt thực; restart bằng đóng MainWindow và mở Store/window mới. Export fixture xác nhận cả tên thư mục và `draft_meta_info.json`, kể cả Unicode.
- Tên invalid không tạo output, duplicate chặn và đổi header sang review; sửa/default khôi phục Ready. Thay cấu hình sau snapshot không đổi tên của job đang chạy. Hủy part 2 giữ part 1 đã hoàn tất, xuất lại không ghi đè.

Bằng chứng: [regression](../artifacts/capcut-names-header/regression-100.xml), [GUI 150%](../artifacts/capcut-names-header/gui-150.xml), [focused cuối](../artifacts/capcut-names-header/focused-final-100.xml), [verification](../artifacts/capcut-names-header/verification.json).

Lượt focused đầu có hai assert header rộng FAIL do ngưỡng phụ thuộc font metrics fallback của offscreen. Đã dùng breakpoint logical rõ ràng, giữ wrap an toàn trong nhãn; các lượt cuối qua. Không bỏ kiểm tra hierarchy, tọa độ thực hay font sau polish.

## E. Source

| File | Thay đổi |
|---|---|
| `transcomic/capcut/planning.py` | Resolve custom names và validation; thuật toán `partition_groups` giữ nguyên AST |
| `transcomic/capcut/state.py` | Lưu/restore tên theo số part, reset và rollback khi save lỗi |
| `transcomic/capcut/exporter.py` | Chỉ nhận snapshot custom names và truyền vào planner ở mode split |
| `transcomic/ui/capcut_plan.py` | Cột Project editable, cảnh báo/tooltip, lưu tên, chặn stale edit và busy |
| `transcomic/ui/capcut_page.py` | Menu default, commit/lock/snapshot tên, trạng thái tổng scan/name/mode |
| `transcomic/ui/capcut_cards.py` | Hierarchy header thật, icon trạng thái, đánh dấu nhãn tên nhóm |
| `transcomic/ui/theme.py` | Selector riêng cho tổng quan và tên nhóm CapCut |
| `tests/test_capcut_names_header.py` | Regression tên, editor, persistence/export, header và typography |
| `scripts/check_capcut_source.py` | Capture trước/sau, số đo font/viewport và xuất mẫu custom names bằng dữ liệu tổng hợp |

Hash matcher, cover helper, template/provenance và pyproject khớp baseline. AST `write_project`, build timeline, validate, clone, safe_name, source assertion và `launch` worker đều khớp baseline. Không sửa metadata cover, duration, timeline hay các chức năng ngoài CapCut.

## F. Giới hạn

Test và capture dùng Qt software/offscreen trên Windows, scale 1/1,5; chưa kiểm kéo cửa sổ giữa hai màn hình khác DPI. Các project mẫu và media đều tổng hợp, DB cô lập. Không mở lại CapCut/GPU hoặc nghe loa thực tế. Bìa mới từ đợt trước vẫn cần nghiệm thu cách hiển thị trong CapCut thật; đợt này không thay cơ chế bìa.

Không build Installer/EXE, đổi version, commit/push/publish, Sandbox, CUDA/GPU stress, API hoặc inference. Các thay đổi source có sẵn của nhiệm vụ trước được giữ nguyên.

## G. Trạng thái

**READY FOR USER ACCEPTANCE — source v1.1.0, chưa phát hành.**
