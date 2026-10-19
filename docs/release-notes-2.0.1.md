# TransComic v2.0.1 — Sửa lỗi dịch HTTP 504 và khôi phục API

- Sửa thao tác dịch lại một dòng, dòng đã chọn, lỗi của file và lỗi trong workspace: tạo chu kỳ mới, không mang cờ đã hoàn tất hoặc bộ đếm chờ của job cũ.
- Chu kỳ Kira mới tự xử lý gateway timeout theo giới hạn request đầu + tối đa ba retry + một rescue cuối, đồng thời tôn trọng các trần request/token/retry đã cấu hình. Lượt cũ giữ ngân sách và bộ đếm đã lưu.
- HTTP 504 vẫn là gateway timeout, không phải quota. Tách thông báo cần kiểm tra lỗi API khỏi quota thực sự đã được provider xác nhận.
- Backoff có giới hạn/jitter và tôn trọng Retry-After của lỗi gateway; có thể dùng key Kira khác khả dụng, giữ nguyên provider/model.
- Giảm concurrency hiệu dụng khi gateway lỗi; tăng dần sau chuỗi thành công. Không sửa số luồng người dùng đã lưu hoặc hủy request đang in-flight.
- Dịch lại dùng key pool hiện tại, giữ cooldown/quota thật của key cũ, và không gửi trùng dòng đang processing.
- Giữ các dòng thành công, lịch sử attempt và checkpoint. Không tự gửi request khi mở lại ứng dụng.
- Áp dụng ở tầng engine dùng chung với Automation; không thay đổi mapping Word/ảnh/WAV, Kokoro hoặc MAU exporter.

## Phạm vi kiểm chứng

Mock HTTP có đếm dispatch thực, kiểm tra các nút dịch lại, fixture 290 dòng (266 thành công, 24 lỗi), recovery và Automation. Smoke EXE bằng dữ liệu tổng hợp từ EXE v2.0.0, bao gồm dịch lại lỗi 504 sau cập nhật, Light/Dark, CPU Kokoro và MAU.

Không chạy API dịch thật, Windows Sandbox hoặc stress GPU/CUDA. Không cài đè ứng dụng đang dùng. **Native Install/Restart và nâng cấp trên máy thứ hai: NOT VERIFIED.** Installer chưa ký Authenticode; updater giữ HTTPS + SHA-256 theo cơ chế hiện có.
