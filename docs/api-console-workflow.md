# API, Console, lịch sử và retry — 13/10/2026

## Thay đổi và nguyên nhân có bằng chứng

1. **Nhập lại hiện bản dịch cũ:** code cũ dedup theo path/hash. Đã bỏ unique index và nhánh dùng lại document; mỗi import có document/line UUID riêng, cột dịch trống. Source identity chỉ là metadata. Startup vẫn trống; mở lịch sử là thao tác riêng.
2. **Lịch sử:** có entry cho từng job hoặc import chưa dịch, file/thời gian/ngôn ngữ/model/tiến độ/trạng thái và checkbox. Xóa một/nhiều có xác nhận; chặn running/pausing/stopping/inflight. Transaction xóa request attempts, batches, jobs và dữ liệu workspace khi không còn job tham chiếu; kiểm tra foreign keys. Không xóa file nguồn/xuất/key/cấu hình chung. Giữ snapshot/lines khi job khác vẫn dùng.
3. **Console:** sidebar, lọc mức độ/provider/model/job/import, tìm metadata, chi tiết, copy sự kiện/báo cáo, xuất JSON/TXT, ẩn hoặc dọn log sau xác nhận. Chỉ tự cuộn khi người dùng ở cuối. Writer riêng, rotation khoảng 2MB × 4 file, 2.000 sự kiện trong RAM, queue giới hạn 5.000. Có báo log health; log async có thể mất các sự kiện chưa kịp ghi khi hệ điều hành crash, nhưng attempt được commit SQLite trước dispatch.
4. **Trace:** timestamp UTC, provider/model/import/job/original batch/attempt UUID+số lần, correlation ID, ID/ordinal dòng; queue wait/HTTP/parse/DB/GUI riêng. Quan sát body gửi bằng HTTPX transport trace khi hỗ trợ, headers trước full body. Mock không hỗ trợ trace thì không khẳng định đã gửi xong. Việc body gửi xong không chứng minh server đã thực thi. GUI acknowledgment ghi import thật và import đang hiển thị; lỗi refresh được ghi riêng.
5. **Bảo mật:** allowlist metadata và event description cố định; không log response body, truyện, toàn prompt, key, Authorization, cookie hoặc exception chứa dữ liệu. Key được đăng ký để che cả correlation ID nếu server echo lại. JSON/text export dùng cùng metadata đã che. Database thử chứa snapshot/kết quả nội bộ; không dùng database đó làm báo cáo để chia sẻ.
6. **HTTP 504:** phân loại response status 504 tách client timeout/network/parser/SQLite. Không tăng timeout hoặc thêm backoff để che nguyên nhân. Dùng một AsyncClient/job, connection pool bằng concurrency; không giữ SQLite transaction trong lúc chờ network. Mặc định production không đặt output cap/reasoning flag khi chưa có tài liệu xác nhận.
7. **Retry:** mặc định bật cho job mới, setting lưu và snapshot vào job; job cũ migration có retry tắt. Chỉ actual HTTP504, đúng attempt2, không attempt3. Unique `(original_batch_id, attempt_number)` và durable reservation trước HTTP. Job max_requests tính cả retry; tắt policy/budget/stop/pause/revision đổi thì chặn. Attempt đã chuẩn bị/gửi khi crash trở thành unknown, không replay lúc startup. Client timeout/401/403/429/parser/DB không tự retry. User chủ động dịch lại tạo job riêng và xác nhận chi phí.
8. **Race:** kết quả phải đúng attempt mới nhất và source/translation revision. Sửa thủ công hoặc Replace thắng response trễ; retry chỉ lấy các dòng chưa bị sửa sau attempt1. Saved log phân biệt ID API chấp nhận và ID thực sự ghi được. Dữ liệu của import cũ không cập nhật sang import mới. DB lỗi không ghi log thành công và không retry API.
9. **Dịch lại tất cả dòng lỗi:** lấy error/unknown trong toàn import đang mở, độc lập bộ lọc, không lấy punctuation-only. Xác nhận count/model/languages/concurrency/batches/token risk. Dùng cùng queue 1–30 workers/max3 dòng, kiểm tra concurrency thật bằng mock. Không thay model âm thầm; nhiều cấu hình gốc yêu cầu chọn từng nhóm.
10. **Chưa dịch và tiến độ:** `translation_source_revision` xác định bản dịch còn khớp nguồn, độc lập trạng thái request mới nhất. Lỗi/unknown/processing/stale thiếu bản dùng được xuất hiện trong Chưa dịch; blanks/symbols và bản cũ hợp lệ không xuất hiện. Export dùng được bản cũ hợp lệ dù retry lỗi. Tiến độ tài liệu theo bản dùng được; tiến độ lượt theo kết quả lượt đó, nhãn còn thiếu/lỗi/retry/pause/stop/interrupted, không báo cả tài liệu hoàn tất khi chỉ dịch lại một nhóm.

