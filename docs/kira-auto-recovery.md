# Kira auto-recovery — báo cáo sửa lỗi, chưa phát hành

> Báo cáo lịch sử cho chính sách v1. Yêu cầu tiếp theo đã cấp quyền retry timeout/504 có giới hạn và hai lượt rà soát; xem [báo cáo mới](kira-performance-recovery.md). Không dùng phần “không tự retry uncertain” bên dưới để mô tả chính sách v2 hiện tại.

Ngày kiểm tra: 18/10/2026. Bản đang phát hành giữ nguyên **1.1.0**.
Mã nền: `ab650e5b9d44375096e9a126b497c96206480f83`.

## A. Nguyên nhân và bằng chứng

| Hiện tượng | Nguyên nhân xác minh trong mã trước khi sửa |
| --- | --- |
| Tự hiện “Tạm dừng người dùng” | Nhánh Kira dispatch gọi `_paused.set()` và ghi `user_paused` khi thiếu key khả dụng, network pause hoặc batch vượt TPM. Đây không phải thao tác Pause của người dùng. |
| Key mắc `UNKNOWN_ERROR` | Pool phân loại timeout/504/5xx không rõ kết quả và một số HTTP lỗi vào trạng thái không được chọn lại; network error còn giữ cờ `network_paused`. |
| 429 hoặc dòng lỗi không tự tiếp tục | Multi-Key đóng băng `auto_retries=0`, `allowed_retry` từ chối toàn bộ Multi-Key; dispatcher riêng chưa có hàng đợi phục hồi an toàn. Cooldown không giải quyết được batch đã thất bại. |
| Phải Khôi phục offline | Trạng thái key/scheduler giữ lỗi và không có đường phục hồi batch tự động. Khôi phục thủ công vô tình trở thành cách thoát các trạng thái này. |
| 121/121 vẫn cần can thiệp | Lỗi tổng hợp dùng trạng thái can thiệp cũ trước khi xét dữ liệu hoàn thành; thay đổi trạng thái chung còn có thể ghi lên file đã hoàn tất. |
| Dòng 105: `Duplicate or invalid line IDs/values` | **Chưa xác định được response cụ thể của dòng 105**. Validator dùng thông báo chung cho nhiều vi phạm. Không có response/batch lịch sử đủ để kết luận ID nào bị trùng hay sai. Hai bản dịch có nội dung giống nhau nhưng ID khác nhau vốn đã được chấp nhận; không phải bằng chứng lỗi. |

Đọc metadata của 8.559 sự kiện log hiện có, không đọc raw response, nội dung tài liệu hoặc credentials: có 18 sự kiện HTTP 504, 12 sự kiện 429, 12 sự kiện 402; có 5 sự kiện key `UNKNOWN_ERROR/http_504`, 4 sự kiện `UNKNOWN_ERROR/http_error`. Đây là **số sự kiện**, không phải số request duy nhất. Log không giữ bằng chứng pause hoặc cấu trúc response của dòng 105. Chi tiết: `artifacts/kira-auto-recovery/existing-log-summary.json`.

Trước sửa, nhóm kiểm thử tái hiện ban đầu cho kết quả **5 FAIL, 1 PASS**. Bản dịch giống nhau ở hai ID khác nhau là trường hợp PASS ngay từ trước sửa. Log: `before-tests.log` trong thư mục artifacts trên.

## B. Mã thay đổi

| Nhóm | File |
| --- | --- |
| Chính sách retry lưu bền, ngân sách | `transcomic/kira_recovery.py` mới; `retry.py`, `storage.py` |
| Scheduler, hàng đợi, nhiều file/ngôn ngữ | `kira_dispatch.py`, `translation.py`, `bulk.py` |
| Limiter, fairness, cooldown, phân loại key | `kira_pool.py`, `kira_keys.py` |
| Parser, HTTP, exact ID, prompt, punctuation | `providers.py`, `prompts.py`, `postprocess.py` |
| Bộ đếm monitor, khôi phục trạng thái | `kira_telemetry.py`, `kira_monitor_store.py` |
| Catalog và UI | `models.py`, `ui/kira_api.py`, `ui/kira_monitor.py`, `ui/main.py`, `ui/stage2.py` |
| Regression | `tests/test_kira_auto_recovery.py`, `test_kira_recovery_ui.py` mới; cập nhật `test_kira_multikey.py`, `test_kira_distribution.py`, `test_kira_live_monitor.py`, `test_kira_live_monitor_ui.py` |

