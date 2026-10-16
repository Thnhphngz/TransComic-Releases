# Kira Live Monitor — triển khai ngày 17/10/2026

## Khảo sát và thiết kế

Mã đầu lượt đã có `KiraPoolProvider.stats`, slot/key, nhóm tài khoản, reservation RPM/TPM/cooldown và dispatcher dùng chung. Nút `Kira: N key` nằm trong hàng Start/Pause/Stop, chuyển thẳng sang API. Claim/attempt UUID, source/translation revision và `finish_batch` đang bảo vệ mapping; mỗi payload tối đa 3 dòng, context riêng. Dispatcher đã có observer HTTP, callback lưu SQLite và các event Console. Theme dùng widget Qt/Liquid Glass, các dialog review đang giữ editor qua `PeriodWarning`.

Giữ scheduler/round-robin, hạn mức, batch/context, language barrier, cửa sổ 10 file và các fence. Mở rộng telemetry đang sở hữu **chính dictionary `pool.stats`**, thêm ledger attempt và tổng hợp theo key/document ID/ngôn ngữ. Popup không có bộ đếm riêng, không lấy tổng chia đều cho key.

## Các thành phần

| File/hàm | Thay đổi |
|---|---|
| `kira_telemetry.py` / `KiraTelemetry` | Ledger idempotent, cập nhật counters cũ và attribution file, snapshot tách rời |
| `kira_pool.py` / `begin_monitor`, `monitor_snapshot` | Gắn telemetry vào pool, khóa snapshot/metadata theo thứ tự SQLite → telemetry, giữ contribution của key đã xóa |
| `kira_dispatch.py` / `run`, `execute` | Gắn claim/sent/received/commit vào attempt ID; lưu attribution trong transaction kết quả |
| `storage.py` / schema, `complete_attempt` | Bảng summary/index bổ sung, bảo vệ diagnostics terminal trước callback trùng |
| `kira_monitor_store.py` | Summary theo run; đọc latest một lần, dựng lại từ diagnostics của đúng run |
| `translation.py` / `monitor_checkpoint`, lifecycle/fence | Checkpoint tối đa khoảng 1 lần/giây và khi kết thúc; giữ Pause/Stop/recovery/unknown |
| `ui/kira_monitor.py` | Dialog, thẻ key, model file cập nhật từng hàng, điều hướng ID |
| `ui/workspace_v2.py`, `ui/kira_api.py` | Nút Kira mở monitor, tooltip; quản lý API qua nút trong popup |
| `ui/model.py`, `ui/main.py` | Giữ editor/undo khi focus qua monitor, đóng timer/dialog khi thoát |
| `diagnostics.py` | Event lỗi persistence của summary, không chứa nội dung hoặc credential |

## Dữ liệu thực tế và cách đếm

Định danh: **run → key → document ID → locale đích → batch UUID → attempt UUID → line ID + source/translation revision**. Chỉ lưu basename, ID/revision và metadata; không lưu source/translation/context vào telemetry. Credential không vào snapshot, tooltip hoặc ảnh. Snapshot được redactor của pool xử lý trước khi hiển thị/lưu summary.

- `CLAIMED_NOT_SENT`: đã được claim nhưng chưa bắt đầu HTTP; không tăng request sent hoặc dòng đang dịch.
- `IN_FLIGHT`: observer xác nhận bắt đầu HTTP. Cộng đúng số line ID payload, bỏ context.
- `COMMITTING`: đã nhận body/failure và không còn chờ HTTP; slot có thể vẫn bận trong lúc validate/commit.
- `SUCCEEDED_AND_COMMITTED`: đầy đủ dòng được xác minh và ghi xong.
- `FAILED`: lỗi được phân loại; dòng hợp lệ của phản hồi partial vẫn có thể được lưu và đếm riêng.
- `UNKNOWN`: timeout/504/cancellation sau gửi hoặc fence; không tự suy ra thành công/thất bại chắc chắn và không tự retry.
- `REJECTED`: revision đã đổi do người dùng; không cộng dòng đó vào contribution của key.
- `CANCELLED`: dừng trước gửi, không tính thành request HTTP hoặc request lỗi đã gửi.

