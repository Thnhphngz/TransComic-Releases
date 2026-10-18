# TransComic v1.2.0

## Tính năng mới

- Xuất Project CapCut sử dụng template MAU.
- Quản lý nhiều nhóm ảnh/voice trong giao diện hai cột.
- Xuất từng nhóm, gộp toàn bộ hoặc chia đều thành nhiều part liên tiếp.
- Tùy chỉnh tên project/part, tạo cover từ ảnh đầu tiên của từng project.
- Thumbnail, tìm/lọc media, nghe voice và xem ảnh ngay trên từng hàng.
- Giữ hai video track, animation/keyframe, audio gap bằng 0 và thứ tự media.

## Cải tiến

- Nút Phát/Dừng và Xem ảnh theo Liquid Glass, hỗ trợ Light/Dark.
- Cải thiện phân phối, trạng thái quota/rate limit và recovery của Kira Multi-Key.
- Đóng gói tài nguyên animation MAU độc lập với cache máy phát triển.
- Bổ sung dependency đọc MP3 và đồng bộ source/notices của thư viện.

## Lưu ý

- Project liên kết ảnh/audio gốc; không di chuyển hoặc xóa chúng khi còn dùng project.
- Tài nguyên effect nhỏ của MAU được lưu trong project; không tạo MP3 gộp hoặc copy media đầu vào.
- Cần CapCut tương thích với template MAU. CapCut GUI và cập nhật máy thứ hai cần người dùng nghiệm thu.
- Kokoro được smoke test bằng CPU với cache đã xác minh, tạo WAV/MP3 ngắn; không tải lại model lớn hoặc thử CUDA trong đợt này.
- Một test MouseFocus trong full regression trước còn ghi nhận đổi current index sau click Play. Người dùng đã xác nhận thao tác thực tế; focused tests kiểm chứng audio/ảnh dựa trên hàng được nhấn, kể cả khi hàng đang chọn khác. Không tuyên bố full regression đã PASS lại.
- Installer không có chữ ký Authenticode. Updater sử dụng HTTPS và SHA-256 theo cơ chế hiện có.
