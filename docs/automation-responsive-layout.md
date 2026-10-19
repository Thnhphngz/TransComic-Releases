# Automation — final responsive layout & dependency validation

> Báo cáo lịch sử của lượt 62:38. Yêu cầu mới về layout 70:30, pinned actions và Project luôn hiện đã được thực hiện trong [Automation compact panel](automation-compact-panel.md).

## A. Layout

- Đã loại `QSplitter` giữa danh sách chương và panel bên phải. Automation không còn splitter con hoặc handle kéo tay; `QHBoxLayout` dùng stretch **62:38**. Kiểm tra kéo tại khe hai cột không thay đổi kích thước.
- Khe 14 logical px, card bo góc và viền mảnh, gradient rất nhẹ theo theme. Sidebar/theme toàn ứng dụng giữ nguyên.
- Trái có minimum 280, phải minimum 300 logical px; phần còn lại tự phân phối. Màn hình hẹp ưu tiên control đọc được, không ép cửa sổ rộng ra ngoài màn hình.
- Toolbar tự chuyển bốn cột thành hai cột khi vùng trái hẹp; nhãn validation chuyển xuống ngay dưới tiêu đề khi cần. Cấu hình từ ba field một hàng chuyển thành một/hai field theo chiều rộng panel.
- Bảng nhận toàn bộ chiều cao còn lại, cuộn trong bảng. Panel phải chỉ cuộn dọc. Không có toolbar/spacer rỗng dưới bảng. Cột bảng có giới hạn chiều rộng để thanh tiến độ/nút không tràn sang cột khác; không ảnh hưởng tỷ lệ panel.
- Kiểm tra 900×580, 1200×780, 1672×941, 1920×1080; DPR 1.0 và 1.5. Khi panel hẹp, vòng hoàn tất thu gọn, tổng nhóm vẫn có trong mô tả; tên ba stage luôn còn.

## B. UX

- Thứ tự: **Kiểm tra lại → + Thêm tài liệu → Bắt đầu/Tiếp tục → Dừng an toàn**. Cùng chiều cao 36 px, spacing 6 px. Thêm tài liệu và Start khả dụng dùng accent; Stop có vai trò danger; icon kiểm tra dùng SVG.
- Badge cạnh tiêu đề thể hiện Chưa kiểm tra / Đang kiểm tra / Đầu vào hợp lệ / N nhóm lỗi / Cấu hình cần kiểm tra. Không tự gán PASS cho đầu vào chưa xác minh. Nhấn badge mở dialog cuộn được, giữ đầy đủ tên nhóm và lỗi, đóng bằng Esc.
- Bỏ card checklist cũ và ba nút lớn Chọn ảnh/sắp xếp, Mở trong Dịch, Mở kết quả. Giữ Ảnh trên hàng, nhấp đúp đúng stable group ID để mở Dịch, menu chuột phải để mở kết quả.
- Card Dịch/Kokoro/CapCut có icon, số liệu thật, thanh màu riêng và chiều cao thống nhất; vòng tròn dùng số nhóm hoàn tất thật. Các số đếm nổi bật hơn vòng trước.
- Giữ delegate/badge/progress nhỏ; không quay về văn bản tiến độ thuần. Không vẽ focus native xanh/trắng hoặc hover xám; focus bàn phím vẫn là nét accent tinh tế.
- Số part và preview chỉ xuất hiện trong mode split. Không đưa lại Model Kokoro, Runtime, nhật ký nhóm hoặc xuất báo cáo thủ công.
- Kokoro vẫn **1 luồng — 1 nhóm mỗi lượt**. Khi active/stopping, cả widget và repository từ chối sửa cấu hình; thử thay giá trị bằng code bị khôi phục về cấu hình thật, không làm giao diện hiển thị sai.

## C. Validation