`finish_batch` và diagnostics terminal nằm trong **cùng outer transaction**. Chỉ cập nhật telemetry sau outer COMMIT. Lỗi write/commit không cộng dòng thành công. HTTP 200, nội dung rỗng sau normalization, sai ID hoặc sai ngôn ngữ không được coi là dòng đã lưu.

`requests` đếm bắt đầu HTTP, không chứng minh server đã tính tiền. `successful_requests` là phản hồi hợp lệ qua các kiểm tra; một phản hồi hợp lệ có thể chứa dòng bị từ chối vì người dùng vừa sửa. `batches` chỉ đếm full commit. Popup hiển thị lỗi request đã xác định và unknown ở hai số riêng; trường `errors` cũ của API vẫn bao gồm cả hai để tương thích.

**Dòng đã lưu** tính theo lần xử lý được chấp nhận. **Dòng duy nhất** là tập `(document ID, locale, line ID)` đã từng được ghi trong lượt. Dịch lại có chủ đích tạo attempt/lượt mới, có `mode=retranslation`; không tạo thêm vị trí nguồn. Ledger bỏ qua event sent/received/terminal lặp lại theo attempt ID. `complete_attempt` giữ diagnostics terminal nếu callback lặp, nên restart không đọc lại một bản ghi đã bị ghi đè sai.

## Popup

- Nút Kira giữ nguyên hàng/vị trí, mở dialog non-modal; không đổi trang hoặc trạng thái dịch.
- Tổng quan, thẻ key thu gọn/mở rộng và bảng file. Slot bận lấy từ pool; dòng đang dịch chỉ tính HTTP đang chờ, không tính queued/claimed/context.
- Timer **750 ms**, cập nhật widget trên Qt main thread; đóng bằng Esc/Đóng dừng timer. Worker vẫn thu thập dữ liệu khi dialog đóng.
- Cập nhật tăng dần theo ID; không reset model mỗi tick, không sắp xếp lại thẻ, giữ scroll/selection/expanded state.
- Rộng mục tiêu 720 logical px, giới hạn theo cửa sổ/màn hình; cao tối đa khoảng 80% vùng ứng dụng. Nội dung nhiều key/file có scroll. Header dài được elide và có tooltip đầy đủ.
- Click file kiểm tra document ID + locale + workspace membership, dùng `open_document` hiện có để giữ vị trí/scroll. Không reimport, dịch lại hoặc gửi HTTP. File không còn mở có thông báo; không tự chuyển nhầm sang file cùng tên.
- Cache editor native và guard focus giữ undo/redo khi chuyển file. Nút **Quản lý API** đóng dialog rồi mới chuyển trang API.

## Persistence và recovery

Thêm bảng `kira_monitor_runs` và index, không rebuild/xóa bảng dịch hoặc đổi phiên bản schema dịch. Summary định kỳ/kết thúc và diagnostics attempt dùng cơ chế SQLite hiện có. Khi mở lại app, đọc một summary mới nhất và diagnostics **chỉ của run đó**, không quét toàn bộ lịch sử mỗi 750 ms. Không giải mã key để khôi phục monitor.

Sau crash, attempt có HTTP start chưa có outcome được dựng thành UNKNOWN; prepared chưa gửi thành CANCELLED, busy về 0 khi xem bản archived. Không khởi động dịch hoặc retry khi mở monitor. Khi key đã xóa, vẫn giữ contribution theo ID, không phục hồi credential. Lịch sử thiếu attribution được ghi là không có dữ liệu chi tiết, không suy đoán file/key.

