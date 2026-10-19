# Khôi phục CapCut, tinh giản Sidebar và Automation table UX

## A. Tab CapCut

**READY FOR USER ACCEPTANCE** — giữ phiên bản **1.2.0**, tiếp tục source hiện tại.

- Bỏ phần khởi tạo/chèn `AutomationMirror` khỏi `CapcutPage`: không còn nhãn “Automation · cùng checkpoint”, dropdown workset, bảng Nhóm/Trạng thái/Voice/Project hoặc hai nút của projection.
- Bỏ refresh projection từ Automation. Không tự chuyển tab, nhập nhóm Automation vào manual workspace hoặc xuất project khi mở trang.
- `build_page` và các thành phần manual CapCut của HEAD v1.2.0 giữ nguyên: danh sách nhóm/trình xem hai cột, ảnh thumbnail, nút nghe/xem từng hàng, ba mode, sửa tên, split preview, output, export/cancel. Diff `capcut_page.py` so với HEAD chỉ còn hai guard ownership đã có để tránh chạy manual export đồng thời với Automation.
- Engine MAU, template, keyframe/animation, direct media paths, checkpoint và backend Automation không bị chỉnh sửa. Module projection cũ không còn được ứng dụng import/hiển thị; không xóa dữ liệu của nó hay checkpoint.
- Test mở CapCut khi có workset Automation xác minh manual groups vẫn độc lập, checkpoint không đổi và không phát sinh export. Regression nhấn xuất manual separate/merged/split vẫn chạy qua worker/exporter thật trên media tổng hợp trong thư mục tạm.

## B. Sidebar và nền/theme

- Bỏ ba mục **Dịch file SRT**, **Hàng đợi**, **Console**. Còn đúng **Dịch → Text to Speech → Xuất Project CapCut → Tự động hóa → Lịch sử → API → Cài đặt**.
- Giữ stack IDs cũ `[0,7,8,9,1,2,3]` cho các mục còn lại; không reindex trang, không xóa scheduler, queue page, SRT, Console/logging hoặc schema. Link cũ tới ID 4/5/6 vẫn resolve an toàn, không highlight nhầm một nút còn lại.
- Đã sửa mapping icon và highlight, mở/thu gọn, focus bàn phím. Không có nút trống hoặc spacer thay cho ba mục bỏ đi.
- Nguyên nhân mảng nâu ở Sidebar: `navigationScroll` viewport/body nhận `QWidget` background toàn ứng dụng, khác nền sidebar. Gán ID và đặt **chỉ ba container này** trong suốt, tắt autoFillBackground sau `setWidget`; gradient/viền nút không đổi.
- Nguyên nhân nền quanh output: wrapper của hàng đường dẫn + nút Chọn nhận background mặc định. Cho wrapper dùng `automationField`, vốn đã có rule trong suốt theo phạm vi Automation. Không phủ thêm lớp màu, không làm tất cả QWidget trong ứng dụng trong suốt.
- Pixel test chụp ảnh **đã compositing trong cửa sổ** xác minh phần trống Sidebar đúng màu theme; ảnh grab riêng của container trong suốt có alpha 0 là bình thường.

## C. Automation

### Empty state

- Bỏ dòng hướng dẫn cố định và chiều cao của nó. Notice chỉ hiện khi có thông báo thao tác/lỗi.
- Bảng rỗng: **Thêm hoặc kéo thả file văn bản vào đây**, canh giữa vùng bảng. Có nhóm nhưng filter không khớp: **Không tìm thấy tài liệu phù hợp**. Có hàng: ẩn empty state.
- Label có `WA_TransparentForMouseEvents`, không accept drops; file TXT/DOCX vẫn thả được xuyên qua vùng này. Không có layer chặn thao tác.

### Cột tự bố trí, không kéo tay

