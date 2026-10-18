# Kira performance & full automatic recovery — source chưa phát hành

Ngày: 18/10/2026. Giữ phiên bản **1.1.0**, branch `main`, HEAD nền `ab650e5b9d44375096e9a126b497c96206480f83`.

Yêu cầu mới cho phép mặc định gửi lại request timeout/504 có rủi ro token trùng trong giới hạn. Chính sách bên dưới thay phần “không tự retry uncertain” của báo cáo [lượt sửa trước](kira-auto-recovery.md). Không tạo checkbox mới cho quyền này.

## A. Nguyên nhân gốc có bằng chứng

1. **Bài 150 slot:** A/B trên cùng source trước tối ưu mới, cùng 10 file/600 dòng, 5 key, account cap 150, MockTransport và giới hạn 15 giây: vòng chờ test dùng `QTest.qWait(10)` đạt **111 slot/15,008 giây** khi bật profile; đổi riêng vòng chờ sang `processEvents()` + `time.sleep(.01)` đạt **150 slot/1,266 giây**. Không tăng timeout và không tắt limiter. Profile của lần chậm có `qWait` 12,845 giây self time. Nút thắt của ca này nằm ở vòng chờ GUI test gây starvation cho Python worker; không có bằng chứng scheduler giới hạn chỉ một batch. Hai profile JSON được giữ riêng trong artifacts.
2. **Chi phí dispatch:** baseline 205 request/615 dòng có hơn **22.000 lệnh SQLite** (1 key, 30 worker, profile), cùng nhiều transaction ghi metadata rời nhau. Đã gộp cập nhật metadata có cùng ranh giới an toàn vào transaction sẵn có; đọc cài đặt key theo lô. Không đổi WAL/synchronous, không bỏ commit attempt trước khi gửi HTTP.
3. **Cooldown bị khuếch đại:** các response 5xx/timeout cùng đợt in-flight tăng `strikes` riêng từng request, đẩy chờ lên 30 giây. Kịch bản 5 DOCX đã không drain trong 25 giây trước sửa. Hiện một đợt cooldown đang áp dụng không bị response cùng cohort cộng dồn backoff; không rút ngắn Retry-After đã có. Unit test 30 lease lỗi xác minh `strikes=1`, cooldown 2 giây ở đợt đầu.
4. **Hết ngân sách vẫn chờ RPM:** dispatcher từng xin limiter reservation trước khi `prepare_attempt` từ chối ngân sách. Thêm preflight chỉ đọc trước limiter; kiểm tra nguyên tử tại `prepare_attempt` vẫn giữ. Test 121 dòng, request budget 1, RPM 1 xác minh dừng hữu hạn thay vì chờ phút tiếp theo cho request không được phép gửi.
5. **Timeout/504 không retry trước đây:** đây là chính sách an toàn đã đóng băng của phiên trước, không phải server chứng minh chưa xử lý. Phiên này thay bằng quyền rủi ro người dùng vừa cấp, vẫn giữ lịch sử attempt UNKNOWN và giới hạn gửi lại.
6. **JSON/dòng cuối còn lỗi:** dispatcher trước chưa có hai lượt rà soát toàn job sau mọi ngôn ngữ; kết thúc một phase có thể chặn ngôn ngữ/file phía sau. Thêm workflow main → review 1 → review 2, dùng lại cùng batch IDs, key/model và ngân sách.
7. **Phải thêm dấu cách mới xuất được:** đã tái hiện bằng test, không cần phỏng đoán cache GUI. `validate_snapshot` dùng điều kiện revision `> original + 1` cho lỗi response không gắn line ID (ví dụ extra ID). Dòng đã được chấp nhận đúng ID ở revision `+1` vẫn bị cảnh báo; thêm dấu cách tăng lên `+2` nên cảnh báo biến mất. Nay lưu bằng chứng source/translation revision khi chấp nhận ánh xạ, kiểm tra dữ liệu hiện tại và bỏ qua bằng chứng response cũ đã được thay thế. Không thêm dấu cách tự động.
8. **Completion:** phiên mới xét dữ liệu đã lưu + structural report + pending/inflight + attempt chưa settled; lịch sử lỗi không tự chặn một file có dữ liệu hiện tại hợp lệ. File còn lỗi không được đánh dấu hoàn tất.

Không có raw response đủ để kết luận chính xác lỗi của từng dòng trong tài liệu thật cũ. Các kết luận trên dựa vào code, fixture và log mock được lưu; không coi mock là bằng chứng Kira thật đã hoạt động tương tự.

## B. File và ranh giới thay đổi

