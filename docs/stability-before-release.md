# TransComic — Stability trước Giai đoạn B

Ngày kiểm tra: 14/10/2026. Chỉ sửa ba vấn đề đã được cấp quyền; không redesign, không mở khóa Stage A.

## 1. Tình trạng ban đầu và bằng chứng

Đọc báo cáo/log V3 và Stage A. Stage A có một lượt 528 pass/1 skip nhưng các lượt sau còn crash `editing.py:126`, Safe Exit 900ms và assertion 429. Không coi lượt chạy riêng/cách ly là chứng minh ổn định toàn suite.

Tái hiện mới: [Tìm/Thay baseline](../artifacts/stability/search-baseline-trace.log), [Safe Exit baseline](../artifacts/stability/safe-exit-baseline.log), [stack worker khi hết 900ms](../artifacts/stability/safe-exit-stacks.log), [đo GIL](../artifacts/stability/gil-baseline.log). Giữ toàn bộ log cũ và lượt không đạt.

## 2. Crash Qt: điều đã chứng minh và giới hạn

Driver hai kịch bản Tìm/Thay nhiều file liên tiếp, cùng process, tái hiện native access violation ngay tại `QListWidget.clear()`. Không phải exception Python có thể catch. Stack hiện hành là GUI thread; không chứng minh có worker trực tiếp gọi `clear()`. Thử tắt skin/popup hoặc bọc callback thay đổi khả năng tái hiện; kết quả đó không đủ xác định một nhánh skin là nguyên nhân duy nhất. Không tạo/tắt skin khác trong bản giao.

Điểm hỏng xác định được là teardown native item trong danh sách kết quả được tái tạo nhiều lần từ slot. **Chưa có C++ symbols/minidump để gán lỗi cho một private function cụ thể của Qt/PySide hoặc khẳng định một lỗi Qt upstream duy nhất.** Sửa loại bỏ cơ chế ownership/teardown dễ hỏng này, giữ chức năng refresh đầy đủ; không chỉ bỏ `clear()` và để kết quả cũ.

`SearchResultView` vẫn là list view Qt trong cùng vị trí/phong cách; có một `SearchResultModel` parent thuộc view, giữ snapshot bất biến `(text, result-key)`. `beginResetModel/endResetModel` thay dữ liệu, không tạo/hủy `QListWidgetItem` cho từng kết quả. Snapshot không đổi thì không reset; click lấy key trước navigation. Test chọn kết quả, replace current/all, undo, multi-file/language vẫn chạy.

## 3. File/function đã sửa

| File | Thay đổi giới hạn |
|---|---|
| `ui/editing.py` | owned snapshot model/view cho kết quả; slots rõ, guard thread/lifetime, coalesce reentry; blocker signal khi đồng bộ file checks |
| `ui/main.py` | delete accepted window qua Qt; close idempotent; callback bridge queued/Slot; không restart refresh khi closing; stop timers; poll cleanup 10ms + yield GIL không đợi worker |
| `ui/workspace_v2.py` | callback layout/branding/restore bỏ qua cửa sổ đã đóng |
| `translation.py` | chặn dispatch khi đã nhận quota exhausted; persist reason, publish callback sau state/attempt commit |

Không đổi storage/schema, provider/endpoint/HTTP timeout/prompt/validator/export guard/locale/concurrency 1–50/chính sách tối đa 5 retry. Không sửa skin/theme/updater/version/BAT/spec/ISS. [Hash phạm vi](../artifacts/stability/scope.json).

## 4. QObject lifetime

Search rebuild/model reset chỉ chạy trên thread của QObject; slot có context receiver, callback khi đóng bị bỏ qua. Reentry đánh dấu pending và drain query mới nhất đồng bộ; không thêm singleShot không có owner/generation. MainWindow `WA_DeleteOnClose` chỉ sau close event được chấp nhận: Cancel/Background vẫn giữ cửa sổ. `close()` lần nữa trả về an toàn, không gọi QWidget đã bị hủy. Qt quản lý parent-child và deferred deletion trên GUI thread; không dựa GC tùy thời điểm để dọn cửa sổ đóng.

Một QApplication skin filter cũ vẫn được giữ, không thêm filter mới. Test kiểm tra model parent, view child count không tăng, một filter, destroyed trên GUI thread và `isValid=False` sau accepted close. Không truy cập widget từ translation worker: Bridge.changed nối queued tới `@Slot(list)`.

## 5. Safe Exit: nguyên nhân đo được

Baseline lặp 5 lần: 3 lần fail, 2 lần pass; lúc fail worker vẫn sống ở các truy vấn hoàn tất scheduler. Trace không chỉ ra logger join đang giữ GUI ở các lần này. Microprobe Windows: 30 lần QTest.qWait(30) ~1,01s cho worker 27 ticks, so sleep(0,9s) cho 55 ticks. Bằng chứng phù hợp với việc event pump/điều phối GIL làm chuỗi Python/SQLite cleanup tiến triển không ổn định; chưa có trace C++ sở hữu GIL để khẳng định nguyên nhân duy nhất trên mọi máy. Poll cũ 100ms còn thêm một vòng chờ vô điều kiện sau start log-close worker; queued refresh có thể restart dù đã closing.

