# Tự dịch lại và quản lý hàng loạt — 13/10/2026

> Báo cáo mới hơn: [retry, tìm/thay nhiều file và lưu giao diện](retry-speed-workspace.md). Đợt sáu lượt trên ba DOCX có ledger riêng; số liệu dưới đây thuộc đợt trước.

## Nguyên nhân và bản sửa

1. Nguyên nhân tự pause: scheduler gọi `pause()` khi 429 không có `Retry-After`, đồng nhất reset chưa biết với quota cạn. Retry dùng vòng 1–4, còn khôi phục chỉ lấy batch `pending`, bỏ qua lỗi có attempt đã hoàn tất.
2. 429 tạm thời hiện không bật cờ pause của người dùng. UI hiển thị `Chờ API`, thời gian còn lại và effective/configured concurrency; danh sách file hiển thị `Chờ giới hạn API`.
3. Deadline cooldown kết thúc thì tự tiếp tục. Pause của người dùng và Stop chặn tiếp tục. Quota được provider xác nhận, lỗi quyền/key/model và vượt giới hạn chờ cần can thiệp; provider độc lập trong hàng loạt retry tiếp tục công việc riêng.
4. Mặc định mới: 5 retry sau lần đầu, tối đa 6 attempt. Tắt/1/2/3/4/5 có trong Cài đặt. Cấu hình đã lưu và job cũ giữ ngân sách của chúng; không nâng ngân sách lịch sử.
5. Các dòng thiếu đủ điều kiện được tự lên lịch ngay sau phản hồi. Khôi phục dựng lại retry từ attempt đã lưu hoàn tất, kiểm tra chính sách và revision. Batch tối đa 3 dòng, giữ context, loại các dòng đã thành công hoặc được sửa thủ công.
6. Những dòng lỗi cuối lượt được thử tiếp tới giới hạn; nếu hết giới hạn hoặc không thể retry an toàn thì giữ lỗi và bản dịch cũ hợp lệ. Nút Tiếp tục không yêu cầu phải còn batch chưa gửi; nút dịch lại lỗi thủ công vẫn dùng xác nhận riêng.
7. SQLite schema 8 giới hạn attempt 1–6, unique batch/attempt, lưu reservation trước HTTP. Attempt 7 bị chặn cả ở policy, scheduler và database. Migration giữ request, trace và foreign key. Attempt mất trạng thái sau crash không tự replay.
8. Cooldown dùng chung scope. Nếu thiếu reset, backoff 1, 2, 4… giây với jitter, giới hạn 30 giây trước jitter. Mặc định tối đa 10 đợt và tổng thời gian chờ thêm 300 giây; các ngưỡng chỉnh được trong Cài đặt và đóng băng cho job mới. `Retry-After` vượt trần chờ dẫn đến cần can thiệp. Đây là chính sách ứng dụng, không phải hạn mức Kira chính thức.
9. Sau 429 effective concurrency giảm về 1, khoảng cách gửi tối thiểu 0,05 giây. Cả request mới và retry chia sẻ gate. 50 phản hồi cùng một cooldown không bị tính thành 50 đợt chờ. Không tự tăng về 50 trong lượt đang phục hồi.
10. `other_import_not_displayed` là DEBUG bình thường. Kết quả vẫn lưu theo document/job/line ID và revision trước thông báo GUI; không pause hay đánh dấu lỗi vì đang xem file khác.
11. Component chung trong `ui/controls.py` chặn wheel trên combo đóng, chuyển tới viewport cuộn cha; popup cuộn qua view, hỗ trợ keyboard/click.
12. Chỉ spinbox Luồng có `allowWheel`; các spinbox cấu hình khác bỏ qua/chuyển wheel. Kira giữ 1–50, mặc định 30 nếu chưa lưu; Gemini dùng quota riêng.
13. Import GUI truyền danh sách workspace hiện hành vào `import_many`: resolved absolute path, Windows normcase, separator, alias. Cùng path không tạo instance/reset/sync; chọn mục đã có và báo ngắn. Nội dung ổ đĩa đổi thì cảnh báo. Import đang chạy được serialize bằng `import_busy`.
14. Hai thư mục khác nhau cùng tên/hash vẫn độc lập. Bỏ khỏi workspace rồi nhập lại tạo ID mới, bản dịch trống; lịch sử cũ được giữ.
15. Hoàn tất đầy đủ/còn lỗi/cần can thiệp có thông báo trong ứng dụng, tray Windows và yêu cầu âm thanh qua `winsound`. Chống lặp theo scheduler session, không tự xuất/Explorer/chuyển trang. Hệ điều hành có thể tắt thông báo/âm thanh. Để tương thích lịch sử, SQLite vẫn dùng terminal `finished`; event `job_completed.reason` phân biệt `completed`/`completed_with_errors`, trạng thái UI dựa trên số bản dịch hợp lệ.

