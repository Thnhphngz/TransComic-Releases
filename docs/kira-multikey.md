# Kira Multi-Key — khảo sát trước triển khai

**Cập nhật kiểm tra 17/10/2026:** xem [điều tra phân phối 121 dòng](kira-distribution-121.md). Bản hiện tại có nhóm tài khoản độc lập, hạn mức/cooldown theo nhóm và thống kê request/batch/dòng/lỗi theo key. Các kết quả nghiệm thu bên dưới ghi nhận lần triển khai ban đầu.

Baseline `dd232ad` / 1.0.3, workspace sạch. Không release, build, đổi version hoặc dùng dữ liệu thật.

## Kiến trúc hiện tại

- `secrets.kira` lưu DPAPI blob; UI chỉ nhận password, không hiện lại. Gemini có bảng riêng, không dùng chung với Kira.
- `Scheduler` chạy một thread với asyncio, concurrency là số coroutine/request đang xử lý toàn lượt, không phải thread/file. `start_many` dùng chung queue round-robin nhưng nạp tất cả file, chưa có cửa sổ 10 file. Ngôn ngữ chạy tuần tự theo frozen run order, cần giữ nguyên.
- `Store.create_job` cố định tối đa 3 dòng, context 8 dòng; claim transaction pending→inflight, attempt UUID là fence, finish kiểm tra source/translation revision và line ownership. Không giữ DB transaction khi HTTP chạy.
- Pause/Stop gate trước prepare/send; Safe Exit hủy rồi fence attempt. Recovery đánh dấu inflight/prepared unknown, không tự gửi khi mở app. Retry cũ có thể retry 504 theo frozen policy: multi-key phải vô hiệu hóa, không tái gửi batch lỗi tự động.
- Parser/provider và `finish_batch` kiểm tra ID, partial results; line structure/export snapshot validation tái sử dụng không sửa quy tắc.

## Thành phần đã triển khai

- Bảng Kira riêng, stable UUID, tên, DPAPI blob, HMAC fingerprint với salt DPAPI; migration blob cũ bằng transaction idempotent, giữ marker ngăn key đã xóa sống lại. Legacy blob được chuyển an toàn, không giải mã để migration.
- Một pool key trong cùng Scheduler; coroutine slot nhận key và batch từ cùng queue. Durable attempt là owner/generation, ghi run/batch/key alias, không chứa secret. Giới hạn mỗi key 1–30 và ngân sách tài khoản dùng chung, không nhân theo file. Round-robin với tối đa 10 source instance hoạt động, không chia key theo file; giữ language barrier hiện tại.
- Key trạng thái READY/COOLDOWN/QUOTA_EXHAUSTED/INVALID/DISABLED/UNKNOWN_ERROR. Lỗi uncertain không requeue. All unavailable thì pause chờ người dùng; cooldown chỉ cho batch chưa gửi sau deadline. Resume không tái gửi unknown.
- UI API danh sách cuộn, thêm/đổi tên/bật tắt/xóa/reset offline. Thanh dịch chỉ thêm badge nhỏ trong hàng nút Start/Pause/Stop, không đổi toolbar/badge kiểm tra cũ.

## Hạn mức và chính sách công khai

Ngày khảo sát 16/10/2026: `https://kiraai.vn/documents/` không đọc được qua công cụ web. Trang `https://kiraai.vn/dieu-khoan/` không cung cấp hợp đồng quota cụ thể đủ để xác nhận nhân concurrency theo số key hoặc dùng nhiều tài khoản. Tin chính thức Qwen3.8 Max Free nêu 1 RPM cho model đó: https://kiraai.vn/tin-tuc/qwen-38-max-free-hoan-toan-mien-phi-tren-kira-ai/ . Không suy rộng thành quota mọi model.

Giới hạn trong ứng dụng là trần cục bộ, không phải xác nhận Kira cấp quota. Mặc định key chưa phân nhóm cùng scope tài khoản, giới hạn tổng 30. Trang API hiện cho chọn nhóm khi key thuộc các tài khoản độc lập; key cùng tài khoản phải cùng nhóm. RPM/TPM/concurrency/cooldown chia sẻ trong nhóm và độc lập giữa nhóm. Mock chứng minh điều phối, không chứng minh tốc độ hoặc chi phí API thật. Lượt điều tra 17/10/2026 chỉ dùng mock theo yêu cầu người dùng.

