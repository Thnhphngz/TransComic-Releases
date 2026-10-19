# Tự động hóa: Dịch → Kokoro → CapCut

## Sử dụng

1. Mở **Tự động hóa**, tạo bộ công việc và thêm từng file DOCX/TXT hoặc kéo thả nhiều file từ Explorer. Thư mục tài liệu không được quét tự động.
2. Chọn thư mục ảnh cho từng hàng bằng nút **Ảnh**; có thể kéo thư mục ảnh trực tiếp vào bất kỳ ô nào của hàng đó. Drop giữ chính sách sort đang chọn; không đoán hàng qua tên folder. Folder được kiểm tra ngoài GUI trước khi ghi mapping; folder rỗng/lỗi giữ nguyên mapping cũ. Số lượng và badge tự kiểm tra sau khi nhận, không tự chạy dịch.
3. Kiểm tra cấu hình chung, provider/model dịch, ngôn ngữ, voice Kokoro, tốc độ và thư mục project. Model/runtime Kokoro giữ cấu hình nội bộ hiện có; UI ghi rõ **Kokoro: 1 luồng · 1 nhóm mỗi lượt**. Chọn xuất riêng nhóm, gộp hoặc chia đều; bảng Project / sửa tên luôn hiện cho cả ba chế độ. Số part giữ nguyên vị trí, chỉ được chỉnh trong chế độ chia.
4. Bấm **Kiểm tra lại**. Lần đầu chỉ được bắt đầu khi tất cả nhóm hợp lệ, số dòng cần voice khớp ảnh và tài nguyên sẵn sàng. Xem xác nhận trước khi chạy.
5. Bấm **Bắt đầu**. Dịch dùng tối đa số worker tổng đã chọn; Kokoro xử lý một nhóm, CapCut xuất một project tại một thời điểm. Các stage chạy chồng nhau khi có nhóm sẵn sàng.
6. **Dừng an toàn** ngăn cấp việc mới, chờ request/WAV/project đang xử lý đạt điểm lưu an toàn. Chỉ chỉnh sửa sau khi dừng xong. Voice/model/tốc độ/runtime của bộ đã chạy vẫn cố định.
7. Muốn sửa bản dịch, mở nhóm trong tab **Dịch**. Automation cập nhật checkpoint và đánh dấu voice/project phụ thuộc cần kiểm tra. Không chỉnh sửa voice của bộ này qua tab TTS.
8. Sau khi dừng hoặc mở lại ứng dụng, bấm **Kiểm tra lại**, rồi **Tiếp tục** để xử lý phần còn thiếu theo checkpoint. Không tự gọi API khi mở ứng dụng và không tự chạy bộ tiếp theo.

**Tab TTS khi Automation chạy:** chỉ hiển thị ngữ cảnh Automation và lịch sử chỉ đọc, không đưa bản nháp thủ công cũ vào batch đang hiển thị. Sau khi dừng/kết thúc, bản nháp còn nguyên được hiển thị lại với chú thích rõ. Các job Automation trong lịch sử có nhãn **Automation · Chỉ đọc**, cho phép xem câu/nghe audio; điều khiển tác vụ từ tab Tự động hóa.

Hàng công cụ Automation theo thứ tự **Thêm tài liệu → Kiểm tra lại → Bắt đầu/Tiếp tục → Dừng an toàn**; cửa sổ hẹp tự chia hai hàng. Hai cột tự bố trí bằng layout 70:30, không có splitter kéo tay. Trạng thái kiểm tra cạnh tiêu đề có thể nhấn để xem lỗi đầy đủ; thống kê nhóm nằm ngay bên dưới badge. Thời gian/trạng thái nằm cùng hàng tiêu đề Tiến độ tổng thể, ba thẻ stage gọn và vòng nhóm hoàn tất luôn được giữ lại.

STT và ba thao tác Ảnh / Dịch / × cố định hai mép bảng, dùng chung model và lựa chọn với phần nội dung. Đường dẫn rút gọn có tooltip; cột ít quan trọng co trước, phần giữa cuộn theo pixel khi cần. Shift+wheel hoặc delta ngang của trackpad cuộn ngang, không thay đổi các tab khác. Panel cấu hình cuộn dọc độc lập; trường thư mục hiển thị đường dẫn rút gọn khi không focus, giữ nguyên đường dẫn đầy đủ để chỉnh sửa. [Báo cáo refinement và ảnh đối chiếu](automation-compact-panel.md).

Header bảng Automation không kéo thay đổi kích thước được; ứng dụng tự tính theo viewport/font/DPI. Khi chưa có tài liệu, bảng hiện **Thêm hoặc kéo thả file văn bản vào đây**; bộ lọc không có kết quả hiện thông báo riêng. Sidebar chỉ còn Dịch, Text to Speech, Xuất Project CapCut, Tự động hóa, Lịch sử, API và Cài đặt; scheduler/hàng đợi, SRT và diagnostic logging vẫn giữ trong backend.