Sửa poll closing thành 10ms, `time.sleep(0)` nhường GIL **không chờ worker**, bỏ extra poll khi log thread đã xong. Chặn refresh/queued UI update trong closing, dừng timers, không sửa deadline 900ms hoặc HTTP/backoff. Đây là thay đổi phối hợp cleanup, không mock bỏ shutdown. Test gốc được gọi nguyên assertions 10 lần cùng process trong test mới.

## 6. Stop → Safe Exit

Stop event chặn dispatch/retry mới; GUI không join worker vô hạn. Request trả kết quả được commit với revision guards. Khi grace hết mới cancel client; transport không hợp tác dùng fence writer hiện có. Logger đóng ngoài GUI trước DB; accepted close giải phóng Qt tree. Các test idle, 1/30 request, pause/cooldown/stop, delayed commit, repeated X, responsive heartbeat và transport ignoring cancellation vẫn được chạy.

## 7. Outcome unknown

Cancel client không chứng minh server chưa xử lý. Giữ error/diagnostics `shutdown_cancelled` và `outcome_unknown`, không ghi đè kết quả commit/manual revisions, không tự replay batch unknown. Reopen kiểm tra không has_work cho attempt chưa rõ. Process probe qua entry point dùng HTTP mock không trả lời; parent chờ returncode để chứng minh process kết thúc thật, không chỉ cửa sổ ẩn.

## 8. Scheduler 429: race/publication

Mã cũ gọi `_notify(saved)` trước nhánh gán `intervention_reason`; các thao tác SQLite/log giữa response và nhánh này mở cửa sổ quan sát state chưa hoàn chỉnh. Lặp baseline nhanh 25 lượt không tái hiện assertion thời gian, nên không khẳng định mọi máy/lượt sẽ lỗi. Lỗi ordering có thể kiểm chứng bằng callback và test giữ commit lại.

Bản sửa nhận quota exhausted thì gán reason/chặn dispatch ngay sau parsed response. Reason được đưa vào attempt diagnostics trước finish/complete commit; job pause/exhausted state được ghi trước completion notification của 429. GUI/callback không nhận “đã lưu” với reason chưa có. Không đổi parser, backoff/Retry-After, attempt limit hoặc adaptive concurrency.

## 9. Không hammer

Test 3/30 mock requests giữ commit đầu lại: reason đã có, không cấp request mới; sau release mọi completion callback quan sát reason + persisted diagnostics + quota job state khớp. Mỗi batch tối đa một attempt trong kịch bản quota exhausted. Resume không tự tạo request mới khi quota chưa xử lý. Các test Retry-After/unknown reset/cooldown/wait budget và multi-file/locale tuần tự cũ được giữ.

## 10. Test mới

`tests/test_stability.py`: 12 cửa sổ/600 refresh cùng process, nested model reset/query, click/replace/undo/popup/theme, destroyed Qt ownership; gọi test Safe Exit 900ms nguyên bản 10 lần; 429 slow commit (3/30); process exit probe thật. Không xóa/nới/skip các test cũ.

`scripts/stability_windows_stress.py`: entry point Windows, DB/LOCALAPPDATA tạm, HTTP guard chỉ MockTransport. Mỗi DPI 40 cửa sổ/1.000 refresh, popup EN/ID, Light/Dark, replace current/all/undo, Console/Settings/Updater, accepted close/deferred destroy; có cửa sổ đóng khi popup còn mở.

## 11–12. Hai lượt regression đầy đủ

- Lượt 1: **534 pass, 0 fail, 1 skip**, **173,06s**. [Log](../artifacts/stability/regression-1.log), [XML](../artifacts/stability/regression-1.xml).
- Lượt 2: **534 pass, 0 fail, 1 skip**, **187,11s**. [Log](../artifacts/stability/regression-2.log), [XML](../artifacts/stability/regression-2.xml).

Hash mã runtime đã lưu trước hai lượt; không sửa mã/test giữa hai lượt, không chạy smoke/Qt của phiên song song. Skip cũ do ledger DOCX hết hạn mức, không reset ledger hoặc gửi API thêm. Lượt targeted trước đó: search/review/V3 68 pass/1 skip, lifecycle/V3 36 pass, 429/multilingual/updater 92 pass; không dùng thay cho full suite.

## 13–14. GUI/stress