## Cấu hình và bảo vệ dữ liệu

- **Tổng lý thuyết** = số key bật/khả dụng × Luồng/key (1–30); **trần dispatch thực tế** = tổng theo nhóm của min(số key khả dụng trong nhóm × Luồng/key, trần tài khoản), còn chịu RPM/TPM/cooldown của từng nhóm. Không suy ra nhiều tài khoản từ số key. Nhóm tài khoản và các trần được chụp khi tạo adapter cho lượt; Luồng/key áp dụng động cho request mới, không hủy request đang gửi.
- Bảng thêm `kira_keys`, `kira_reservations`; giữ schema dịch 8, không rebuild/xóa bảng dịch. Migration dùng marker `kira_keys_migrated`, atomic/idempotent; key cũ có ID `legacy-kira`, tên Kira 1, giữ nguyên ciphertext. `secrets.kira` cũ được giữ làm tương thích tới khi người dùng chủ động xóa key legacy; không fallback sau migration nên key đã xóa không tự xuất hiện lại. Salt fingerprint lưu riêng bằng DPAPI, HMAC không dùng key thô làm hash công khai.
- Danh sách API chỉ đọc metadata khi refresh, dùng QSignalBlocker để rebuild không phát sinh thao tác bật/tắt/xóa. Tên không được chứa secret đã lưu. Không hiện suffix của secret; chỉ mask và stable ID. DPAPI lỗi không dùng plaintext fallback.
- Kira mới không tự retry bất kỳ batch đã gửi nào. `kira_multi_key` đóng băng auto_retries=0/retry_504=false. Tiếp tục lịch sử chỉ nhận pending chưa có attempt; explicit dịch lại có xác nhận tạo job mới và có thể tốn tiền. Gemini và scheduler legacy dùng cho các test cũ không đổi chính sách.
- Claim pending→inflight và prepare attempt UUID nằm trong cùng transaction; state + attempt ID + revision là fence. Batch diagnostics ghi run/job/batch/attempt/key alias và prepared/sent, không chứa secret. Không có lease expiry resend. Unknown được giữ cho review, không giả thành pending sau crash.
- Nhận kết quả dùng parser/finish_batch cũ, không thay mapping, hậu xử lý, kiểm tra ngôn ngữ hoặc export validation. Cảnh báo số dòng/dấu chấm và search/undo vẫn dùng state hiện tại. HTTP body không được ghi log; diagnostics nhạy cảm được redaction bằng toàn bộ secret đã đăng ký trước khi lưu vào DB.

## Điều phối và trạng thái lỗi

Một dispatcher trong `Scheduler._run` chọn phase Kira, không tạo scheduler hay OS thread/file mới. Mỗi source instance có hàng batch dùng chung cho mọi key; chọn round-robin trong tối đa 10 file active. Không ưu tiên đặc biệt file gần xong (mức ưu tiên thêm bằng 0), để giữ công bằng nghiêm ngặt. Slot/key nhanh tự lấy việc còn lại, không ràng key với file. File hết batch gửi được nhường vị trí ngay; lỗi/unknown vẫn không được báo hoàn thành. Ngôn ngữ giữ barrier tuần tự theo thứ tự người dùng đã chọn.

| Bằng chứng | Trạng thái key / tác động |
|---|---|
| 401 | INVALID; không nhận batch mới, key khác tiếp tục |
| 403 / model hoặc quyền bị từ chối | UNKNOWN_ERROR, chờ người dùng kiểm tra; không tự đổi model |
| 429 với mã quota rõ | QUOTA_EXHAUSTED, không đoán thời điểm reset; key khác chỉ chạy trong ngân sách chung |
| 429 tạm thời | COOLDOWN; tôn trọng Retry-After, thiếu deadline dùng 5 giây local backoff. Scope chưa rõ nên cooldown áp dụng chung, không xoay key để vượt 429 |
| 504 / server error | Request unknown, key UNKNOWN_ERROR; không resend hoặc failover batch |
| Timeout/mất kết nối | Request unknown theo phân loại bảo thủ hiện có, dừng cấp việc toàn pool tới Resume; không khẳng định server chưa xử lý |
| Người dùng tắt/xóa | Không nhận lease mới; request đang gửi được hoàn tất an toàn |
| Tất cả key không khả dụng | Tạm dừng, lưu lý do, chờ thêm/khôi phục key rồi người dùng nhấn Tiếp tục |