Summary là persistence phụ: lỗi lưu summary ghi cảnh báo, giữ thống kê RAM và không làm ngắt dịch. Transaction kết quả/attempt vẫn bắt buộc; lỗi ở đó ngắt theo cơ chế hiện có, không ghi nhận thành công giả. Tốc độ là trung bình theo thời gian trôi qua từ đầu lượt, gồm cả thời gian Pause; không phải benchmark API thật hoặc chứng nhận chất lượng ngữ nghĩa.

## Kiểm thử và bằng chứng

Tất cả dùng dữ liệu tổng hợp và MockTransport, đặt `TRANSCOMIC_RELEASE_OFFLINE_TESTS=1`. Các ca mới bao phủ 1/2/3/5 key, DOCX 121 dòng, nhiều file/trùng tên/nhiều locale, key nhanh/chậm, quota/cooldown, timeout/504, partial/invalid/normalization, write/commit failure, callback trùng, sửa tay, Pause/Resume/Stop, Safe Exit/fence và restart. GUI bao phủ 1/10 key, nhiều file/scroll, timer tự cập nhật, Esc/nút đóng/API, điều hướng, undo/redo và đổi lượt.

Bằng chứng ở [`artifacts/kira-live-monitor`](../artifacts/kira-live-monitor). Mock 5 key/10 file đạt 150 HTTP slot, 165 batch duy nhất; snapshot và UI refresh được đo riêng. Mock 2 key trên DOCX 121 dòng ghi 21/20 request và 61/60 dòng đã lưu, 121 dòng duy nhất. Không coi số đo mock là hiệu năng hoặc giám sát Kira thật.

### Kết quả cuối trên mã bàn giao

| Bộ kiểm thử | PASS | FAIL | SKIP | Thời gian theo log pytest |
|---|---:|---:|---:|---:|
| Focused monitor/multi-key/toolbar/line/export checks | 168 | 0 | 0 | 184,29 giây |
| Toàn bộ offline regression | 1.138 | 0 | 0 | 423,74 giây |
| Native Windows Light/Dark 100% | 11 | 0 | 0 | 42,75 giây |
| Native Windows Light/Dark 125% | 11 | 0 | 0 | 42,85 giây |
| Native Windows Light/Dark 150% | 11 | 0 | 0 | 44,66 giây |
| Ca DOCX export sau sửa phép chờ worker | 1 | 0 | 0 | 4,68 giây |

Kết quả full đã bao gồm phép thử DOCX export được sửa, các ca legacy/Gemini/SQLite/export, Kira Multi-Key, nhóm tài khoản và bộ monitor mới. Focused không thay thế full; mỗi bộ có XML/log riêng. Lượt full trước bị dừng sau lỗi phép chờ DOCX không được tính PASS.

[`acceptance.json`](../artifacts/kira-live-monitor/acceptance.json) tổng hợp XML, metadata và kiểm tra SHA-256 của source/tests không đổi so với lần kiểm thử cuối. XML cuối: `focused-final.xml`, `full-offline-final.xml`, `dpi100-verified.xml`, `dpi125-verified.xml`, `dpi150-verified.xml`. Tất cả đều FAIL=0, ERROR=0, SKIP=0.

Mock tải 5 key/10 file cấu hình 150 slot đạt **150 HTTP đồng thời, 165 request duy nhất**. Snapshot backend trung bình khoảng **0,12 ms**; lần đo UI cuối trung bình khoảng **2,61 ms**, cao nhất khoảng **41,3 ms**. Số đo này thuộc fixture cục bộ, không khẳng định throughput của Kira thật.

Phiên bản nguồn giữ **1.0.3**; HEAD giữ `dd232ad4af60c0611e1bb89e064a0c5414829360`. `release_transcomic.bat`, `scripts/automatic_release.py` và file version không thay đổi; không commit, build hoặc phát hành.

### Các lỗi phát hiện và sửa trong kiểm thử