Sau hai regression, Qt native Windows DPR **1,0/1,25/1,5**, **40 cửa sổ + 1.000 refresh mỗi mức**, tổng **120 cửa sổ/3.000 refresh**, không crash. 40 destroyed signals/DPI đều trên GUI thread; một skin filter. Refresh tối đa đo trên fixture nhỏ: khoảng **4,93 / 3,31 / 3,20ms**, không phải cam kết throughput tài liệu lớn. [100%](../artifacts/stability/windows/0.8/report.json), [125%](../artifacts/stability/windows/1/report.json), [150%](../artifacts/stability/windows/1.2/report.json). [Ảnh Dark](../artifacts/stability/windows/1/search-0.png), [Light](../artifacts/stability/windows/1/search-1.png), [Updater giữ nguyên](../artifacts/stability/windows/1/updater-0.png).

Process probe bổ sung 3 lượt: mỗi lượt một mock request không trả lời, grace fixture 100ms, confirmations đúng một lần, unknown giữ nguyên và không replay. Từ bắt đầu probe request đến thoát và đối chiếu DB: **218–228ms**. Parent chờ process đầy đủ **1,435–1,460s** gồm Python/Qt startup; cả ba returncode=0. Đây là hai mốc đo khác nhau, không gọi 218ms là thời gian startup+exit toàn process. [Đo OS exit](../artifacts/stability/os-exit.json).

## 15–16. Dữ liệu, API, release

Chỉ temp DB/fixtures, không sửa DB/DPAPI/source/export/history/settings thật. HTTP mock/guard, **0 Kira/Gemini thật**, không reset ledger. Không PyInstaller/ISCC/build/installer/tag/push/upload/publish; Stage A code và khóa production giữ nguyên bằng hash. Không tạo release hoặc mở khóa B.

## 17–18. Rủi ro và kết luận

**STABILITY PASS** theo tiêu chí của đợt này: hai full suite cùng mã đạt liên tiếp, Safe Exit 900ms/429/stress Qt/native DPI đều đạt, chỉ skip cũ. [Nghiệm thu tổng hợp](../artifacts/stability/acceptance.json).

Không bảo đảm mọi lỗi native Qt trên mọi driver/máy đã bị loại bỏ; chưa có C++ root-cause symbols. Kết quả mock không chứng minh server cancellation hoặc chất lượng API thật. **Đủ điều kiện chuẩn bị Giai đoạn B**, nhưng chưa cấp quyền thực hiện build/publish. Stage A vẫn khóa; B còn cần signature policy/toolchain/helper installer độc lập, installer/upgrade verification và phê duyệt riêng.

## Báo cáo cuối — 20 mục

1. Xác định điểm crash native item teardown; chưa gán một private Qt/PySide bug duy nhất khi thiếu symbols.
2. Kết quả dùng owned immutable snapshot model; refresh đầy đủ, guard reentry/thread/lifetime và Qt cleanup, không tắt skin hay che exception.
3. Stress nghiệm thu: 120 cửa sổ, 3.000 refresh cùng process theo từng DPI, không crash; unit còn 12 cửa sổ/600 refresh mỗi full run.
4. Safe Exit không tái hiện treo/thất bại trong hai full suite và repeated original test; không cam kết mọi điều kiện máy.
5. Probe request→exit/DB check 218–228ms; parent toàn process 1,435–1,460s gồm startup. Mốc 900ms test cũ giữ nguyên.
6. In-flight hoàn tất thì lưu revision-safe; deadline cancel giữ outcome_unknown, không xem client cancel là server chưa xử lý; fence giữ committed/manual edits.
7. 429 có lỗi thứ tự publication, với cửa sổ timing trước reason; không mặc định assertion chỉ lỗi timeout.
8. Reason đặt khi parsed quota exhausted, lưu attempt diagnostics; job state + commit trước completion notification. Slow-commit test kiểm chứng.
9. Chặn dispatch mới khi quota cần can thiệp; cooldown/wait budget/Retry-After cũ giữ nguyên, không hammer.
10. Tối đa 5 retry (6 attempts), batch/concurrency/prompt/validator/locale không đổi.
11. Hai full regression: 534 pass/1 skip, rồi 534 pass/1 skip; không assertion lỗi.
12. Không native Qt crash ở hai full suite và native stress mới; log baseline crash giữ nguyên.
13. Native Windows 100/125/150% đạt, không dùng mockup.
14. Updater/version/BAT/spec/ISS giữ hash và khóa production; 91 test updater và 22 V3 tests nằm trong full suite đạt.
15. Chỉ bốn file runtime nêu trên; không backend ngoài cleanup/429, không SQLite schema change.
16. Toàn bộ test temp DB/fixtures, không sửa SQLite/DPAPI/history/source/export/settings thật.
17. Không Kira/Gemini thật; HTTP mock/guard, không reset ledger.
18. Không EXE/installer build hoặc installer launch thật.
19. Không tag/push/upload/publish GitHub; test preflight cũ chỉ read-only.
20. STABILITY PASS, đủ chuẩn bị B; chưa cho phép thực hiện phát hành B và chưa bỏ điều kiện ký số/toolchain/installer validation.
