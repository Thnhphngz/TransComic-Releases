# TransComic v2.0.4 — candidate

Sửa xóa lịch sử TTS ngay sau mở lại: kiểm tra runtime không khóa mục đã kết thúc; xóa bản ghi giữ WAV/MP3. Lịch sử Automation có thể được ẩn mà không xóa checkpoint. Lỗi ghi được báo và không làm danh sách biến mất trước commit.

Sửa thoát khi Automation đang kiểm tra nháp; lưu intent thêm tài liệu/ghép ảnh để khôi phục sau mở lại, chặn kết quả cũ ghi đè mapping mới. Không tự bắt đầu dịch/TTS/CapCut.

Bổ sung log thời gian cập nhật trong `Updates/update-timing-*.jsonl`: tải/xác minh, bàn giao helper, Safe Exit, chờ tiến trình cũ/launcher, Installer, xác minh bản cài, gọi EXE và nhận startup receipt. Helper mới ghi thêm log Inno `installer-*.log`. Log timing chỉ chứa stage, version, PID, thời gian và mã lỗi an toàn; không chứa API key, nội dung, argv hoặc startup ticket.

EXE mới xác nhận startup sau paint và lượt xử lý GUI tiếp theo, không dùng sleep cố định; lỗi xác nhận không tạo receipt thành công. Không thay schema receipt, checksum, xác minh process identity hoặc cơ chế khôi phục.

**Giới hạn tương thích:** v2.0.3 → v2.0.4 vẫn dùng helper được đóng gói trong v2.0.3. Release mới không sửa được helper đang chạy ở phía cũ. EXE v2.0.4 ghi được log startup với startup ticket cũ; log tải/Installer/restart mới có đầy đủ từ helper/app v2.0.4 khi cập nhật các bản sau. Chưa có bằng chứng xác định nguyên nhân mở lại chậm trên laptop thứ hai, không tuyên bố đã chữa được độ chậm đó.

**Gate phát hành:** chưa có môi trường Windows riêng truy cập được để cài sạch và nâng cấp thật v2.0.3 → v2.0.4; người dùng đã xác nhận phải ghi rõ bước bị chặn. Không cài đè production, không dùng Sandbox và không lấy mock/download/hash thay native upgrade. Giữ candidate chưa public cho đến khi gate đạt; không kế thừa waiver native update của đợt v2.0.3.

Thành phần, Mutagen, tài nguyên/animation CapCut MAU và hồ sơ quyền phân phối giữ nguyên.

Pipeline build tách phân tích GUI và helper thành hai tiến trình PyInstaller tuần tự để giảm đỉnh RAM; giữ nguyên định dạng onedir GUI, onefile helper và các kiểm tra nguồn/PE/checksum trước đóng gói.
