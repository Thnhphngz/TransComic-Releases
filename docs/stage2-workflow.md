# Giai đoạn 2 — Gemini, nhiều tài liệu và nhiều ngôn ngữ

Ngày nghiệm thu offline: 13/10/2026, Asia/Bangkok. Các báo cáo Giai đoạn 1 giữ nguyên dưới dạng lịch sử; số kiểm thử/API trong những báo cáo đó không phải kết quả Giai đoạn 2.

## Trạng thái

Đã triển khai và kiểm thử offline các phần dưới đây. **Chưa nghiệm thu đầy đủ Giai đoạn 2: chưa có kết quả Gemini thật.** Không chạy PyInstaller/Inno Setup, không tạo EXE/installer/release, không gọi Kira thật trong đợt này.

Người dùng đã cấp quyền riêng: tối đa một GET `models.list`, một POST `generateContent`, một dòng công khai “Hôm nay trời rất đẹp” sang tiếng Anh, output tối đa 256 token, tổng trần 1.000đ. Đã dùng đúng **1 GET (HTTP 200) và 1 POST (HTTP 404)**. Không retry/đổi key/đổi model/mở đợt mới. [Bản ghi quyền](../artifacts/live_gemini_stage2/authorization.json) đã khóa ngân sách request; quyền thử Kira trước đây không áp dụng cho Gemini.

GET trả model `models/gemini-2.5-flash-lite`; POST tới resource đó trả 404 `model_not_found`. Cache 19 model sau lọc đã được lưu vào ứng dụng bằng dữ liệu GET có quyền, không tải lại. Có thể chọn Provider Gemini để đọc cache. Danh sách model không chứng minh generateContent thực sự chạy được với key/API version; không đoán nguyên nhân sâu hơn từ mã HTTP. Không có usage hoặc bản dịch, không khẳng định lỗi 404 miễn phí.