**Tab CapCut giữ giao diện thủ công v1.2.0**, không có dropdown/bảng Automation và không tự nhập các nhóm Automation. Xem tiến độ/project Automation ngay trong tab Tự động hóa, dùng menu hàng để mở kết quả. Mở tab CapCut không xuất thêm project hoặc thay checkpoint. [Báo cáo khôi phục UI](ui-restore-capcut.md).

Ba nút lớn dưới bảng đã bỏ; dùng **Ảnh** trên từng hàng, nhấp đúp để mở Dịch hoặc menu chuột phải để mở kết quả. Nhật ký nhóm và nút xuất báo cáo thủ công không có trong UI; log/checkpoint và báo cáo HTML/JSON tự động vẫn giữ trong backend.

Sau lần xác minh đầu vào, thay đổi cấu hình được tự kiểm tra theo nhóm phụ thuộc. Đổi model/provider/luồng, voice hoặc số part/tên/thư mục project không parse lại Word/probe lại ảnh khi fingerprint còn hợp lệ. Đổi đầu vào làm mất cache của nhóm tương ứng. Trước khi cấp việc, worker vẫn thực hiện gate đầy đủ với hash và mapping mới, không dùng cache UI để bỏ qua integrity.

## Lưu trữ và bảo vệ output

- Bản dịch dùng chính `Store.lines` của tab Dịch. Xuất DOCX/TXT cạnh nguồn với hậu tố ngôn ngữ thực; giữ định dạng DOCX bằng renderer hiện có.
- WAV dùng `TtsStore` và manifest hiện có, giữ số thứ tự slot gốc dù một câu lỗi. Bản sửa tạo thư mục voice phiên bản mới, giữ media cũ của project đã xuất.
- CapCut dùng exporter MAU hiện có, hai video track, keyframe/animation, audio gap 0 và đường dẫn media trực tiếp. Mỗi part bắt đầu timeline từ 0; không gộp MP3, không sao chép media vào project.
- File/project đã có không bị ghi đè. Output bị chỉnh sửa bên ngoài được giữ lại; output mới dùng hậu tố phiên bản.
- Checkpoint nằm trong SQLite, manifest và hash xác định quyền sở hữu. Mở lại chỉ nạp trạng thái; Resume kiểm tra lại source, ảnh, bản dịch, WAV và project trước khi cấp việc.
- Source thay đổi cấu trúc hoặc xung đột bản dịch sửa tay sẽ chặn riêng nhóm. Không dịch chuyển mapping để cố xuất. Khi thứ tự ảnh mới không xác định được, cần ghép lại rõ ràng.
- Báo cáo HTML/JSON ở `TransComic_Automation_Reports` cạnh file nguồn đầu tiên; lỗi ghi báo cáo không xóa checkpoint nội bộ.

## Retry và giới hạn

| Stage | Chính sách |
| --- | --- |
| Dịch | Batch gốc tối đa 3 dòng; ban đầu + 3 retry + 1 cứu lỗi cuối, tối đa 5 request/batch/chu kỳ. Chỉ gửi các dòng còn lỗi trong đúng ranh giới batch gốc. |
| 429 | Tôn trọng Retry-After; thời gian quá dài được lưu checkpoint và yêu cầu xử lý, không gửi sớm. |
| 504/timeout | Retry có giới hạn và backoff; không tự đổi provider. |
| Mất mạng | Kiểm tra TCP không gửi HTTP dịch, không tiêu thụ lượt thử. Safe Stop ngắt chờ. |
| Kokoro | Tối đa 5 lần/WAV/chu kỳ; lượt cứu cuối chờ các nhóm bình thường khác. Không tạo lại WAV thành công còn hợp lệ. |
| CapCut | Tối đa 4 lần với lỗi hệ thống tạm thời; không retry lỗi mapping, quyền ghi hoặc hết dung lượng. Publish atomic; giữ project đã hoàn tất. |

## Kiến trúc

`automation.repository` lưu metadata và liên kết định danh dòng gốc; `validation` lập mapping/part; `controller` điều phối và Safe Stop; `adapters` gọi Scheduler dịch, Kokoro và exporter MAU; `services` sở hữu tài nguyên dùng chung; `reports` xuất báo cáo. `ui.automation_page` trình bày tiến độ Automation; trang CapCut thủ công không chứa projection Automation.

Manifest lớn lưu riêng với metadata stage để tránh ghi lại toàn bộ danh sách ảnh mỗi bước. GUI cập nhật theo nhóm thay đổi, gộp tín hiệu theo timer; bảng nhóm dùng model/delegate thay vì tạo widget cho từng hàng. Giao diện dùng theme và GlassButton hiện có, hỗ trợ Light/Dark và cuộn khi cửa sổ hẹp.

Không thay đổi các file worker tạo identity runtime Kokoro; cache CPU/CUDA đã cài tiếp tục được nhận diện. Kiểm tra hiện tại là source/offline; không có build Installer hoặc kiểm thử Sandbox/CUDA trong đợt này.