- Resume tới ngay sau khi phase đã drain trong lúc Pause có thể ghi đè trạng thái `finished` bằng `running`, dẫn tới `needs_intervention`. Resume giờ giữ trạng thái phase đã hoàn tất; bước drain và Resume dùng cùng khóa điều phối. Regression ép cả ranh giới slot vừa giải phóng và phase đã drain.
- Widget popup có thể đã nhận đủ số dòng nhưng tiêu đề còn chờ nhịp timer 750 ms. GUI regression đợi cả số liệu lẫn trạng thái hoàn thành; không thay timer thành polling liên tục.
- Native Windows 150% có thể dịch dialog ra ngoài vùng hiển thị khi cửa sổ cha lớn hơn màn hình. Dialog tính cả frame và clamp vị trí sau show; regression kiểm tra geometry cùng nút đóng.
- Focus khi chuyển từ monitor về editor ở native Windows có thể đóng editor vừa khôi phục. Guard điều hướng và trả focus giữ đúng editor/undo/redo; có ca click chuyển file rồi Ctrl+Z/Ctrl+Y.
- Khôi phục từ summary cũ cần tính lại latency/error rate từ diagnostics bền vững. Unknown chưa có số đo latency không tạo mẫu 0 giây; UI hiển thị chưa đủ dữ liệu.
- Full regression phát hiện phép thử xuất DOCX đọc file trước khi worker hoàn tất: timeout chờ cũ chỉ khoảng 2 giây, trong khi fixture hoàn tất sau khoảng 3,5 giây. Chỉ sửa `tests/test_gui.py` để đợi tín hiệu hoàn tất với giới hạn 10 giây và assert worker đã xong; giữ nguyên kiểm tra nội dung DOCX và logic export.

Các log thử nghiệm thất bại hoặc bị dừng trong thư mục bằng chứng được giữ để đối chiếu; chỉ kết quả final được tính nghiệm thu.

### Giới hạn và kiểm tra thủ công

- Theo dõi lượt Kira hiện tại hoặc lượt gần nhất đã có attribution; không tự dựng contribution cho lịch sử trước Live Monitor. Không có trình duyệt nhiều năm lịch sử.
- Nếu retry workspace gồm nhiều nhóm model/provider chạy bằng các scheduler con, popup chọn lượt Kira của scheduler con mới nhất; không cộng các run độc lập thành một lượt giả. Các summary vẫn tách theo run ID.
- Tốc độ gồm thời gian chờ/Pause, chỉ phản ánh dữ liệu lượt hiện tại. Request unknown không xác nhận số token hoặc tiền đã tiêu.
- Kiểm tra thủ công trên máy người dùng: mở monitor khi dịch, thu/mở thẻ, chuyển file và quay lại editor; xem số slot còn bận khi Pause; đóng/mở popup, restart sau khi hoàn tất và so sánh thống kê. Chỉ thử API thật khi có yêu cầu riêng; phiên này không thực hiện.

### Ảnh giao diện

| DPI thực tế | Light | Dark |
|---|---|---|
| 100% / DPR 1,0 | [Popup Light](../artifacts/kira-live-monitor/dpi100/monitor-light.png) | [Popup Dark](../artifacts/kira-live-monitor/dpi100/monitor-dark.png) |
| 125% / DPR 1,25 | [Popup Light](../artifacts/kira-live-monitor/dpi125/monitor-light.png) | [Popup Dark](../artifacts/kira-live-monitor/dpi125/monitor-dark.png) |
| 150% / DPR 1,5 | [Popup Light](../artifacts/kira-live-monitor/dpi150/monitor-light.png) | [Popup Dark](../artifacts/kira-live-monitor/dpi150/monitor-dark.png) |

Các ảnh là widget native Windows với HTTP mock đang giữ request để chụp số dòng in-flight, không phải số liệu hoặc giám sát tài khoản Kira thật. Thư mục tương ứng chứa `dpi.json` xác nhận DPR và ảnh toàn trang editor.

Không API thật, không dữ liệu riêng trong kiểm thử, không tăng version, build EXE/Installer, chạy BAT phát hành hoặc publish. Không xóa/reset dữ liệu, backup hay journal.
