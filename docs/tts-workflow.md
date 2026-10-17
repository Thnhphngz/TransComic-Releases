# Text to Speech V4.1 — cách sử dụng

Mã nguồn **1.0.4**, chưa có trong Installer đã phát hành. Mở bằng `python run_transcomic.py`; giữ nguyên `.venv` CUDA đã hoạt động, không cài chồng ONNX Runtime CPU. Kokoro v1.0 không hỗ trợ tiếng Việt.

## Tạo audio

1. Mở **Text to Speech**, xem backend thực tế ngay cạnh tiêu đề: **Kokoro · CUDA GPU** hoặc **Kokoro · CPU**. CUDA chỉ được xác nhận sau audio probe và node GPU; nếu GPU lỗi, ứng dụng thử CPU và cập nhật nhãn.
2. Chọn ngôn ngữ, voice, speed, WAV/MP3, nơi lưu và số đoạn đồng thời trên trang chính. Mặc định số worker tự động dựa trên profile benchmark và RAM/VRAM trống; máy/config chưa được đo dùng 1. MP3 kbps chỉ hoạt động khi chọn MP3.
3. **TTS Hàng Loạt**: Thêm file, Nhập thư mục hoặc kéo TXT/DOCX lên bảng. Có checkbox/chọn tất cả, Xóa file đã chọn, Xóa toàn bộ danh sách. File nhập mới dùng xuống dòng; không bị thay đổi bởi chế độ tách của editor Nhập văn bản.
4. **Nhập văn bản**: sửa tên output và nội dung trực tiếp. Bên phải hàng tab có toggle **Tách văn bản**: OFF = một audio; ON chọn Theo câu hoặc Theo dòng. Bộ đếm lấy từ thuật toán segment thật. Bật/tắt giữ nguyên hình học hàng tab; cửa sổ hẹp bố trí hai hàng cố định. Không có nút Xóa toàn bộ trong tab này.
5. **Bắt đầu** dùng cấu hình hiện tại. Cạnh file nguồn chạy ngay khi hợp lệ; Thư mục tùy ý mở picker. Văn bản nhập cần chọn thư mục cụ thể. Cancel picker không tạo job/audio. Không có nơi xuất “gần nhất” hoặc nút xác nhận riêng.
6. Sửa tên/text/cấu hình sau khi tạo audio cho phép bấm Bắt đầu tạo **job ID mới**, giữ job và output cũ. Trùng tên thư mục được cấp suffix an toàn. Lượt đang chạy giữ nguyên snapshot cấu hình.

## Điều khiển job — ý nghĩa mới

- **Tạm dừng**: ngừng cấp thêm đoạn, cho lease đang chạy về checkpoint an toàn; giữ audio, cho **Tiếp tục**.
- **Dừng / Hủy**: hủy vĩnh viễn phần chưa hoàn thành. Persist `cancelled` ngay, khóa claim/commit/resume, hủy process inference. Giữ file đã tạo và lịch sử. Mở lại ứng dụng cũng không được resume job đó.
- Muốn chạy lại job đã hủy: Bắt đầu tạo job mới; không tái kích hoạt ID cũ hoặc ghi đè audio cũ.
- Thoát ứng dụng theo chính sách thoát an toàn dùng **interrupted**, khác Hủy. Crash cũng được reconcile theo manifest/revision/hash trước khi khôi phục.
- Job `stopped` từ phiên trước vẫn được giữ nguyên, hiện “Đã dừng (cũ)”; có thể khôi phục qua lịch sử với đối chiếu output. Không chuyển hàng loạt dữ liệu cũ sang cancelled.

## Lịch sử và nghe thử