- Header của cả ba view dùng `QHeaderView.Fixed`, không movable, không cursor resize. Kéo mép header không thay đổi độ rộng.
- Chiều rộng nội dung tính từ viewport và font metrics; co đường dẫn trước, số lượng đủ mẫu ba chữ số dòng/ảnh, tiến độ đủ ba bar, trạng thái có badge, hành động có gutter scrollbar. Checkbox/actions vẫn cố định hai mép.
- Tính lại khi resize, Sidebar thay đổi, style/font/palette hoặc DPR thay đổi. Không hardcode một bộ độ rộng cho mọi màn hình; cuộn ngang theo pixel giữ nguyên.
- Giữ 70:30, không splitter, toolbar hiện tại, badge/thống kê header, ba stage/ring, Project luôn hiện và slot Số part disabled ngoài split.

### Folder drop

1. Drop vào bất kỳ ô nào của hàng: checkbox, tên, đường dẫn, số lượng, progress, status hoặc actions. Đích lấy stable group ID từ model đang filter; không đoán theo tên folder.
2. Highlight cam nhẹ đúng cả hàng ở ba view, xóa khi leave/drop. Không đưa hint vào layout trong lúc drag để hàng không di chuyển dưới con trỏ.
3. Kiểm tra directory tồn tại/đọc được và manifest theo **sort policy đã chọn** ngoài GUI. Folder rỗng, ảnh hỏng hoặc lỗi đọc bị từ chối **trước khi ghi mapping**.
4. Sau khi kiểm tra, xác minh ownership một lần nữa rồi gọi `pair_images` hiện có. Tự chạy validation đầu vào, cập nhật counts/badge và chặn Start nếu lệch; không gọi API hoặc tự Start.
5. Không cho Start trong lúc precheck folder còn chờ. Folder chốt sau cùng thắng nếu các lượt precheck hoàn tất ngược thứ tự. Nếu workset đã bắt đầu trong lúc chờ, không commit folder mới.
6. Folder vào vùng trống bị từ chối. Đã chặn fallback từ Automation về handler nhập thư mục tài liệu của cửa sổ chính; folder chứa TXT không bị quét nhầm vào tab Dịch.
7. Sau Stop, thay folder rồi Resume vẫn dùng invalidation/checkpoint hiện có. Test xác minh WAV hợp lệ không tạo lại, nguồn/voice/project cũ không bị xóa, project mới dùng version/path riêng.

## D. Kiểm thử và ảnh nghiệm thu

| Nhóm | PASS | FAIL | Log |
| --- | ---: | ---: | --- |
| Automation GUI/refinement hiện có | 47 | 0 | [initial.log](../artifacts/ui-restore/initial.log) |
| Manual CapCut, navigation, workspace, Liquid Glass | 92 | 0 | [manual-regression.log](../artifacts/ui-restore/manual-regression.log) |
| Restore/drop/empty/header — DPI 100% | 19 | 0 | [restore-final-100.log](../artifacts/ui-restore/restore-final-100.log) |
| Restore/drop/empty/header — DPI 150% | 19 | 0 | [restore-final-150.log](../artifacts/ui-restore/restore-final-150.log) |
| Drop lệch số lượng và hoàn tất ngược thứ tự | 2 | 0 | [drop-order.log](../artifacts/ui-restore/drop-order.log) |
| Chốt parent drop/drag geometry và nav keyboard | 4 | 0 | [final-drag-100.log](../artifacts/ui-restore/final-drag-100.log) |
| Chốt legacy drop/header DPI 100% | 5 | 0 | [final-layout-100.log](../artifacts/ui-restore/final-layout-100.log) |
| Chốt header/drop-order/ảnh DPI 150% | 7 | 0 | [final-150.log](../artifacts/ui-restore/final-150.log) |
| Ảnh 100%, đợi thumbnail tải xong | 2 | 0 | [photos-100.log](../artifacts/ui-restore/photos-100.log) |

Các lượt chốt chạy giao nhau; không cộng số lần chạy thành số test duy nhất. Tổng **160 case khác nhau** đã PASS, không chạy full offline suite vì không chạm engine.