## Đợt API thật duy nhất

User cấp tối đa **1.000đ**, tối đa **3 request**, mỗi model đúng một. Đã dùng key DPAPI qua SQLite **read-only**, không migrate/reset database người dùng và không in key. Không gọi Gemini, model khác, authenticated model discovery, retry hoặc fallback. Chạy tuần tự, concurrency1, timeoutread90/connect10/write30/pool10, `max_tokens=512`.

File `D:\word 50 cach\7-8.docx`: 125 units, SHA256 `1103b346f781c4cc9f1aca7ee787b8421b12749e1ff28d96524a59645a288696`; hash/bytes giữ nguyên. Mỗi request dịch **dòng26** (“nói a đi”), hai dòng nguồn tham chiếu25/27, UUID mục tiêu riêng. Ledger ghi UUID và reservation trước từng call, khóa exclusive toàn đợt; rerun không gửi thêm. Input JSON toàn request 1.550–1.559 ký tự, dưới4.000; không gửi toàn file.

| Model | Giây tới kết quả/lỗi | HTTP | ID hợp lệ / lưu DB | Input / output / tổng token | Ước tính đ |
| --- | ---: | ---: | ---: | ---: | ---: |
| coding-mimo-v2.6-flash | 9,348 | 200 | 1 / 1 | 430 / 149 / 579 | 1,32496 |
| deepseek-v4.1-flash | 4,173 | 200 | 1 / 1 | 450 / 411 / 861 | 5,71662 |
| glm-5.3-flash | 11,585 | 200 | 0 / 0 | 413 / 564 / 977 | 6,25989 |

**Tổng: 3 request, 1.293 input + 1.124 output = 2.417 token; ước tính 13,30147đ** theo usage và giá sale công khai. Đây không phải xác nhận số dư đã bị trừ. Giá công khai đọc trực tiếp trước đợt thử:

