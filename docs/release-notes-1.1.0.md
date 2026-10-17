# TransComic v1.1.0 — Text to Speech & Windows Setup

- TTS Kokoro cho TXT/DOCX hàng loạt và văn bản nhập trực tiếp; tạo WAV/MP3.
- Tối đa hai worker TTS; CUDA trên NVIDIA tương thích, tự chuyển CPU khi cần.
- TTS → Cài đặt → Tải model tự chuẩn bị model, voice và runtime, xác minh checksum và inference. Lần đầu cần internet; cache hợp lệ được dùng lại sau restart/update.
- Nghe thử bằng thiết bị âm thanh mặc định Windows, popup xem câu, quản lý lịch sử, tạm dừng/tiếp tục/hủy.
- Cải thiện giao diện và đóng gói Windows; giữ chức năng dịch TXT/DOCX, Kira/Gemini, Multi-Key, biên tập và xuất tài liệu.

## Cập nhật từ v1.0.4

Mở **Kiểm tra cập nhật** trong ứng dụng đã cài → tải v1.1.0 → xác nhận cập nhật khi công việc đã lưu. Không gỡ bản cũ. SQLite, cấu hình, API key và dữ liệu TTS nằm ngoài thư mục cài đặt; không tự chuyển dữ liệu giữa các máy.

Windows 10/11 x64. Installer **UNSIGNED**; HTTPS và SHA-256 kiểm tra tính toàn vẹn, không thay thế chữ ký publisher. GPU phụ thuộc phần cứng/driver; người dùng không cần cài Python, pip, CUDA Toolkit hoặc cuDNN thủ công.

Source/notices của thành phần đi kèm nằm trong `ThirdParty` và asset `TransComic-1.1.0-ThirdParty-Sources.zip`. `SHA256SUMS.txt` giữ định dạng hai mục cho updater v1.0.4; checksum của source/notices nằm trong `ThirdParty-SHA256SUMS.txt`.