| Thành phần | File |
| --- | --- |
| Workflow hai lượt rà soát | `transcomic/kira_workflow.py` mới, `translation.py` |
| Dispatch/attempt/risk/queue fairness | `kira_dispatch.py`, `kira_recovery.py`, `retry.py` |
| Limiter/key/cooldown | `kira_pool.py`, `kira_keys.py` |
| Ngân sách/persistence/proof | `storage.py` (schema 9, migration thêm cột; không xóa bảng dữ liệu) |
| Kiểm tra cấu trúc/hoàn thành | `line_structure.py`, `bulk.py` |
| Monitor/UI trạng thái và cấu hình | `kira_telemetry.py`, `kira_monitor_store.py`, `ui/kira_monitor.py`, `ui/kira_api.py`, `ui/main.py`, `ui/stage2.py` |
| Benchmark tái lập | `scripts/benchmark_kira_recovery.py` mới |
| Tests | `test_kira_full_recovery.py` mới, các regression Kira hiện có, `test_line_structure.py`, các fixture migration `test_storage.py`/`test_final_workflow.py` |

Giữ nguyên các sửa catalog/parser/prompt của lượt trước. Không sửa TTS, hai worker, tách audio, version, release scripts, số dòng/thứ tự hay dấu chấm trong bản dịch. Không reset repo, không commit/push/build/publish.

## C. Hiệu năng mock

Mỗi điểm: 5 file × 123 dòng = 615 dòng, 205 request, độ trễ mock đặt 30 ms, cùng script và bật cProfile. RPM/TPM được cấu hình cao **chỉ trong fixture**, vẫn qua limiter; không dùng request thật để benchmark.

| Tổng worker cho phép | Key | Baseline (giây) | Sau sửa (giây) | Peak HTTP trước → sau |
| ---: | ---: | ---: | ---: | ---: |
| 1 | 1 | 11,750 | 10,925 | 1 → 1 |
| 5 | 1 | 3,765 | 2,516 | 5 → 5 |
| 10 | 1 | 3,589 | 2,955 | 7 → 9 |
| 20 | 1 | 3,314 | 2,569 | 7 → 9 |
| 30 | 1 | 3,185 | 2,517 | 8 → 9 |
| 1 | 3 | 11,483 | 11,185 | 1 → 1 |
| 5 | 3 | 3,498 | 2,752 | 5 → 5 |
| 10 | 3 | 3,601 | 2,708 | 7 → 8 |
| 20 | 3 | 3,472 | 2,538 | 7 → 9 |
| 30 | 3 | 3,395 | 3,020 | 7 → 9 |

Đây là quan sát từng lượt chạy, không phải cam kết tốc độ Kira hay phép đo thống kê nhiều lần. Profile có overhead; với response mock rất nhanh, CPU/SQLite chiếm đáng kể nên peak thấp hơn số worker cho phép không đồng nghĩa xử lý tuần tự. Kịch bản giữ request in-flight xác minh **đạt 30 HTTP đồng thời**, và bài GUI giữ request xác minh 150 slot ở cấu hình tương ứng. Không giữ Store/monitor/reservation lock trong lúc gọi/await HTTP.

Ví dụ 30 worker/3 key: throughput mock 181,17 → 203,67 dòng/giây; effective RPM trung bình 3.623,47 → 4.073,40. Phân phối 205 request là 68/68/69, không có key rảnh vô lý. Không áp dụng RPM mock này cho tài khoản thật. Cấu hình thật mặc định vẫn 60 RPM/account scope, concurrency/account 30, TPM 1.000.000 và các giới hạn riêng đã cấu hình.

Artifacts baseline/after giữ latency HTTP đo được, dispatch latency, peak active, request/key, state và remaining. Benchmark chẩn đoán bổ sung ghi thời gian chờ/giữ SQLite lock và wait reasons. Live Monitor hiển thị in-flight, queue, RPM trung bình, key/cooldown và phase review. Không gán số đo mutex/scheduler idle của mock thành độ trễ server Kira thật.

Lượt chẩn đoán lock riêng trên source cuối (không trộn vào matrix so sánh): 30 worker/3 key, 2,933 giây; worker chờ SQLite lock tổng **10,34 ms**, một lần chờ lâu nhất **0,0794 ms**, giữ lock cộng dồn **2,258 giây** qua nhiều scope nhỏ. Không có wait reason của limiter/key trong fixture khỏe này. Assert tại HTTP handler xác minh không giữ Store, monitor hoặc reservation lock trong lúc gọi HTTP. Tổng hold time không phải một critical section dài liên tục. Bài GUI source cuối đạt **150 slot/1,022 giây**, vẫn giới hạn 15 giây (`final-gui.json`).