| Phụ thuộc | Kiểm tra | Khi thay đổi cấu hình |
| --- | --- | --- |
| Source/Image theo nhóm | Source SHA, đơn vị dòng/ID/revision, ảnh/định dạng/sắp xếp, số lượng/mapping, dung lượng | Stamp/version cache chỉ hợp lệ với đúng nguồn, thư mục, thứ tự và tập ảnh đã xác minh. Thay đầu vào chỉ làm lại nhóm liên quan. |
| Translation | Provider/model, cặp ngôn ngữ, worker, trạng thái key/project và giới hạn Gemini | Chỉ invalidate phần dịch; không parse lại Word hoặc probe lại ảnh khi input stamp còn đúng. Metadata API key thay đổi cũng đổi fingerprint; không lưu secret vào cache. |
| Kokoro | Target/voice/language/speed/variant/device/format, tài nguyên model/runtime | Chỉ invalidate Kokoro. Bất biến của bộ đã chạy không đổi. |
| CapCut | Mode, số part, tên, thứ tự nhóm/part, thư mục, dung lượng và quyền ghi | Chỉ invalidate CapCut. Quyền ghi kiểm bằng file tạm duy nhất, không chạm output cũ. |

Cache được thêm vào metadata/checkpoint JSON hiện có, có version; không reset SQLite hay yêu cầu schema migration phá dữ liệu. Bộ cũ không có cache được kiểm tra đầy đủ rồi bổ sung cache.

- UI debounce tự kiểm tra cấu hình sau lần đầu kiểm tra đầu vào, không bắt người dùng bấm nút nhiều lần. Nút Kiểm tra lại vẫn xác minh lại điều kiện cấu hình và fingerprint.
- Source được đối chiếu SHA; input stamp kiểm tra tập file/size/mtime/ctime/identity và revision dòng. Không chỉ nhìn tên thư mục. Kết quả lỗi tài nguyên được phép kiểm tra lại để hồi phục.
- Kết quả async thuộc config hoặc workset cũ không bật Start hoặc ghi đè badge mới.
- **Trước cấp việc**, `_run` luôn gọi validation đầy đủ với `reuse_inputs=False`: đọc/hash nguồn, probe/hash ảnh, kiểm tra mapping, config và tài nguyên. Cache UI không bỏ qua preflight đầu tiên hay integrity khi Resume.
- Regression sửa source/ảnh sau khi đã PASS, kể cả khôi phục mtime, đều bị fresh dispatch gate chặn trước khi tạo job/request. Resume nguồn đổi cùng cấu trúc vẫn giữ stable line IDs và invalidate batch cần thiết.
- Không sửa scheduler/provider, concurrency, retry, Safe Stop, engine Kokoro, MAU export hoặc output protection.

### Bằng chứng giảm quét

Fixture hai nhóm: lần đầu parse Word/TXT **2**, image manifest **2**. Sau đổi model/provider/worker, voice/speed hoặc part/tên project: parse **0**, image manifest **0**, chỉ section phụ thuộc chạy. Đổi thư mục ảnh của một nhóm: parse **1**, image manifest **1**, nhóm còn lại dùng snapshot đã xác minh. Thêm key: chỉ section Translation chạy, không gửi HTTP.

## D. Đối chiếu mockup thực tế

Đã tìm và mở đúng [mockup gốc người dùng gửi](../artifacts/automation-responsive/reference-candidate-44.png), không tạo lại ảnh tham khảo. Ảnh gốc 1672×941; ảnh nghiệm thu dùng cửa sổ 1672×941 logical px, DPR ghi trong JSON.

| Điểm | Trước sửa | Vòng 1 | Vòng cuối |
| --- | --- | --- | --- |
| Chia vùng | Splitter, hai khối chạm cạnh, handle nhìn rõ | Layout tự động, khe thoáng, card gradient | Giữ bố cục thống nhất, không kéo đổi tỷ lệ |
| Validation | Card ở đáy phải | Badge cạnh tiêu đề, click xem lỗi | Có trạng thái async và bảo vệ kết quả cũ |
| Toolbar/đáy bảng | Check ở cuối, ba nút lớn dưới bảng | Đúng thứ tự mới, bỏ toàn bộ footer | Icon SVG, không cắt chữ ở hai hàng |
| Cấu hình | Hàng ba field cố định | Có reflow; phát hiện ô số hẹp trong ảnh | Grid 12 cột chia span hợp lý, đủ nút tăng/giảm; test control nằm trong parent |
| Tiến độ | Số đếm nhỏ, ít phân cấp | Thêm icon và font số 17 px | Kiểm tra lần nữa Light/Dark/DPI; không chồng card/vòng |

