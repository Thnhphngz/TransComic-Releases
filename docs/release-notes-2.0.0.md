# TransComic v2.0.0 — Tự động hóa Dịch → Kokoro → CapCut

## Tính năng mới

- Quản lý nhiều bộ công việc DOCX/TXT và thư mục ảnh; kéo thả theo từng nhóm.
- Pipeline Dịch → Kokoro TTS → project CapCut MAU, theo dõi tiến độ từng bước.
- Điều phối Kira/Gemini, retry có giới hạn, Dừng an toàn và Tiếp tục.
- Checkpoint/recovery; mở ứng dụng không tự chạy lại bộ công việc hoặc gửi API dịch.
- Xuất từng nhóm, gộp hoặc chia part; báo cáo HTML/JSON.
- Đồng bộ dữ liệu giữa các trang; chạy nền và mở lại bằng Windows System Tray.

## Giao diện

- Dashboard Automation hai cột responsive, Light/Dark, cấu hình khóa khi đang chạy.
- Sidebar gồm Dịch, Text to Speech, CapCut, Tự động hóa, Lịch sử, API và Cài đặt.
- Giữ trải nghiệm xuất CapCut thủ công của v1.2.0.

## Tương thích và phạm vi xác minh

- Dùng updater và định danh cài đặt hiện có để nâng cấp từ v1.2.0 lên v2.0.0.
- Kiểm tra migration bằng dữ liệu tổng hợp từ mã trong EXE v1.2.0; bảo toàn cấu hình,
  key mã hóa, lịch sử và các file ngoài database. Kiểm tra mở lại checkpoint thử nghiệm.
- Smoke trên EXE đóng gói: HTTP dịch mock, Kokoro CPU từ cache cô lập, MAU và Tray.
- **Install/Restart qua Installer thực tế và nâng cấp trên máy thứ hai: NOT VERIFIED.**
  Chưa tuyên bố đã kiểm chứng toàn bộ chuỗi cập nhật native. Không cài đè ứng dụng đang dùng.
- Không gọi API dịch thật, không Windows Sandbox, không stress CUDA/GPU.
- Installer chưa có chữ ký Authenticode; updater dùng HTTPS và SHA-256 theo cơ chế hiện có.
- Không chạy lại CapCut GUI trong đợt đóng gói; kiểm chứng cấu trúc MAU và tài nguyên bằng smoke test.