| Model | Input sale / output sale, đ mỗi1M token | Giá gốc input / output dùng ước tính bảo thủ |
| --- | ---: | ---: |
| [Coding MiMo](https://kiraai.vn/models/coding-mimo-v2.6-flash/) | 1.820 / 3.640 | 3.640 / 7.280 |
| [DeepSeek](https://kiraai.vn/models/deepseek-v4.1-flash/) | 2.730 / 10.920 | 3.900 / 15.600 |
| [GLM](https://kiraai.vn/models/glm-5.3-flash/) | 2.730 / 9.100 | 3.900 / 13.000 |

Trước gửi, giới hạn input token ước tính bảo thủ bằng UTF8 bytes+128 và output512 cho tổng38,1836đ ở giá gốc, **không khẳng định là upper bound tuyệt đối cho reasoning không báo riêng**. User đã xác nhận monetary cap sau khi được thông báo chưa xác minh cách tính reasoning. Không thể enforce số tiền tại gateway từ client; kiểm tra usage sau từng call và dừng khi vượt estimate/token configuration. GLM báo completion564 >512 nên đánh dấu `reported_usage_exceeded_configured_estimate` và kết thúc; đây đã là call thứ3, không có call tiếp theo. Không nâng output cap để thử lại.

MiMo và DeepSeek: response JSON hợp lệ, lưu đúng UUID, GUI xác nhận nhận cập nhật, không cảnh báo punctuation trên mẫu ngắn; khớp tham chiếu ngữ nghĩa “Say ah”/“Open wide”. **Không suy ra độ ổn định hoặc chất lượng cả chương từ một mẫu/model.**

GLM: headers và full body nhận xong, status200; parser báo `Model response is not JSON`; không ghi bản dịch đoán theo vị trí, dòng vẫn error/Chưa dịch, GUI nhận trạng thái lỗi. Đây là bằng chứng trường hợp “web có request nhưng app không có bản dịch” do nội dung phản hồi không hợp lệ, không phải HTTP504, timeout, mất DB commit hay mất thông báo GUI trong lần này. Không giữ raw response vì yêu cầu riêng tư, nên chưa phân biệt chắc truncation, reasoning preamble hay prose thay JSON. Đợt thử chưa thu finish_reason/reasoning detail; đã thêm metadata cấu trúc/finish_reason/reasoning_tokens cho request sau và kiểm thử offline, không giả lập đó là dữ liệu GLM thật đã quan sát.

**Không gặp HTTP504 trong ba call này; chưa xác minh nguyên nhân gateway 504 của các lần trước.** Không tuyên bố đã sửa gateway hoặc model ổn định. Bản sửa cải thiện phân loại, lưu trạng thái, khả năng truy vết và giới hạn retry; parser vẫn từ chối JSON sai/thiếu/trùng ID và chỉ nhận phần hợp lệ.

Đợt thật ghi queue wait0,248–0,279giây, HTTP4,173–11,585giây, DB save0,095–0,241giây, GUI acknowledgment0,00025–0,000425giây. Với mẫu này, thời gian chủ yếu nằm ở HTTP; không suy ra các batch chậm trước đây cũng có cùng nguyên nhân. Shared-client startup được tính trong queue wait.

## Bằng chứng và kiểm thử

- [Console API thật đã che dữ liệu](../artifacts/live_api_20261013/console-report.json), [TXT](../artifacts/live_api_20261013/console-report.txt).
- [Ledger/cost/token/ID](../artifacts/live_api_20261013/authorization-ledger.json), [giá public đã đọc](../artifacts/live_api_20261013/public-prices.json). Không xóa/reset ledger; đợt đã dùng hết3slot.
- [Native Windows smoke](../artifacts/gui/console/report.json): chạy `run_transcomic.py` bằng Python, platform windows, DPI125%, DB tạm, 125units, Light/Dark, manuscript/Console/history, retry-all với filter ẩn, mock504→200 một retry, xóa lịch sử có xác nhận, giữ scroll cũ/theo scroll cuối, copy report không lộ key. Không có paid call trong smoke. Ảnh ở `artifacts/gui/console`.
- Regression: giữ toàn bộ133 test cũ, sửa kỳ vọng import độc lập/schema5/navigation theo usability; test “no retry504” vẫn giữ assert6call khi optiontắt. Bổ sung34 test thực chất: 504→200/504; no retry401/403/429/500/parser/timeout/network; policy/budget; concurrency1/3/30; crashattempt2/lateattempt1; revisions; usability/export; shared-reference delete+rollback+keys/files; 3import DOCX; log rotation/privacy/restart; Consolefilters/copy/clear; DB failure; stage timings+GUI acknowledgment; other import; stop/pause trướcdispatch; GUI failure; giả lập nội dung khôngJSON+overcap. **167 đạt, 0 thất bại, 19,10 giây**, lệnh `python -m pytest -q --basetemp .pytest_console_complete`.

## Chạy

Hồi quy sau chỉnh metadata GUI cuối cùng: **167 đạt, 0 thất bại, 19,09 giây**, `python -m pytest -q --basetemp .pytest_console_release`. Native smoke Light/Dark cũng chạy lại thành công, không phát sinh request thật.

```powershell
python run_transcomic.py
python -m pytest -q --basetemp .pytest_console_complete
python -m scripts.console_gui_smoke
```

Không build EXE/PyInstaller/Inno Setup; file gốc và database/key người dùng giữ nguyên. SQLite migration5 áp dụng khi người dùng mở app thật, giữ các bảng/dữ liệu cũ.