Các trạng thái chờ `waiting_rate_limit`, `provider_recovering`, `retry_scheduled` tách khỏi `user_paused`. Hết ngân sách hoặc lỗi không thể phục hồi chuyển `needs_intervention` với lý do cụ thể. `finished`, `stopped`, `interrupted`, `unknown` tiếp tục giữ nghĩa riêng. Chỉ điều khiển Pause của người dùng đặt cờ user pause.

Key phân biệt READY, COOLDOWN, TEMPORARY_ERROR, INVALID, PERMISSION_DENIED, MODEL_UNAVAILABLE, QUOTA_EXHAUSTED, CREDENTIAL_ERROR và UNKNOWN_ERROR khi chưa đủ chẩn đoán. Permission/model block có phạm vi model. Quota đã xác minh có phạm vi account + model, không quay sang key cùng tài khoản để vượt quota. Các tài khoản được cấu hình độc lập vẫn có giới hạn riêng.

Parser chỉ nhận ánh xạ ID chính xác: phát hiện duplicate JSON keys/IDs, kiểu sai, thiếu/thừa ID, text rỗng, newline/control character và Unicode surrogate lỗi. Cho phép code fence và wrapper `data`/`result` đã biết; không đoán bằng thứ tự. Giữ phần hợp lệ của response; chỉ phần chưa đạt điều kiện mới được thử lại. Hai ID khác nhau có cùng text vẫn hợp lệ.

Prompt mới chỉ áp dụng cho lượt Kira Multi-Key mới; nêu rõ tập target IDs và giữ punctuation. Phiên cũ và prompt Gemini giữ phiên bản cũ; không viết lại dữ liệu đã lưu. Lịch sử request lỗi không bị biến thành request thành công chỉ để xóa cảnh báo.

## C. Chính sách tự động và giới hạn

| Loại lỗi | Hành vi |
| --- | --- |
| Chưa gửi; xác minh connect trước khi gửi body | Xếp lại có giới hạn, giữ key/model gốc. |
| HTTP 429 rate limit | Đọc Retry-After dạng số/ngày HTTP và header reset hợp lệ; chờ, giảm tốc và thử lại trong ngân sách. |
| Response đã nhận nhưng schema/ID/ngôn ngữ không hợp lệ | Lưu phần đã xác minh, thử lại **chỉ dòng lỗi**, giữ nguyên key/model và revision. |
| Timeout/504/408/5xx hoặc kết quả không rõ | **Không tự gửi lại request đó**. Giữ unknown; key có thể phục hồi để làm các batch chưa gửi. |
| 401; 403; 402/quota xác minh; model từ chối | Phân loại auth/permission/quota/model, dừng phạm vi không khả dụng; không retry vòng lặp, không tự đổi model. |
| Safety/content filter | Không tự retry. |

Mặc định cho lượt mới:

- Tối đa **2 request thử lại/batch**, tổng **30 request thử lại/lượt**; mỗi giá trị có thể chỉnh, đặt retry/budget bằng 0 để tắt.
- Với `N` batch ban đầu: trần tự tính `N + min(2N, 30)` request/lượt. Có thể đặt trần tổng request nhỏ hơn. Bộ đếm dùng reservation/attempt lưu bền, tính bảo thủ cả lượt đã chuẩn bị nhưng có thể chưa gửi.
- Retry backoff cơ sở 1 giây, tăng theo số attempt, có jitter; trần backoff cấu hình 30 giây. Retry-After lớn hơn được tôn trọng; nếu vượt thời gian chờ còn lại thì dừng thay vì gửi sớm.
- Tổng thời gian chờ phục hồi mặc định **300 giây**, tối đa **10 đợt phục hồi 429**. Bộ đếm chờ thực tế và thời gian chờ đã đặt trước đều được lưu. Chờ RPM thông thường và user pause không bị tính như lỗi phục hồi.
- Lỗi vận chuyển tạm thời có cooldown 2/4/8/16/30 giây. 429 giảm concurrency tài khoản và áp dụng pacing chung, không hủy tùy tiện request đang chạy. Sau chuỗi thành công và khoảng yên lỗi, tăng capacity từng bước.
- Limiter sliding window dùng chung cho workers và các key cùng account scope, giữ RPM/TPM/concurrency; mặc định account concurrency 30, RPM 60, TPM 1.000.000. Đây là cấu hình bảo thủ, **không khẳng định là hạn mức chính thức**; không mặc định 100 RPM. Header hạn mức quan sát được chỉ hạ trần cấu hình.
- Retry chỉ nhận key/model gốc. Batch đang inflight có attempt UUID/revision fence; không có cơ chế lease hết hạn tự gửi lại request không rõ kết quả. Người dùng sửa dòng thì response cũ không được ghi đè.
- Bước chọn batch bỏ qua tạm thời retry đang bị key gốc chặn để các batch khác đủ điều kiện vẫn nhận việc, kể cả retry của key khác trong cùng file. Không đổi quyền sở hữu của retry. Regression xác minh key thứ hai phục hồi trước khi key thứ nhất hết cooldown.
- Hạn mức đóng băng theo lượt và giữ qua restart; phiên cũ không tự được cấp thêm retry. Sau crash chỉ khôi phục trạng thái rồi chờ người dùng xác nhận, không tự gửi mạng.
- Key UNKNOWN_ERROR cũ chỉ được phân loại lại khi có attempt khớp làm bằng chứng; không tự bật key đã tắt hoặc reset lỗi auth/quota. Hết cooldown thông thường tự trở về READY.