Cooldown và reservation RPM/TPM được lưu để restart/đổi key không reset ngân sách. TPM dự trù bảo thủ theo byte UTF-8 prompt/context + output cap 4.096 + overhead; không dùng usage thấp trả về để hoàn lại quota trong cửa sổ. Đây là upper estimate cục bộ, không thay tokenizer/billing Kira. Không refund reservation đã chuẩn bị nhưng bị Pause ngay trước send. Restore offline không gửi request kiểm tra; bật lại sau disable không xóa cờ quota đã xác nhận.

## UI và thống kê

`ui/kira_api.py`: tên/mask/trạng thái, checkbox, thêm nhiều key, đổi tên, xóa có xác nhận, khôi phục offline có xác nhận; danh sách cuộn. Cấu hình tài khoản chung và số request/lỗi/latency trung bình từng key ở trang API. Không yêu cầu nhập lại key cũ.

`workspace_v2`: nút nhỏ Kira: N key trong hàng Start/Pause/Stop, chỉ hiện khi provider Kira. Toolbar năm nút và hai badge giữ layout cũ. `main._refresh`: busy/max slot, số key khả dụng và file active trên thanh tiến độ; tooltip Luồng nói rõ mỗi key. Settings retry cũ không thể bật cho lượt Kira mới.

## Kiểm thử và giới hạn

Kết quả XML/log, load JSON và ảnh được ghi tại `artifacts/kira-multikey/`. Fixture DPAPI và DB đều tổng hợp/riêng biệt; không mở DB người dùng hoặc lấy key thật. Có kiểm tra migration rollback, restart không resurrect key đã xóa, duplicate, 1/2/3/5 key; trần 30/60/90/150 và 3×10; 25 và 100 file; RR, fast/slow key, ID trả đảo thứ tự; thiếu/thừa/trùng/newline, TXT CRLF và DOCX trống; explicit pause/resume/stop và cancellation; claim race/stale fence/manual edit; durable quota/cooldown; GUI refresh không xóa nhầm key.

Giới hạn cần nói rõ: không suy ra tài khoản sở hữu chỉ từ secret; mọi key dùng chung account safety scope. Cấu hình local phải được đối chiếu với provider trước khi nâng. Không chứng minh quyền multi-account hoặc tốc độ thật bằng mock. Không tự nhận diện quota reset khi provider không cung cấp bằng chứng. Không chứng nhận ngữ nghĩa dịch bằng ID/số dòng. Bản thử là source, không tạo EXE/Installer.

### Smoke và ảnh

- `smoke100/`, `smoke125/`, `smoke150/`: launcher GUI source, profile riêng, Light/Dark, TXT/DOCX/export, source bytes giữ nguyên, search/replace/undo, queue clear, update popup mock, SRT placeholder và Safe Exit. Cả ba lượt PASS, DPR 1,0/1,25/1,5; 0 real HTTP, 0 installer process. Không build EXE.
- `ui-run-smoke.json`: hai smoke bổ sung dùng MockTransport và DB tạm. (1) Đường Start một file tạo run ID và config retry=0, hai request trả về đúng SQLite, chỉnh sửa tay được giữ. (2) Safe Exit khi hai request multi-key đang chạy, grace 0,1 giây, cả sáu dòng còn unknown, thread dịch thoát. Không gửi lại request.
- Hover của test native dùng Qt Enter event để độc lập với sai số con trỏ QtTest khi ép scale khác Windows. Geometry và childAt kiểm tra vùng click, QTest click mở đúng popup và Esc đóng. Không coi đây là chứng nhận tự động cho mọi cấu hình driver/con trỏ desktop.
- Ảnh toàn cửa sổ dùng nguồn tổng hợp: [100% Light editor](../artifacts/kira-multikey/dpi100/editor-False.png), [100% Dark editor](../artifacts/kira-multikey/dpi100/editor-True.png), [100% Light API](../artifacts/kira-multikey/dpi100/api-False.png), [100% Dark API](../artifacts/kira-multikey/dpi100/api-True.png); [150% Light editor](../artifacts/kira-multikey/dpi150/editor-False.png), [150% Dark editor](../artifacts/kira-multikey/dpi150/editor-True.png), [150% Light API](../artifacts/kira-multikey/dpi150/api-False.png), [150% Dark API](../artifacts/kira-multikey/dpi150/api-True.png). Thư mục dpi125 chứa ảnh tương ứng và mỗi thư mục có dpi.json.