## Bằng chứng kiểm thử

16. Toàn bộ pytest: **306 passed, 1 skipped trong 65,36 giây**. Skip thuộc ledger fixture Word offline cũ đã dùng đủ 3 lượt, không bị reset. Đợt thật mới dùng ledger riêng. Có test 1/2/5 retry rồi thành công, 6 attempt vẫn lỗi, partial/resume, 429 có/không reset, quota, 50 worker, pause/stop cooldown, crash, revision, migration trace, notification, wheel và import trùng. Không xóa test cũ; cập nhật kỳ vọng cũ trái chính sách mới.
17. Smoke native Windows qua `run_transcomic.py`: 3 DOCX tạo riêng, 54 dòng, **25 request mock gồm 7 retry**, peak 3, tự tiếp tục cooldown, mọi dòng hoàn tất, chặn duplicate/wheel, giữ scroll, một notification, không xuất. Ảnh và JSON ở `artifacts/retry-management/gui/`. Đã xem ảnh cooldown để sửa cả lỗi nhãn bị ghi đè và nhãn bị cắt.
18. Hạn chế: không thể đảm bảo hết 429 phía server; quota cạn, timeout/crash chưa rõ, lỗi quyền và database không tự khắc phục. Ngữ nghĩa bản dịch vẫn cần biên tập; kiểm tra ID/dữ liệu đầy đủ không chứng minh mọi câu dịch đúng. Giá/usage là số quan sát, không có xác nhận trừ tiền ví và không có billing cap do provider áp đặt. Native smoke xác minh yêu cầu phát âm thanh, không xác minh người dùng nghe thấy âm thanh.

## API thật được cho phép riêng

19. User cho phép tối đa 5 lượt `7-8.docx`, Kira DeepSeek, tổng 10.000đ. Đã dùng **1 lượt**, đúng `deepseek-v4.1-flash`, VI→EN, 125 dòng, concurrency 30, max output 2.048 token/request, tối đa 252 request/job kể cả retry. Kết quả **125/125 dòng done**, **43 request: 42 HTTP 200 và 1 HTTP 504**; batch 504 gồm 3 dòng tự retry một lần thành công, không cần Tiếp tục. Không có 429 trong lượt thật. Max attempt thực tế 2, 125 trace accepted, foreign key check sạch, không xuất file tự động.

   Usage các phản hồi có báo: input **49.399**, output **21.993**, total **71.392**. Theo [giá DeepSeek công khai](https://kiraai.vn/models/deepseek-v4.1-flash/) kiểm tra lúc chạy: input gốc 3.900đ/1M, output gốc 15.600đ/1M (sale 2.730đ và 10.920đ). Usage đã báo tương ứng khoảng **535,75đ theo giá gốc**; 504 không báo usage nên không biết phí thực tế của request đó. Tổng ngân sách dự phòng đã giữ trước 43 request là **1.959,48đ**, dưới trần 10.000đ, không coi đây là số trừ ví thực tế. Dừng gửi tiếp nếu usage HTTP 200 thiếu hoặc vượt token dự tính. Ledger không cho tự chạy lại/xóa để thử thêm.

   Bằng chứng: `artifacts/retry-management/live-deepseek/authorization-ledger.json`, `prices.json`, `results.sqlite3`, `events.json`, `pass-1-lines.json`. Kiểm tra các dòng 31–33 và 73–75 trong ảnh lỗi trước: đều có bản dịch đã lưu. Một số tên/cách diễn đạt cần biên tập; không chấm toàn bộ ngữ nghĩa 100%.

20. **Không build EXE, installer hoặc release.** Mã, dữ liệu thử độc lập, ảnh GUI và báo cáo là kết quả của đợt này. Không sửa Word gốc hoặc database/key của người dùng.