Chạy lại matrix: `python -m scripts.benchmark_kira_recovery --workers 1 5 10 20 30 --keys 1 3 --files 5 --lines 123 --delay .03 --profile --output <file.json>`.

## D. Chính sách retry và hai lượt rà soát

- Lượt mới đóng băng `kira_recovery_version=2`; quyền gửi lại uncertain mặc định đã được người dùng cấp. **Không có checkbox bật quyền này**.
- 429 giữ Retry-After, limiter dùng chung theo account scope, pacing và tự tiếp tục. Có thể retry một lần trong main; các phần lỗi còn lại đi qua review, không cấp ngân sách riêng.
- Timeout/504/408/5xx/kết nối chưa rõ kết quả: giữ attempt cũ UNKNOWN, đánh dấu nguy cơ token trùng, xếp phần chưa thành công vào review. **Tối đa hai attempt gửi lại trên cùng batch gốc trong cả job**, kể cả các retry trước đó và sau restart. Kể cả đặt generic retry limit >2, lineage uncertain vẫn không quá attempt số 3.
- JSON/schema/ID/ngôn ngữ lỗi: giữ các ánh xạ chắc chắn, chỉ thử lại phần lỗi. Không đoán theo thứ tự, không đổi key/model. Hai text giống nhau ở ID khác nhau hợp lệ.
- Sau nhiều response malformed, có thể giảm còn 1 dòng/request. Vẫn cùng batch gốc/attempt counter. Nếu ngân sách cho phép, xử lý các phần còn lại trong cùng review; nếu không đủ, giữ lỗi. Không dịch lại phần đã lưu thành công.
- Main đi qua toàn bộ file và ngôn ngữ trước review 1. Review 2 chỉ chạy nếu còn dòng có thể thử lại. Mỗi review dùng lại giới hạn chung, không reset khi chuyển phase/queue/language.
- Dispatcher không ghi parent run COMPLETED ở giữa các phase/ngôn ngữ. Resume một phần không hoàn tất parent run hoặc language còn file khác chưa xong. Stop tại lần commit cuối vẫn giữ run/monitor STOPPED, không cấp quyền kích hoạt pipeline tiếp theo dù bản dịch đã đủ.
- Mặc định generic retry 2/batch, global retry 30/lượt; request bound `N + min(N × retry_limit, global_retry_budget)`. Có thể tắt retry hoặc hạ trần request/token.
- Token budget là reservation bảo thủ: UTF-8 request estimate + output max + overhead; trần tự tính hữu hạn từ request allowance × TPM cấu hình, lưu cố định. Usage provider báo lớn hơn estimate được cộng bảo thủ và chặn request tiếp theo nếu vượt allowance. Không thể thu hồi token của request đã gửi hoặc bảo đảm số tiền provider tính khi billing chưa được xác minh.
- Backoff exponential có jitter, giữ các trần chờ 300 giây/10 đợt phục hồi 429 mặc định. Cooldown không chiếm slot HTTP. Một đợt lỗi in-flight không khuếch đại strikes nhiều lần.
- Attempt UUID, trạng thái inflight, unique attempt number và revision fence ngăn hai worker retry cùng batch tại một thời điểm; response cũ không ghi đè revision mới. Không giả định Kira có idempotency API chưa xác minh: **có thể bị tính token trùng ở server**.
- Stop/Pause không cho gửi request mới. Restart chỉ đọc/khôi phục trạng thái; chỉ sau Start/Resume rõ ràng mới xử lý tiếp. Bộ đếm attempt, retry, token, chờ và phase giữ nguyên.
- Resume từ UI có thể nâng chính sách v1 lên v2 theo quyền mới, giữ mọi trần và bộ đếm cũ; không cấp thêm request. Chi phí token lịch sử chưa có reservation được dự phòng bảo thủ. Snapshot đã tắt retry vẫn tắt; snapshot thiếu allowance hữu hạn không được tự cấp quyền mới.
- 401/403/quota/model/safety: dừng đúng phạm vi, không retry vô hạn, không chọn model trả phí hoặc key ngoài phạm vi đã được cho phép.

## E. Xác minh cấu trúc và export

Mỗi export đọc snapshot hiện tại rồi kiểm tra snapshot checksum, số vị trí, stable IDs/owner, thứ tự, line endings, DOCX locators/unit mapping và nội dung single-line. Bằng chứng chấp nhận theo cặp revision giải quyết cảnh báo response cũ; không bỏ qua sai ID/số lượng/thứ tự thực tế.