### File/function chính

| File | Thay đổi |
|---|---|
| `transcomic/kira_keys.py` | KiraKeysMixin: migration ciphertext, CRUD, HMAC duplicate, status/restore |
| `transcomic/kira_pool.py` | KiraPoolProvider: pool slot, account budget, cooldown, per-key stats, redaction |
| `transcomic/kira_dispatch.py` | Phase dispatch dùng chung trong Scheduler, fair file window, durable claim/attempt, no retry |
| `transcomic/translation.py` | Nhánh phase Kira trong `_run`, resume và has_work an toàn |
| `transcomic/storage.py` | Hai bảng bổ sung, migration, compatibility save/load, frozen no-retry config |
| `transcomic/retry.py` | Chặn automatic retry cho snapshot Kira Multi-Key |
| `transcomic/diagnostics.py` | Mô tả key_state dùng chung cho provider, không ghi nhầm Gemini cho sự kiện Kira |
| `transcomic/ui/kira_api.py` | API list/checkbox/name/delete/restore, giới hạn và thống kê |
| `transcomic/ui/main.py` | Dùng provider pool cho mọi đường Kira, Start một file dùng run chung, key input và live progress |
| `transcomic/ui/stage2.py` | Tạo adapter, range/tooltip luồng 1–30, provider visibility, config/refresh |
| `transcomic/ui/workspace_v2.py` | Nút quản lý nhỏ, retry explicit dùng snapshot mới, tắt cấu hình auto-retry cũ cho Kira |
| `tests/test_kira_multikey.py`, `tests/test_kira_multikey_ui.py` | Tests mới về key, dispatch, lỗi, DB, bảo mật và UI |
| `tests/test_liquid_glass_v3.py`, `tests/test_toolbar_layout.py`, `tests/test_workspace_v2.py` | Wheel/provider-switch test theo UI trần 30; hover deterministic ở forced DPI. Giữ tests scheduler legacy 40/50 để kiểm tra tương thích |

### Kiểm tra thủ công trước khi dùng thật

1. Trong đúng tài khoản Windows đã lưu key, kiểm tra Kira 1 cũ còn trong API. Không sao chép DB/DPAPI sang Windows user khác rồi giả định có thể giải mã.
2. Đối chiếu RPM/TPM/concurrency và quyền sử dụng các key với Kira. Sửa account limit ở trang API cho lượt mới, không mặc định 2 key được cấp 60 request đồng thời.
3. Thử bật/tắt key, chọn Luồng/key, Pause/Resume, xem trạng thái quota và số liệu. Restore chỉ sau khi đã kiểm tra quyền/quota; Resume không tái gửi unknown.
4. Kiểm tra con trỏ/hover và popup trên màn hình/DPI thực tế của người dùng. Ảnh và native Qt tests đã bao phủ ba scale, không thể chứng nhận mọi môi trường desktop.

**API thật: SKIP.** Không có key thật được chủ động bật riêng cho phép thử trong dữ liệu thử, chưa đủ bằng chứng về chính sách multi-account và giới hạn chi phí; không mở DB người dùng để tự tìm key. Tổng request/dòng/token/chi phí API thật của đợt này: **0 / 0 / 0 / 0đ**. Đây không phải bằng chứng Kira đã chấp nhận chạy nhiều tài khoản.