Ảnh giữ lại cho từng vòng:

- [Trước sửa — Dark](../artifacts/automation-responsive/before-dark.png) · [Light](../artifacts/automation-responsive/before-light.png)
- [Vòng 1 — Dark](../artifacts/automation-responsive/pass-1/polish-dark.png)
- [Cuối — Dark 100%](../artifacts/automation-responsive/gui-100/polish-dark.png) · [Light 100%](../artifacts/automation-responsive/gui-100/polish-light.png)
- [Cuối — Dark 150%](../artifacts/automation-responsive/gui-150/polish-dark.png) · [Light 150%](../artifacts/automation-responsive/gui-150/polish-light.png)
- [Cửa sổ hẹp 150%](../artifacts/automation-responsive/gui-150/responsive-narrow.png)

Giống mockup: bố cục hai cột, hierarchy tiêu đề/bảng/card, charcoal/nâu + orange accent, icon/progress ba bước và vòng hoàn tất, các trạng thái màu, glass nhẹ. Khác có chủ đích: mockup cũ có nhật ký/checklist/năm nút, nhưng yêu cầu mới đã bỏ hoặc di chuyển; source giữ chọn workset, cấu hình ngôn ngữ nguồn/Kokoro và preview thực. Qt không mô phỏng acrylic/blur theo từng pixel. Số liệu khác ảnh mẫu vì lấy từ fixture đã chạy, không dùng con số minh họa cố định. Ảnh Qt grab là client area, mockup có cả thanh tiêu đề hệ điều hành.

## E. Tests

| Lượt | Kết quả |
| --- | --- |
| Automation service, dependency validation, toàn bộ GUI tại thời điểm chốt vòng 2 | **70 PASS / 0 FAIL**, `artifacts/automation-responsive-regression.log/xml` |
| Dependency tests riêng, nằm trong 70 ca trên | **11 PASS / 0 FAIL**, `automation-responsive-dependencies.log/xml` |
| GUI DPR 1.5 | **23 PASS / 0 FAIL**, `automation-responsive-gui-150.log/xml` |
| Kết quả validation trả về chậm không bật Start bằng config cũ, bổ sung sau lượt 70 | **1 PASS**, `automation-responsive-late-result.log` |
| Thêm key/đổi nhóm tài khoản chỉ kiểm tra Translation, không quét media | **2 PASS**, `automation-responsive-api-config.log`; ca đổi nhóm tài khoản bổ sung sau lượt 70 |
| Giới hạn resize cột, bổ sung assertion sau vòng ảnh 1 | **4 PASS**, `automation-responsive-column-bounds.log` |
| Chụp cuối cùng kích thước tham khảo, Light/Dark 100% và 150% | **2 PASS mỗi scale**, `automation-responsive-final-shots-100.log`, `automation-responsive-final-shots-150.log` |

Các lượt trùng ca, không cộng số lần chạy thành số ca duy nhất. Không có lỗi chưa xử lý. Không chạy lại toàn bộ suite 1.713+ bài vì thay đổi tập trung UI/validation; test pipeline/retry/recovery/share tabs nằm trong focused regression 70 ca. UI tương tác dùng Qt thực, backend HTTP mock và PCM tổng hợp; không dùng API thật, truyện sản xuất, GPU/CUDA stress hoặc Sandbox.

Đã kiểm tra nguồn version 1.2.0 và tám runtime worker giữ nguyên từng byte. Icon mới được glob resource hiện có nhận diện; không build, tăng version, commit/push hay release.

## F. Trạng thái

**READY FOR USER ACCEPTANCE**