Đã kiểm tra cửa sổ 900×580, 1200×780, 1672×941 và các regression resize hiện có; Sidebar mở/thu gọn; font lớn, DPR 1.0/1.5; kéo mép header; scroll/hit regions; drop cả bảy ô; folder rỗng/hỏng/vùng trống/active/stopped; filter stable ID; ảnh thay đổi rồi Resume; không phát sinh API hoặc tự Start. Test manual playback dùng mock player, không kiểm tra phần cứng âm thanh.

Đã mở trực tiếp ảnh sau để đối chiếu ba ảnh người dùng gửi: khối projection CapCut biến mất, Sidebar còn bảy mục không có nền hình chữ nhật lệch tông, hàng output hòa với card. Ảnh cùng cửa sổ 1672×941 logical px, Sidebar expanded, dữ liệu synthetic; không dùng truyện/media riêng của người dùng.

### DPI 100%

| Vùng | Dark | Light |
| --- | --- | --- |
| CapCut thủ công, ba nhóm/chia hai part | [Ảnh](../artifacts/ui-restore/gui-100/capcut-manual-dark.png) | [Ảnh](../artifacts/ui-restore/gui-100/capcut-manual-light.png) |
| Automation nhiều nhóm | [Ảnh](../artifacts/ui-restore/gui-100/automation-many-dark.png) | [Ảnh](../artifacts/ui-restore/gui-100/automation-many-light.png) |
| Empty state | [Ảnh](../artifacts/ui-restore/gui-100/automation-empty-dark.png) | [Ảnh](../artifacts/ui-restore/gui-100/automation-empty-light.png) |
| Drag-over hàng thứ ba | [Ảnh](../artifacts/ui-restore/gui-100/automation-drag-dark.png) | [Ảnh](../artifacts/ui-restore/gui-100/automation-drag-light.png) |

### DPI 150%

| Vùng | Dark | Light |
| --- | --- | --- |
| CapCut thủ công, ba nhóm/chia hai part | [Ảnh](../artifacts/ui-restore/gui-150/capcut-manual-dark.png) | [Ảnh](../artifacts/ui-restore/gui-150/capcut-manual-light.png) |
| Automation nhiều nhóm | [Ảnh](../artifacts/ui-restore/gui-150/automation-many-dark.png) | [Ảnh](../artifacts/ui-restore/gui-150/automation-many-light.png) |
| Empty state | [Ảnh](../artifacts/ui-restore/gui-150/automation-empty-dark.png) | [Ảnh](../artifacts/ui-restore/gui-150/automation-empty-light.png) |
| Drag-over hàng thứ ba | [Ảnh](../artifacts/ui-restore/gui-150/automation-drag-dark.png) | [Ảnh](../artifacts/ui-restore/gui-150/automation-drag-light.png) |

## E. Giới hạn

- GUI dùng Qt offscreen và `QT_SCALE_FACTOR`; chưa thay display DPI của Windows thật hoặc kéo thả bằng Explorer/trackpad phần cứng. Đã gửi các Qt drag/drop/mouse/key events thực qua viewport/window.
- Không mở CapCut thật, chạy Sandbox, kiểm thử CUDA hay dịch API thật. Kết quả MAU được kiểm qua exporter/regression offline; giữ các giới hạn đã nêu trước về nghiệm thu trong CapCut thật.
- UI CapCut hiện tại đối chiếu cấu trúc `build_page` của HEAD v1.2.0 và ảnh người dùng; dữ liệu/thumbnail trong ảnh là fixture, không phải 1.567 cặp ảnh/voice của người dùng.

## F. Trạng thái

**READY FOR USER ACCEPTANCE**.

Không build Installer, tăng version, commit/push hoặc publish. Không xóa SQLite, source, media hay checkpoint của người dùng. Snapshot trước sửa, patch và kết quả kiểm tra được giữ trong `artifacts/ui-restore`.