## Kết quả nghiệm thu

| Nhóm | PASS | FAIL | SKIP | Bằng chứng |
|---|---:|---:|---:|---|
| Full offline trên mã cuối | 1.078 | 0 | 0 | `acceptance-full.xml`, 392,76 giây |
| Focused Multi-Key | 37 | 0 | 0 | `focused-final.xml` |
| GUI Windows native, Light/Dark 100% | 56 | 0 | 0 | `dpi100-final.xml` |
| GUI Windows native, Light/Dark 125% | 56 | 0 | 0 | `dpi125-final.xml` |
| GUI Windows native, Light/Dark 150% | 56 | 0 | 0 | `dpi150-final.xml` |
| GUI source smoke | 3 lượt | 0 | 0 | `smoke100/125/150/report.json` |
| GUI Start/SQLite và Safe Exit Multi-Key | 2 lượt | 0 | 0 | `ui-run-smoke.json` |
| Fixture DB cũ không có bảng feature | 1 lượt | 0 | 0 | `old-schema-smoke.json` |
| DPAPI blob hỏng + key khỏe | 1 lượt | 0 | 0 | `corrupt-key-smoke.json` |
| Workspace/provider switch theo trần mới | 15 | 0 | 0 | `workspace.xml` |
| API Kira thật | 0 | 0 | Có chủ đích | Chưa xác minh điều kiện ở mục trên; không dùng key thật |

37 case mới gồm 33 backend và 4 UI. Các lượt GUI lặp theo DPI và full suite có case trùng; không cộng thành số test độc lập. Các log `full*.log` từ lượt dừng sớm/lỗi assertion UI cũ được giữ để truy vết, không dùng làm bằng chứng nghiệm thu cuối. Full suite cuối và hash/Git/protected files được tổng hợp trong `acceptance.json`. Blob DPAPI hỏng đã được cách ly mà không lặp giải mã/ghi DB theo mỗi refresh; không có plaintext fallback.

Load mock có 5 cấu hình: 1×30, 2×30, 3×30, 5×30, 3×10; mỗi cấu hình 397 request/25 file, quan sát đỉnh 30/60/90/150/30, tối đa 10 file active, chỉ 1 OS thread xử lý HTTP. Có thêm hàng đợi 100 file trong regression. JSON `load-*.json` ghi request/key, error rate, latency, thời gian dispatch và Python traced allocations; đây không phải tổng RSS của process hoặc benchmark API thật. Các case fast mock chịu chi phí SQLite/validation/tracing, không chứng minh tốc độ tăng tuyến tính theo key.

Benchmark riêng sau các lượt regression, cùng 65 request/10 file và HTTP mock trễ cố định 0,5 giây: 1 key ×30 mất **1,736 giây**, 2 key ×30 mất **1,148 giây**; peak HTTP mock thực sự **30/60**. Tốc độ đo được khoảng **6.738/10.188 dòng/phút**. Đây là bằng chứng dispatcher tận dụng được I/O song song trong mô phỏng, không phải tốc độ Kira thật hoặc cam kết tăng 1,51× trên dữ liệu người dùng. Xem `latency-benchmark.json`. Các load có tracing ghi khoảng 3–6 MiB Python allocations bổ sung và dispatch trung bình vài millisecond trên máy thử; số liệu chính xác từng lượt nằm trong JSON.

## Trạng thái bàn giao

Giữ source **1.0.3**, HEAD **dd232ad4af60c0611e1bb89e064a0c5414829360**. Git có **17 file sửa/thêm chưa commit** của tính năng và kiểm thử/tài liệu. `git diff --check` PASS; version, `release_transcomic.bat`, `scripts/automatic_release.py` không đổi so với HEAD. Không chạy release/build, không commit/push/publish, không thao tác journal/tag hoặc xóa lịch sử/backup/artifacts cũ. Không mở hoặc chỉnh DB/key thật của người dùng. Để xem tính năng cần chạy source `run_transcomic.py`; bản EXE đã cài chưa được thay thế.
