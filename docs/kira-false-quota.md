# Kira Multi-Key: sửa khóa quota lan sang tài khoản khác

## A. Nguyên nhân và bằng chứng trước/sau

Ngày kiểm tra: 18/10/2026. Tiếp tục trên source đang có; không phát hành.

Hai vấn đề khác nhau đã được xác minh:

1. **Provider từ chối thật:** diagnostics đã lưu có HTTP 402 / `vnd_balance_exhausted` với `mimo-v2.6-flash` và `coding-mimo-v2.6-flash`. Đây là các ID trả phí, khác ID có hậu tố `-free`. Profile đọc trực tiếp cho thấy Key 2 và Key 3 có số dư VND bằng 0, dù còn token/hạn mức free. Không thể dùng token free để kết luận model trả phí vẫn được phép gọi.
2. **Ứng dụng khóa nhầm các key khác:** `kira_account_scope()` mặc định `shared`; pool ghi `kira_model_quota:shared:<model>` sau một lỗi quota rồi loại mọi key trong nhóm. Không có bằng chứng ba key cùng tài khoản. Hai marker này vẫn tồn tại trong database. Profile GET thực tế trả ba định danh tài khoản khác nhau; báo cáo chỉ giữ hash định danh.

Tái hiện bằng cùng kịch bản tổng hợp trên source trong backup và source sửa:

| Kịch bản ba key chưa xác minh | Trước sửa | Sau sửa |
|---|---:|---:|
| Tổng slot với 30/key | 30 | 90 |
| Key khả dụng sau một key nhận quota phạm vi account | 0 | 2 |
| Trạng thái ba key | quota / READY / READY | quota / READY / READY |

Như vậy trước sửa hai key READY vẫn bị chặn bởi marker nhóm. Sau sửa trạng thái quota chỉ áp dụng đúng key/model, trừ khi có cả xác nhận thành viên nhóm và phạm vi account từ provider. Tên hiển thị không tham gia quyết định.

Bằng chứng: `artifacts/kira-false-quota/before-metadata.json`, `reproduction-before-after.json`, `profiles-before.json`. Không giữ response body lịch sử: chỉ có status/mã lỗi có cấu trúc đã được diagnostics ghi nhận; không suy diễn nội dung body chưa lưu.

## B. Bằng chứng API thật

Dùng đúng ba key đang cấu hình, đọc ciphertext qua SQLite chế độ chỉ đọc và giải mã trong bộ nhớ. Không đọc tài liệu dịch riêng. Model thử riêng là `longcat-2.5-preview-free`; không sửa lựa chọn model của người dùng.