**Giới hạn chi phí:** trần request và output token giới hạn mức sử dụng, không phải bảo đảm số tiền VND do provider thu. Chưa có bảng giá áp dụng cho từng tài khoản/reasoning được xác minh để cam kết trần tiền. Retry format có thể tốn thêm tiền/token. UI nêu rõ điều này và cho tắt retry; không tự chuyển free sang paid. Không gửi live POST trong lượt này vì chưa xác minh được điều kiện chi phí an toàn.

## D. Model Kira

Nguồn: GET công khai [catalog chính thức Kira](https://kiraai.vn/api/v1/models), HTTP 200; snapshot `artifacts/kira-auto-recovery/official-models.json`.

| Exact API ID | Catalog | Trường `is_free` | Quyền gọi bằng key / thanh toán thực tế |
| --- | --- | --- | --- |
| `beam-free` | active, đã thêm | true | Chưa xác minh bằng POST |
| `deepseek-v4.1-flash-free` | active, đã thêm | true | Chưa xác minh bằng POST |
| `mimo-v2.6-flash-free` | active, đã thêm riêng với model paid | true | Chưa xác minh bằng POST |
| `longcat-2.5-preview-free` | active, đã thêm theo ID người dùng xác nhận | true | Chưa xác minh bằng POST |

`longcat-2.5-preview-fre` không có trong catalog; không tạo alias cho ID sai. Giữ các model cũ và lựa chọn đã lưu. Mock 403 kiểm tra từng exact ID không fallback.

Catalog đồng thời chứa giá input/output khác 0: Beam 5.000/13.000, ba model còn lại 10.000/20.000 trong các trường `price_input_vnd`/`price_output_vnd`. Chưa xác minh đơn vị/điều kiện miễn phí/billing/reasoning nên không suy ra “chắc chắn không mất tiền” từ hậu tố tên hoặc cờ free.

## E. Kiểm thử

Các log/XML ở `artifacts/kira-auto-recovery/`. Tất cả dữ liệu kiểm thử tổng hợp và HTTP MockTransport; bật guard từ chối transport mạng thật. GUI dùng Qt offscreen/software.

- Nhóm Kira tập trung trước lượt tổng hợp cuối: **141 PASS, 9 deselected** (`final-kira-focused.xml`).
- Nhóm UI/monitor/retry trước lượt tổng hợp cuối: **45 PASS** (`gui-focused.log`).
- Nhóm regression tài liệu/Gemini/editor/export/persistence/TTS/updater trước lượt tổng hợp cuối: **276 PASS** (`offline-regression.xml`).
- Lượt tổng hợp đầu: **161 PASS, 1 FAIL, 9 deselected**, dừng ở `test_monitor_refresh_does_not_stall_150_http_slots` vì chưa đạt 150 request sau 15 giây. Giữ nguyên log/XML `acceptance-regression.*`; không ghi đè kết quả FAIL này.
- Đọc SQLite kiểm thử ở chế độ chỉ đọc sau FAIL: **139 attempt chuẩn bị**, phân phối **27/28/28/28/28** cho 5 key READY; health limit 150, spacing 0, next_send 0, không có strike. Không có bằng chứng key bị bỏ rơi hoặc limiter chặn ở thời điểm lưu. **Chưa xác định hết nguyên nhân không đạt thời hạn**; không tuyên bố performance 150 slot đã đạt. Fixture sau assertion lỗi đóng DB khi còn worker nên sinh thêm cảnh báo thread; không xem cảnh báo đó là bằng chứng nguyên nhân fail ban đầu.
- Bổ sung GUI mock nhỏ **8 slot, 2 key, 3 file/36 dòng** để kiểm tra refresh khi HTTP đang chờ, chia 4 slot/key, không gửi thêm do refresh và hoàn tất không trùng request. Có cleanup chờ worker kết thúc trước khi đóng DB.
- Kết quả tổng hợp nhóm nhẹ trên mã cuối cùng: xem phần “Nghiệm thu cuối” bên dưới và `light-acceptance-regression.xml`.
- Nhóm nhẹ loại **10 trường hợp tải lớn**: 9 mock load đã không chạy và 1 bài 150 slot đã FAIL ở lượt trước, không chạy lại vì ổn định máy sau BSOD. Không tuyên bố toàn bộ stress/full suite đã PASS.
- Live Kira: **PARTIAL — không gửi POST**, chỉ GET catalog vì chưa xác minh giá để bảo đảm trần tiền.

Bao phủ: 429 rồi thành công, 429 liên tiếp, Retry-After, quota/auth/model/permission, timeout/504/5xx không gửi lại, lỗi connect chưa gửi, lỗi chuẩn bị attempt không rò slot; giới hạn per-batch/global/request/wait; fairness/rate limit theo tài khoản; nhiều worker/nhiều file; partial repair/121 dòng; completion và file tốt không bị file lỗi ghi trạng thái; nguồn sửa trong lúc chờ response; crash/restart và bộ đếm; Stop/Pause trong cooldown; parser fixtures; punctuation; che credentials trong header lỗi; dropdown exact IDs và Light/Dark.

Regression liên quan gồm Kira, Gemini, TXT/DOCX, storage, scheduler, bulk, sai ngôn ngữ, editor/undo, export và retry. TTS/updater chỉ chạy kiểm thử offline liên quan; không chạy inference CUDA, Sandbox, installer hay cập nhật GUI thực tế.

## F. Trải nghiệm tự động

Trong mock nhiều worker/nhiều file và trường hợp cuối còn một dòng lỗi, job tự chờ rồi dịch lại phần lỗi và hoàn tất trong ngân sách, **không cần Pause/Resume/Khôi phục offline/Dịch lại thủ công**. File hoàn tất vẫn hoàn tất khi file khác lỗi. Monitor giữ lịch sử request thất bại, cập nhật số dòng lỗi hiện tại khi dòng được lưu thành công; trạng thái chờ và lý do can thiệp không che bằng user pause.

Timeout/504 còn unknown hoặc vượt ngân sách vẫn cần người dùng quyết định; không hiển thị hoàn tất giả. Đây là ranh giới phục hồi an toàn, không phải mọi lỗi đều được gửi lại.

## G. Sẵn sàng phát hành

**PARTIAL — NEEDS FURTHER VERIFICATION.** Mã và regression offline đã được triển khai; live billing/access chưa kiểm chứng, bài thời hạn 150 slot chưa đạt và chưa điều tra hết trên máy an toàn hơn. Chưa phát hành. Có thể đề xuất hotfix **1.1.1** sau khi người dùng chấp nhận phạm vi kiểm chứng còn thiếu; chưa thay version.

Không commit/push/build/publish, không ghi đè release 1.1.0, installer, dữ liệu người dùng hoặc key. Không chạy Windows Sandbox/CUDA; kiểm tra nhẹ cho thấy CmService vẫn Stopped. GUI update Sandbox còn dang dở trước đây vẫn **CHƯA HOÀN TẤT**; nhiệm vụ Kira này không thay kết luận đó.

## Nghiệm thu cuối

1. **463 PASS, 10 deselected, 125,16 giây**: `light-acceptance-regression.xml/.log`. Bao gồm GUI 8 slot và regression liên quan đã liệt kê. Lượt này hoàn tất trước điều chỉnh cuối ở bước chọn retry bị key gốc chặn.
2. Sau điều chỉnh đó và bổ sung test same-file/pinned-key, chạy lại toàn bộ nhóm Kira tập trung cùng GUI 8 slot: **144 PASS, 9 deselected, 36,29 giây**, `final-dispatch-regression.xml/.log`. Không cộng hai số PASS vì các bộ test chồng lặp.
3. AST kiểm tra **24 file Python PASS**; `git diff --check` theo cấu hình Git hiện có **exit 0**. Metadata: `source-checks.json`.
4. Nhóm nhẹ và nhóm tập trung cuối không có FAIL. Lượt đầu có FAIL performance 150 slot vẫn được giữ và chưa được giải quyết/kiểm chứng lại; không gọi toàn bộ suite PASS.
5. HEAD vẫn `ab650e5b9d44375096e9a126b497c96206480f83`, version 1.1.0; toàn bộ thay đổi chưa commit. Không có POST Kira thật hoặc dữ liệu tài liệu riêng được dùng để kiểm thử.

Kết luận giữ **PARTIAL — NEEDS FURTHER VERIFICATION**, chưa đủ để tuyên bố đã nghiệm thu live hoặc performance 150 slot.