Đã kiểm tra [giá chính thức](https://ai.google.dev/gemini-api/docs/pricing): Flash-Lite 2.5 standard text $0,10/triệu input và $0,40/triệu output gồm thinking. Cận input thận trọng 4.000 byte, output 256, FX tính dư 50.000đ/USD và hệ số an toàn 2 cho ước tính trước gửi 50,24đ, dưới cap 1.000đ. Đây không phải số tiền đã trừ. [Pricing plan](../artifacts/live_gemini_stage2/pricing-plan.json), [kết quả thật](../artifacts/live_gemini_stage2/report.json), [ảnh lỗi thật trong GUI](../artifacts/live_gemini_stage2/windows-result-404.png).

Phép thử còn phát hiện scheduler chờ pause khi không còn batch trong queue. Đã sửa kiểm tra queue rỗng trước chờ pause; thêm regression 404 cuối queue phải kết thúc, 404 khi còn batch phải pause và không gửi batch tiếp. Sửa lỗi này được kiểm chứng bằng mock, **không gửi lại POST thật**. Phép thử đầu phải Stop sau 90 giây để thoát trạng thái chờ; HTTP 404 đã về trong khoảng 0,45 giây, không phải timeout HTTP. Báo cáo được đọc lại từ SQLite, không replay.

## Các file chính

| File | Chức năng |
| --- | --- |
| `transcomic/gemini.py` | REST Gemini, model list, phân loại lỗi, key ưu tiên và quota limiter |
| `transcomic/storage.py` | Migration schema 6, run/job, workspace ngôn ngữ, key DPAPI, quota bền vững, snapshot xuất |
| `transcomic/translation.py` | Scheduler tổng, chia lượt file/ngôn ngữ, pause/resume/stop, attempt trước HTTP |
| `transcomic/bulk.py` | Nhập thư mục, sắp thứ tự tự nhiên, trạng thái workspace và xuất hàng loạt |
| `transcomic/ui/stage2.py` | Provider, key/model/quota, nhiều ngôn ngữ, nhập/xuất nền, hàng đợi |
| `transcomic/ui/main.py` | Ghép Stage 2 với editor, lịch sử, chuyển workspace và lưu chỉnh sửa |
| `transcomic/diagnostics.py`, `transcomic/ui/console.py` | Metadata provider/key alias/file/import/run/đích/attempt và Console |
| `scripts/stage2_gui_smoke.py` | Chạy entry point Python trên Windows, HTTP giả lập, storage riêng |
| `scripts/live_gemini_one.py` | Phép thử có quyền riêng, một dòng, sổ reservation trước HTTP, không replay |

Không thêm glossary/series/nhân vật/SRT. Prompt Kira `review-v2` và ngữ cảnh nguồn lân cận được giữ nguyên; Gemini dùng cùng payload mục tiêu/context và parser ID.

## API chính thức

Dùng HTTPX async hiện có; không cần thêm SDK. Endpoint chính thức v1beta, key ở header `x-goog-api-key`, không đưa key vào URL. POST dùng `systemInstruction`, `contents`, `generationConfig.responseMimeType=application/json`. Nhận text từ `candidates[].content.parts`, bỏ phần thinking, ghi usage khi có và kiểm tra từng ID; không đoán theo vị trí hoặc dùng JSON lẫn văn xuôi. Tham chiếu [generateContent](https://ai.google.dev/api/generate-content), [Models API](https://ai.google.dev/api/models), [structured output](https://ai.google.dev/gemini-api/docs/structured-output).

Model được tải qua thao tác có xác nhận, tối đa một trang/GET, không retry/key fallback. Chỉ lấy model có `generateContent`, loại ID chuyên image/audio/TTS/live/embedding/video. Lưu tên hiển thị/resource/token limits trong cache. Nếu còn trang sau, báo danh sách chưa đầy đủ. Offline giữ cache cũ, không thay model trong job đang chạy. Models API thành công chưa chứng minh quyền generateContent của từng model.

## Key và quota

Key plaintext chỉ có trong bộ nhớ phục vụ HTTP. SQLite lưu ciphertext Windows DPAPI và fingerprint để dedup; giao diện chỉ hiện alias, project khai báo, trạng thái từ bằng chứng. Thêm key không gọi API; GET model không đánh dấu key đã dịch được. Snapshot job chỉ lưu ID/thứ tự/project của key, không lưu secret. Xóa/sắp ưu tiên bị chặn trong lúc job Gemini đang chạy.

Các worker dùng cùng một key hiện tại. Không dùng nhiều key song song để tăng tốc. [Quota Gemini tính theo project](https://ai.google.dev/gemini-api/docs/rate-limits), nên key cùng project hoặc không rõ project không được tự đổi để lấy quota mới.

| Kết quả | Hành vi |
| --- | --- |
| 401 / 403 | Auth/quyền; lưu bằng chứng, tạm dừng, không tự đổi key |
| 429 thiếu bằng chứng daily | Rate limit tạm thời; tạm dừng, chỉ tiếp tục các batch chưa gửi khi người dùng resume |
| 429 `google.rpc.QuotaFailure` với quota ID theo ngày | Đánh dấu hết quota, chờ request key cũ kết thúc; chuyển key ưu tiên kế tiếp chỉ khi project độc lập đã khai báo |
| 404 | Model không tồn tại; tạm dừng, không chọn model khác |
| 5xx / timeout / lỗi mạng | Kết quả có thể không rõ; không retry hoặc đổi key |
| Schema/ID thiếu/sai/trùng | Chỉ nhận ID hợp lệ; báo lỗi từng batch/dòng, không suy diễn |

Chuyển key chỉ áp dụng batch **chưa gửi tiếp theo**, không tự gửi lại batch daily quota vừa bị từ chối. Thành công của request đang chạy không xóa bằng chứng quota của request khác trên cùng key.

RPM/TPM/RPD/concurrency phải được người dùng kiểm tra theo model và project trong AI Studio. Limiter dùng cận input thận trọng từ byte UTF-8, không gọi thêm `countTokens`. Reservation lưu SQLite trước khi gửi, giữ cả request kết quả không rõ và không đặt lại khi tạo lượt mới. Ngân sách local được cộng chung cho mọi key/project của cùng model, không tăng sau rotation. Cửa sổ rolling 24 giờ thận trọng hơn lịch reset Pacific của Google; có thể chờ lâu hơn quota thực. Cấu hình RPD là ngân sách local cho cửa sổ đó, nên đặt giá trị không vượt phần còn lại đã kiểm tra. Không biết các request ngoài ứng dụng; server có thể giới hạn sớm hơn. Pause/Stop được kiểm tra trong thời gian chờ quota.

## Nhập, workspace và scheduler

Nhập nhiều TXT/DOCX hoặc thư mục con trên thread nền. Dedup đường dẫn chuẩn hóa chỉ trong một thao tác, thứ tự chương 2 trước chương 10. File hỏng/không hỗ trợ không chặn file hợp lệ; TXT không chắc encoding được báo để nhập riêng và chọn encoding. Nhập lại cùng file là UUID mới, không kéo bản dịch cũ sang.

Mỗi source instance/ngôn ngữ đích có document/line ID, revision, bản dịch, context và export revision riêng. Workspace hiện lưu bản sao snapshot nguồn; tăng dung lượng theo số đích để đổi lấy sự độc lập, chưa tối ưu chia sẻ BLOB. Snapshot nguồn và DOCX gốc không bị ghi đè.

Một run cố định provider, model, source, targets, prompt, timeout, concurrency, key priority và quota. Scheduler round robin giữa các job file/ngôn ngữ; tổng worker toàn lượt nằm trong một giới hạn, không nhân theo số file hoặc đích. Kira vẫn giữ 1–30 và policy 504 cũ; Gemini không tự retry. Ngữ cảnh chỉ từ cùng document; phản hồi ghép bằng ID và guard revision, chỉnh sửa tay/Replace ưu tiên trước phản hồi đến muộn.

Pause ngăn dispatch mới, cho request đang gửi kết thúc. Resume không replay lỗi/unknown. Stop giữ batch chưa gửi để chủ động tiếp tục từ lịch sử, chờ request đang gửi có kết quả/timeout. Attempt đã được chuẩn bị trước HTTP nhưng chưa xác định trạng thái không tự phát lại sau crash. Lượt phục hồi giữ provider/model/ngôn ngữ/key snapshot; nếu key đã xóa thì báo không phục hồi được, không thay key âm thầm.

Khởi động editor trống. Lịch sử chỉ mở đúng workspace đã chọn, không auto API. Dropdown chuyển file/ngôn ngữ, lưu editor đang mở và vị trí cuộn từng workspace. API update không điều hướng sang file khác hoặc kéo cuộn bản thảo.

## Xuất

Mỗi thao tác xuất hàng loạt hỏi phương thức, nhớ phương thức/thư mục nhưng vẫn xác nhận lần sau. Cạnh nguồn: `TransComic/EN`, `TransComic/ID`…; thư mục tùy chọn cũng có thư mục ngôn ngữ. Tên `TênChương_EN.txt/docx`; khi trùng basename trong cùng folder/đích, thêm hash ổn định của đường dẫn và source instance. Existing file: phiên bản `_2`, `_3`… / ghi đè / hủy các file trùng.

Snapshot toàn bộ workspace được chụp trong một transaction ngắn; render/ghi file trên thread nền. Chỉnh sửa/API sau lúc chụp không đổi nội dung đợt xuất, và không làm bản mới bị đánh dấu đã xuất. Thiếu bản dịch phải xác nhận dùng nguồn tại vị trí đó. Giữ dòng trống/ending/space TXT, cấu trúc đoạn/bảng DOCX; không ghi đè nguồn. Lỗi một output được báo riêng. Xóa lịch sử bị chặn khi nhập/xuất nền đang chạy.

## Console

Metadata: provider, model, key alias, file name, document/import ID, target language, run/job/batch/attempt, HTTP status, elapsed/queue/HTTP/parse/database/GUI timing, accepted/rejected IDs và usage. Không ghi prompt/nội dung truyện/raw key. Console có filter Kira/Gemini, model động, tìm metadata và báo cáo đã redaction; các guard attempt/late response/revision của Giai đoạn 1 được giữ.

## Bằng chứng kiểm thử

- Toàn bộ 167 ca Giai đoạn 1 được giữ; migration kỳ vọng schema 6 thay schema 5.
- Thêm kiểm thử Gemini: REST/header/context/ID, 401/403/404/429/5xx, network/timeout không retry, schema thiếu/sai, models GET có quyền, DPAPI/masking, rotation không đồng thời và không tăng quota.
- Nhập 1/10/100 file cùng TXT/DOCX hỏng, trùng trong action, reimport; các cặp EN→VI, VI→EN/ID, EN→ID, ZH→VI.
- Scheduler tổng concurrency 1/3/30, round robin nhiều file/đích, context không trộn, crash unknown không replay, request budget toàn run.
- Xuất TXT/DOCX, basename trùng, hai đích, source fallback, version/cancel, snapshot nhận chỉnh sửa/API muộn.
- UI→adapter→parser→SQLite→GUI bằng mock, cấu hình chạy không đổi theo UI, thủ công được giữ, cache offline, quota qua restart, stop cắt thời gian chờ quota.
- Guard live: mặc định chỉ chuẩn bị, không mở user DB/gửi HTTP; quyền riêng bắt buộc; reservation GET và POST độc lập và không replay sau thất bại.

Lệnh đầy đủ sau bản sửa cuối: `python -m pytest -q --basetemp .pytest_stage2_final3`: **227 đạt, 0 thất bại, 33,61 giây**. Gồm toàn bộ 167 ca Giai đoạn 1 và 60 ca mới; không tăng timeout HTTP để làm test qua.

Native Windows: `python -X utf8 -m scripts.stage2_gui_smoke` chạy `run_transcomic.py` với LOCALAPPDATA riêng, Light/Dark, tỉ lệ 125%, 3 file TXT/DOCX → 6 workspace EN/ID, concurrency tổng 3, pause/resume, sửa tay/chuyển workspace, 34 POST mock, xuất 6 file và nguồn không đổi. [Report](../artifacts/gui/stage2/report.json), [editor Dark](../artifacts/gui/stage2/dark-manuscript-1000.png), [queue Light](../artifacts/gui/stage2/light-queue.png), [API Dark](../artifacts/gui/stage2/dark-api-1000.png), [Console Dark](../artifacts/gui/stage2/dark-console-1000.png). Đây là bằng chứng giao diện và luồng dữ liệu, không chấm chất lượng ngữ nghĩa Gemini.

Native hồi quy Kira: `python -X utf8 -m scripts.console_gui_smoke`, Word 7-8.docx 125 units, 2 request mock gồm 504→200 đúng một retry, giữ nguồn, xóa lịch sử có xác nhận và cuộn Console đúng. [Report](../artifacts/gui/console/report.json).

## Phần còn lại và cách chạy

Đã có key DPAPI do người dùng thêm. API thật đã dùng đủ 1 GET/1 POST nhưng POST 404, token/chi phí thực tế chưa có. Không kết luận về chất lượng ngữ nghĩa, quota thực tế hoặc tương thích JSON từ mock. Muốn thử model khác cần **đợt quyền mới**, không nằm trong quyền đã dùng. `python -X utf8 -m scripts.live_gemini_one` (không flag = chỉ mô tả, không API); `--report-only` đọc SQLite và ghi báo cáo, không HTTP. Sổ reservation không tự reset kể cả lỗi.

Chạy ứng dụng:

```powershell
python -m pip install -e '.[test]'
python run_transcomic.py
```

Thêm key tại **Quản lý API → Google Gemini**; không dán secret vào chat/log. Không phải build EXE để dùng các chức năng mới.