Xác minh miễn phí bằng [catalog chính thức](https://kiraai.vn/api/v1/models) và [tài liệu Kira](https://kiraai.vn/documents/). Catalog có trường giá khác 0 nhưng `is_free=true`; code hiển thị bảng model trong tài liệu chính thức ưu tiên `is_free` và hiển thị “100% Free”. Vì vậy không dùng các trường giá chung để đổi sang model trả phí. Thông tin xác minh lưu trong `models.json`, `free-verification.json`.

| Key | HTTP thực tế | Mã lỗi | Kết luận |
|---|---:|---|---|
| Key 1 | 200 | — | Có quyền gọi model free đã thử |
| Key 2 | 402 | `pro_membership_required` | Model yêu cầu quyền Pro; không phải hết quota |
| Key 3 | 402 | `pro_membership_required` | Model yêu cầu quyền Pro; không phải hết quota |

HTTP 402 không đủ để kết luận quota. Parser mới ánh xạ `pro_membership_required` thành `permission`, giữ chặn đúng key/model. Không thử lại hai key bị từ chối quyền; không nạp tiền, thay gói hoặc đổi sang model trả phí.

Profile trước/sau cho thấy số dư VND cả ba tài khoản không đổi. Token dùng trong ngày của Key 1 tăng 4.106; không coi số request là số tiền. Không có POST cố tình gây 429/504.

## C. Các lượt thử và ngân sách

| Lượt | Key | Request | Lượt-dòng | Kết quả |
|---|---|---:|---:|---|
| 1 | Key 1 | 1 | 3 | HTTP 200, 7,371 giây; lỗi ghi báo cáo cục bộ làm mất phần kết quả đã parse, không gửi lại |
| 1 | Key 2 | 1 | 3 | HTTP 402 / thiếu quyền Pro |
| 1 | Key 3 | 1 | 3 | HTTP 402 / thiếu quyền Pro |
| 2 | Key 1 | 3 | 9 | Scheduler lưu 9/9 dòng, run `finished`, 3 HTTP đồng thời |
| 2 | Key 2 và 3 | 0 | 0 | Giữ trạng thái thiếu quyền model đã xác minh |
| 3 | — | 0 | 0 | Không dùng; lượt 2 đã đi qua đường tạo job, gửi batch, lưu kết quả và monitor |

**Tổng 6 request, 18/270 lượt-dòng, còn 252; retry thật: 0.** Key 1 dùng 12 lượt-dòng, Key 2 và Key 3 mỗi key 3. Mọi key đều dưới 30 lượt-dòng/lượt. Không có lượt thứ tư.

`live-budget.sqlite3` dùng `BEGIN IMMEDIATE` để kiểm tra và giữ ngân sách trước mỗi POST, kể cả nhiều worker/process. Reservation chưa rõ đã gửi vẫn tính vào trần. Ledger cố định ba hash key, giới hạn batch ≤3, round 1–3 và tổng 270. Guard chỉ cho endpoint chat chính thức, model free cố định và output ≤1.024 token; không retry ở tầng HTTP transport. Dừng probe key đã được xác nhận quota hoặc thiếu quyền. Lỗi ghi báo cáo ở request đầu không reset ledger; lần tiếp tục bỏ qua request đã gửi.

Bằng chứng chi tiết: `live-summary.json`, `live-round-1.json`, `live-round-2.json`, `profiles-after.json`. Database job thử hoàn toàn tách biệt dữ liệu người dùng.

## D. Thay đổi source

- `transcomic/kira_keys.py`: tách khai báo nhóm cũ khỏi nhóm có xác nhận; mặc định hiệu lực là từng key. Chọn nhóm qua UI lưu xác nhận rõ ràng. Khôi phục offline xóa marker nhóm mới theo phạm vi hiệu lực. Không suy luận quota chỉ từ 402 trong bước phục hồi trạng thái cũ.
- `transcomic/kira_pool.py`: health/concurrency/RPM/TPM/cooldown theo phạm vi đã xác nhận hoặc từng key; không dùng marker `shared` cũ làm khóa. Quota nhóm cần provider xác nhận phạm vi account. Quota key/model được giữ, reset có thời điểm được áp dụng khi refresh/restart; reset chưa rõ yêu cầu xác minh/khôi phục chủ động. Không tự gửi probe khi mở ứng dụng.
- `transcomic/providers.py`: 402 quota cần mã có cấu trúc; nhận diện riêng thiếu quyền Pro; 429 không có mã quota vẫn là giới hạn tạm thời. Giữ phân loại 401/403/404/5xx/timeout hiện có. Đọc Retry-After cho quota; không dò từ khóa message chung.
- `transcomic/ui/kira_api.py`, `transcomic/ui/kira_monitor.py`: nhãn quota/quyền rõ hơn; giải thích chưa xác định thì xử lý riêng. Danh sách key dùng trạng thái model của run hiện tại thay vì hiển thị quota model cũ. Khi hết key, phần thống kê vẫn có lý do từng key.
- Tests cũ về tài khoản chung được cập nhật fixture để **khai báo nhóm thật sự**, giữ nguyên các assert trần chung/cooldown và phục hồi. Không biến tài khoản chưa xác minh thành nhóm chung trong test mới.
- `tests/test_kira_false_quota.py`: regression mới và kiểm tra ngân sách nguyên tử. `scripts/probe_kira_false_quota.py`: probe có giới hạn, không được gọi bởi ứng dụng hoặc test offline.

Các thay đổi performance/recovery từ phiên trước được giữ. Không sửa dấu câu, mapping, TTS, version, export hay release trong nhiệm vụ này.

## E. Regression

Kết quả cuối cùng được ghi trong `artifacts/kira-false-quota/verification.json` và các XML tương ứng.

- Regression rộng 42 file: **804 PASS, 1 FAIL, 10 deselected**, 345,43 giây. Failure duy nhất là assert nhãn cũ `Hết quota`; chức năng đang hiển thị đúng nhãn mới. Giữ nguyên XML/log của lần chạy này, không ghi đè thành PASS.
- Sau cập nhật assert và bổ sung kiểm tra model đang chạy: **204 PASS, 1 deselected**, 86,24 giây (`acceptance-final.xml`). Bao gồm ca từng fail, recovery, grouping, provider và Gemini.
- Sau đồng bộ thêm trần trong Live Monitor chưa có run: **20 PASS, 1 deselected**, 16,56 giây (`ui-final.xml`), kiểm tra Light/Dark và các card còn lại không bị tạo lại khi một key đổi trạng thái.
- Nhóm regression mới độc lập: **25 PASS**, 2,27 giây (`focused-final.xml`). Có kiểm tra ledger qua restart, concurrent reservation không vượt 270 và từ chối round 4/key ngoài danh sách.
- AST của 13 file Python sửa/thêm hợp lệ; `git diff --check` trả 0; quét artifacts không phát hiện plaintext của ba key thật. Không cộng các số test chồng lặp thành số test độc lập.

Bao gồm: ba key khỏe/độc lập/tên giống nhau; 429 có/không Retry-After; quota, thiếu quyền, timeout, JSON lỗi và lỗi chưa rõ ở một key; marker quota nhóm cũ qua restart; model được chọn rõ ràng; nhóm có xác nhận; quota reset; giới hạn 30/key; budget không reset; recovery hai lượt và Gemini. GUI kiểm tra Light/Dark, cập nhật nhãn khi model hiện tại khác model đã bị quota.

Các bài lớn về load/tracemalloc/150 slot được loại khỏi lượt regression rộng để giữ tải nhẹ trên máy từng BSOD. Không chạy Windows Sandbox, GPU/CUDA, kiểm thử cập nhật thực tế, build hoặc release.

## F. Hiệu năng

Kịch bản MockTransport 121 dòng, batch ≤3, ba key độc lập: **41 request, phân phối 14/14/13**, giữ được **ít nhất 30 HTTP đồng thời**, mọi dòng lưu thành công. Test còn kiểm tra trần 30 slot/key, 90 tổng và nhóm đã xác nhận vẫn bị giới hạn 30 tổng. Đây là mô phỏng scheduler, không phải tốc độ server.

Lượt thật 2 có ba request Key 1 chồng thời gian, thời gian từng request khoảng 9,54–13,31 giây; peak 3. Không có bằng chứng ba key thật cùng dịch thành công vì hai key thiếu quyền model free này.

## G. Giới hạn

- Không chứng minh ba key đều có quyền dịch model đang thử: provider xác nhận ngược lại cho Key 2/3. Sửa grouping không cấp quyền Pro hoặc số dư trả phí.
- Không tự đổi model đang chọn. Nếu muốn dùng Key 2/3, cần chọn model mà tài khoản được phép dùng hoặc xử lý quyền ở Kira; nhiệm vụ này không thay gói.
- Round 1 Key 1 chỉ giữ được HTTP 200, không giữ bản dịch đã parse do lỗi báo cáo cục bộ. Round 2 xác minh lại đường đầy đủ với 9 bản dịch được lưu; không bịa kết quả round 1.
- Không tái tạo 429/504 thật; recovery được kiểm tra offline. Quota có reset được gỡ khi refresh sau hạn; trường hợp job đã dừng vì quota có thể cần người dùng Tiếp tục. Không tự gửi lại quota chưa rõ reset.
- Source sửa chưa đóng gói vào EXE; ứng dụng đang mở/bản cài cũ cần khởi động bằng source mới để dùng sửa lỗi. Không thay release public v1.1.0.

## H. Đánh giá

**PARTIAL — NEEDS VERIFICATION** đối với mục tiêu ba key thật cùng dịch. Đã sửa và chứng minh khóa quota lan nhầm; đã hoàn tất đường dịch thật với key có quyền. Hai key còn lại bị provider từ chối quyền model, không phải scheduler bỏ rảnh vô lý. Chưa phát hành.