Đối với dữ liệu trước migration, chỉ dựng bằng chứng đọc từ `api_text_versions.accepted` phù hợp nội dung hiện tại và source revision; không sửa bản dịch hoặc undo history. Kiểm tra lại sau restart, edit, retry và batch export không cần thêm dấu cách.

Kịch bản 5 DOCX xác minh đủ 121 dòng/file, lưu hợp lệ và xuất đủ 5 file. Chưa xây pipeline auto-export → TTS; chỉ `finished`/COMPLETED qua kiểm tra cuối mới là điều kiện cho pipeline tương lai. `completed_with_errors`, `blocked`, waiting, user pause và stopped không được coi là hoàn tất.

## F. Kiểm thử và bằng chứng

Tất cả ở `artifacts/kira-performance-recovery/`; dữ liệu tự tạo. HTTP dùng MockTransport, regression bật guard từ chối network transport thật; GUI offscreen/software.

- Trước sửa: **7 FAIL** tái hiện timeout/5xx không phục hồi, thiếu review toàn job và stale structural warning.
- Sau sửa đầu: **48 PASS** nhóm recovery + line structure.
- Scenario tập trung: **4 PASS** gồm 5 DOCX/605 dòng/30 HTTP, chia malformed thành single-line, giữ dấu chấm và cohort cooldown. XML `scenario-fixed.xml`.
- Regression đầy đủ trong phạm vi dịch và kết quả cuối: xem phần nghiệm thu bên dưới; manifest file tests ở `offline-files.json`.
- Bộ cũ có 9 ca load/tracemalloc lớn được loại khỏi lượt regression để không chạy tải không cần thiết trên máy từng BSOD. Có matrix bounded, 30 worker và bài 150 slot được kiểm tra riêng. Không tuyên bố toàn bộ mọi bài stress của repo đã chạy.
- Không chạy test TTS/CUDA/Sandbox/updater/release không liên quan. Version/release/installer không thay đổi.
- **Live Kira: PARTIAL / không gửi POST.** Chưa xác minh được billing/ràng buộc free để bảo đảm trần chi phí; dùng mock để chứng minh logic, không dùng tài liệu riêng hoặc thử gây 429 thật.

## G. Giới hạn còn lại

Server có thể tính tiền cho request timeout cũ lẫn request gửi lại; quyền mới chấp nhận rủi ro đó, local fencing không đồng nghĩa server deduplication. Hết retry/request/token/wait budget hoặc lỗi quyền/quota không thể tự xử lý sẽ kết thúc rõ ràng, giữ bản dịch đã lưu. Tốc độ Kira thật và quyền/billing model chưa được đo bằng live test trong lượt này.

## H. Đánh giá

**PARTIAL — NEEDS VERIFICATION** cho phần live billing/access/tốc độ thật. Source chưa phát hành. Người dùng quyết định riêng về hotfix 1.1.1; không đổi version hoặc gọi Auto Release.

## Nghiệm thu cuối

- Regression rộng trong phạm vi dịch: **780 PASS, 9 deselected, 364,25 giây**, `offline-final.xml/.log`. Manifest đã loại các bộ TTS/CUDA/Sandbox/updater/release không liên quan.
- Sau chốt cuối cho parent/language/Stop và đồng bộ bộ đếm success: **57 PASS, 31,33 giây**, `acceptance-focused.xml/.log`. Bao gồm hai lượt review, đa ngôn ngữ, subset resume, Stop tại commit cuối, 5 DOCX/605 dòng/30 HTTP, normalization telemetry và bài GUI 150 slot. Không cộng số test chồng lặp với lượt regression rộng.
- Ba FAIL ở lượt rộng trước được giữ trong `offline-complete.*`: fixture Pause tự pause lại khi Resume (đã sửa thành one-shot); expectation telemetry chưa tính retry normalization; migration constraint chưa giữ cột `reserved_tokens` (đã sửa và test bảo toàn 12.345 token cùng trace/FK). Lượt rộng sau đó PASS; không xóa log FAIL.
- Matrix benchmark cuối: `baseline.json` → `after-final.json`; chẩn đoán lock ở `lock-diagnostics.json`, GUI ở `final-gui.json`. Không tăng mốc 15 giây để tạo PASS.
- Không gửi POST Kira thật, không dùng tài liệu riêng, không đổi version/HEAD, không commit/push/build/publish. CmService vẫn Stopped; không có tiến trình Sandbox/vmmem do lượt này khởi chạy.

Các test vượt ngân sách hoặc lỗi không phục hồi xác minh trạng thái có lỗi/blocked, không tạo Completed giả. Không tự động xuất hoặc kích hoạt TTS trong nhiệm vụ này; chỉ hoàn thiện điều kiện dữ liệu đủ để xuất an toàn.