- Panel bên phải cao từ header tới đáy, cuộn riêng, luôn hiện. Card chỉ chứa tên, ngày, voice/speed, backend/format, số audio/trạng thái, Xem câu/Nghe và menu `⋯`.
- Tìm trực tiếp theo tên hoặc voice bằng ô **Tìm lịch sử TTS...**. Card tải theo nhóm 20; bảng câu dùng model/view.
- File hàng loạt hoặc input nhiều đoạn: **Xem câu** mở dialog riêng, không bung card. Có tìm theo STT/text, toàn bộ đoạn pending/running/success/cancelled/error, preview đầy đủ, Phát/Dừng cho audio sẵn sàng. Thiếu file hiển thị mềm; không tự sửa lịch sử để che mất file.
- Input Không tách/một đoạn: card chỉ có **Nghe** khi audio sẵn sàng, không mở danh sách câu.
- Một player chung nằm giữa phía dưới vùng làm việc, có Phát/Tạm dừng, tên file, tua, thời gian, âm lượng và **×**. Không nằm trong card/dialog, không phát chồng, không che nút inference. **× dừng phát thật rồi ẩn player; không hủy job TTS**.
- Đóng dialog không tự dừng audio: player chung vẫn hiện và điều khiển được. Đổi tab TTS không tạo player khác.
- Menu `⋯` của card: mở folder, relink, chi tiết, điều khiển job hợp lệ, xóa bản ghi. Không có Tiếp tục cho cancelled/completed. Folder mất thì Open disabled, có Liên kết lại.
- Nút **Xóa lịch sử** ngay header mở xác nhận toàn bộ, kể cả ngoài bộ lọc; chỉ xóa metadata lịch sử, **giữ audio, file nguồn, model/runtime và tài liệu nháp**. Chặn khi còn job lịch sử đang chạy/paused/recoverable; không tự hủy job.
- Import, sửa nháp và chọn cấu hình không tạo card lịch sử. Card xuất hiện khi **Bắt đầu** hợp lệ được scheduler chấp nhận; lỗi runtime sau đó vẫn giữ bản ghi để chẩn đoán.
- Player lấy đầu ra mặc định hiện tại khi phát audio mới. Đổi default/kết nối/ngắt thiết bị đầu ra sẽ dừng nguồn cũ an toàn; nhấn Phát từ card/popup để phát lại. Không tự tiếp tục sang loa sau khi ngắt tai nghe. Không đổi thiết lập Windows.
- Tab **Chi tiết** dùng editor Qt với Ctrl+Z native khi editor đang mở. Sau Enter/chuyển ô, Ctrl+Z tại bảng hoàn tác lần commit gần nhất nếu cùng segment/revision và job không chạy; đây không phải lịch sử Undo toàn ứng dụng.
- **Xóa toàn bộ** ở tab Hàng Loạt chỉ dọn danh sách hiện tại, giữ editor nhập văn bản và toàn bộ lịch sử/audio đã chạy.

## Model, runtime và lỗi

**Luồng setup mới:** trong Cài đặt nhấn **Tải model** một lần. Ứng dụng tự tải variant/voice, chuẩn bị runtime CPU/CUDA khi cần, kiểm tra inference và cả WAV/MP3 trước khi báo Sẵn sàng. Có Hủy tải/Thử lại, dùng lại file đã xác minh và resume file dở. Không yêu cầu pip/Python/CUDA thủ công. Xem [báo cáo one-click và giới hạn Installer](tts-one-click-setup.md); nghiệm thu Windows sạch/frozen còn PARTIAL, chưa phát hành bản mới.

Cài đặt tập trung quản lý model, tải/hủy/gỡ model, chẩn đoán và log. Luồng one-click dùng catalog artifact cố định để chuẩn bị runtime độc lập trong dữ liệu ứng dụng; descriptor GPU pack cũ vẫn được hỗ trợ cho tương thích. Installer và nghiệm thu Windows sạch chưa thực hiện; trạng thái phân phối vẫn **PARTIAL**.

Không còn status strip dưới bên trái. Thông báo thường vào tooltip/header hoặc Cài đặt; lỗi quan trọng mở popup chẩn đoán có traceback và Sao chép lỗi đã lọc secrets. Nhãn header luôn theo backend đang dùng, không theo backend mong muốn.

Output giữ quy tắc `_TTS_inprogress` → `_Ntts`, filename `0001.wav/mp3`, manifest, revision/attempt fencing, hash, recovery và collision an toàn. Database/model/output người dùng không bị dọn khi đổi giao diện.

Xem [hotfix V4.1 và ảnh](tts-ux-v41.md), [báo cáo V4](tts-ux-v4.md), [baseline CUDA](tts-cuda-parallel-hotfix.md), [license và giới hạn phân phối](tts-licenses.md).
