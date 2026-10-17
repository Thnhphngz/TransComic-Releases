# TTS UX/UI V4 — triển khai và nghiệm thu source

Ngày 17/10/2026 · TransComic **1.0.4** · chưa build/phát hành.

## A. UX/UI

**Nguyên nhân cũ:** `HistoryCard.expand()` chèn một bảng nhiều cột vào card hẹp; `HistoryPanel.attach_player()` tiếp tục chèn player vào chính card. Panel lại là child của vùng bên dưới controls, nên không thể cao tới header. Hai cơ chế làm size hint/card thay đổi khi mở câu hoặc nghe, cắt cột text và ép thanh âm lượng.

**Bố cục mới:** horizontal splitter nằm ở root trang TTS. Bên trái chứa header, controls gọn, hàng tab/tách, nội dung và điều khiển inference; bên phải là history từ trên xuống đáy. Panel cố định, cuộn độc lập, không có nút ẩn hoặc tab Lịch sử. Card chỉ chứa metadata và hành động; không còn table/player trong card.

| Thành phần | Hành vi V4 |
|---|---|
| TTS Hàng Loạt | Giữ import/thư mục/drop, checkbox/chọn tất cả, xóa file chọn/xóa danh sách, Chi tiết và progress từng file |
| Nhập văn bản | Có tên output và editor; không có Xóa toàn bộ. Sửa text/tên/config để tạo job mới ngay, không phải clear trước |
| Chi tiết | Giữ mapping/filename và editor được phép; tạo lượt mới từ context sau Hủy không bị signal đổi tab kéo về run cũ |
| Lịch sử | Tìm trực tiếp tên/voice, debounce 150 ms, 20 card/lần; thông báo trống; clear history có xác nhận áp dụng toàn bộ, không chỉ kết quả lọc |
| Xem câu | Một dialog nonmodal, resize, default 900×590 logical pixel có cap theo màn hình. STT/text/trạng thái/Phát-Dừng, tìm text hoặc STT, preview đầy đủ, model/view cho hàng nghìn đoạn |
| Audio player | Một `QMediaPlayer`/`QAudioOutput`, bar layout ở giữa đáy vùng nội dung bên trái, ngoài card/dialog. Play/Pause, filename, seek, thời gian, volume, ×; responsive một/hai hàng, không đổi hình học tabs/card |
| Settings | Model tiêu chuẩn/nhẹ, tải/gỡ/cancel, runtime/dependencies/log/chẩn đoán và pack khi có descriptor. Voice/speed/format/output/bitrate/concurrency trên main. Không tải engine/model mới |
| Backend | Nhãn ở header, dùng tên engine riêng (`engine_name`) và backend đã probe/thực chạy; CPU fallback cập nhật CPU. Không còn status strip dưới trái |
| Tách văn bản | Toggle dạng switch cùng hàng tab về bên phải ở độ rộng tiêu chuẩn; ON chọn Theo câu/Theo dòng, OFF một đoạn. Stack giữ kích thước ON/OFF, cửa sổ hẹp dùng hai hàng ổn định |

Nhóm tách chỉ thao tác editor khi dùng UI. Bulk import mới giữ xuống dòng, không bị thay bởi lựa chọn tách trong editor. Thuật toán phân đoạn không thay đổi. Đếm dựa trên `segments()` thật, có debounce text input. So sánh editor snapshot không gọi `nvidia-smi` theo từng phím gõ.

Popup cập nhật các segment ID có thay đổi; presence check file chạy ngoài paint/GUI thread, kiểm tra toàn bộ khi mở và các hàng nhìn thấy theo timer. Card input một audio cũng kiểm tra file nền: mất file thì hiện **Thiếu file**, vô hiệu Nghe; khôi phục file thì tự cập nhật. Không sửa trạng thái SQLite để che lỗi. Phát vẫn xác minh hash trước khi đọc; chọn audio khác dừng nguồn cũ trong lúc kiểm tra nguồn mới. Popup dùng lại controller, kết nối signal một lần. Đóng popup không dừng audio ngầm: player chung vẫn hiện, × dừng và thu player.

Input Không tách/một đoạn chỉ có Nghe khi thành công; input split nhiều đoạn dùng Xem câu. Quyết định theo config và số đoạn, không chỉ theo tab/path. × của player không hủy inference; Hủy inference cũng không tự dừng nguồn đang nghe đã commit.

## B. Logic TTS và persistence

`DRAFT → RUNNING → PAUSED → RUNNING → COMPLETED` vẫn có checkpoint. **Dừng/Hủy** chuyển sang **CANCELLED terminal**; không còn Stop rồi Resume cùng ID.

- Persist cancelled ngay khi hủy, invalidate attempt của đoạn chưa thành công trước khi kết thúc process; `claim()` trả None và `owns()` từ chối commit sau cancel.
- `Scheduler.start`, state transition, `Outputs.confirm/retry` và edit snapshot đều chặn tái kích hoạt cancelled. Inference process bị hủy an toàn; file đã commit, manifest và hash thành công được giữ. Không auto retry hoặc resurrect khi mở lại.
- Hủy cả lượt paused/draft có tài liệu được hỗ trợ. Card không còn menu Tiếp tục nếu cancelled/completed. Bắt đầu lại clone snapshot sang **run/document/segment ID mới**, cấp folder mới, không ghi đè job cũ.
- Tạm dừng ngừng claim và chờ các lease đang xử lý hoàn tất; Tiếp tục dùng snapshot đã lưu, đối chiếu manifest/hash trước phần còn thiếu.
- Thoát an toàn dùng `stop(permanent=False)` và lưu **interrupted**, khác Hủy. Close sau Hủy không được downgrade cancelled sang interrupted.
- Crash còn được startup chuyển running/pausing/stopping sang interrupted; cancelled nằm ngoài các chuyển đổi đó.

**Dữ liệu cũ:** không migration hàng loạt `stopped → cancelled`. Giữ legacy stopped như checkpoint recoverable, label “Đã dừng (cũ)”, đối chiếu manifest khi tiếp tục. Marker `preferences.job_cancel_policy=2` được thêm idempotent. Không đổi schema bảng dịch, không xóa/reset SQLite; schema TTS vốn dùng status TEXT, không cần rewrite bảng để thêm cancelled.

## C. CUDA và song song

Không thay dependencies, ONNX Runtime, provider options, DLL preload, engine, shared pool hoặc model/voice catalog. Snapshot trước/sau và hash engine/pool được lưu trong `artifacts/tts-v4`.

Normal launcher **`python run_transcomic.py --tts-v4-smoke ...`** mở GUI thật bằng `.venv` dự án, toàn bộ data/output là fixture ở `D:\TransComic-TestRuntime`. HTTP bị chặn trong harness; model cache đã xác minh được tái sử dụng, không tải model hay gọi API dịch.

**CUDA thực:** `onnxruntime-gpu 1.24.4`, CUDA + CPU session, probe 1.950 node CUDA. DOCX 20 đoạn hoàn tất sau pause/resume, giữ hash 4 audio; timeline gộp trước/sau pause ghi nhận peak **2 lệnh session.run chồng thời gian ở host**. Không dùng số slot queued làm bằng chứng concurrent inference và không tuyên bố đã profile CUDA kernel overlap.

**Hủy GPU:** khi active = 2, đo **0,204 s**, giữ 1 audio đã thành công, child PID thoát, không orphan, không commit muộn; reopen vẫn cancelled. GUI tạo/phát MP3 và WAV thật; editor sửa tạo job mới thành công. Clear history giữ nguyên hash **25 file audio**. [Report GUI CUDA](../artifacts/tts-v4/real-gpu/report.json).

Lần chạy GPU đầu chỉ xét timeline sau Resume, khi RAM gate đã giảm về 1 nên báo thiếu concurrency proof. Đã sửa harness kiểm tra cả hai khoảng trước/sau pause; lần đầy đủ tiếp theo ghi nhận peak 2. Không hạ gate RAM/VRAM để ép test qua.

CPU fallback đã dùng fault injection vào **khởi tạo GPU**, sau đó chạy inference/encode/playback **CPU thật**. 20/20 đoạn, pause/resume giữ 3 audio; hủy active = 1 mất 0,128 s, no orphan; WAV/MP3 và clear-history giữ 25 file. Lần đầu các checkpoint đều đạt nhưng CLI cuối cùng lỗi cp1252 khi in tiếng Việt; JSON UTF-8 và GUI không lỗi. Harness đổi console JSON sang ASCII escapes và giữ file JSON UTF-8; phần in cp1252 đã được kiểm tra lại. [Report CPU lần đầu](../artifacts/tts-v4/real-cpu-01/report.json).

**Chạy lại đầy đủ CPU sau sửa console: EXIT 0**, 20/20, giữ 3 audio qua pause; cancel active = 1 **0,105 s**, giữ 1 file; WAV/MP3, restart cancelled, editor mới và clear giữ 25 file đều đạt. [Report CPU cuối](../artifacts/tts-v4/real-cpu/report.json).

**Crash/reopen V4:** kill đúng PID GUI fixture đã kiểm tra command/root, active = 1 (gate RAM đang dùng một lane), child tự thoát, không orphan; mở normal launcher lại, run interrupted khôi phục **12/12 audio**, giữ hash **2 file**. Chỉ rút ngắn text pending trong fixture để giới hạn thời gian test; không sửa audio thành công. [Crash report](../artifacts/tts-v4/crash-report.json). Lượt cancel hai lane thật nằm ở bài GUI CUDA phía trên.

Không có benchmark throughput mới để công bố trong V4. **31,7% là baseline của phiên trước**, không gán cho lần đo UI này; xem [baseline gốc](tts-cuda-parallel-hotfix.md). Test hiện tại xác minh CUDA và hai lane không hồi quy, output/identity đúng.

## D. Dữ liệu và an toàn output

- Giữ source DOCX/TXT, model/cache, runtime, lịch sử và audio người dùng. Không dùng database/output thật để thử.
- Input tên/text/config mới tạo run mới; cancel picker không tạo job mới. Job cũ không bị sửa để lấy lại Bắt đầu.
- Output tiếp tục `_TTS_inprogress` → `_Ntts`, `0001.wav/mp3`, UUID/revision/attempt fencing. Hoàn tất đảo thứ tự vẫn đúng filename; collision planner/finalize giữ unique suffix và không merge folder lạ.
- Clear danh sách Hàng Loạt khác clear history; cả hai giữ audio. Editor nhập không bị clear theo nút Hàng Loạt.
- Clear history chặn khi còn tác vụ/paused/recoverable hoặc nháp có tài liệu; không tự hủy job để dọn. Xác nhận ghi rõ TOÀN BỘ, kể cả ngoài bộ lọc. Không unlink output hoặc model; popup trỏ tới record bị xóa đóng an toàn.

## E. Kiểm thử

| Nhóm | Bằng chứng |
|---|---|
| Focused TTS | **93 passed / 53,59 s**, [log](../artifacts/tts-v4/focused-final.log); bổ sung route/cancelled Details, switch audio và popup sau clear ở lượt kiểm tra tiếp theo |
| Full offline | **1.231 passed / 570,63 s**, [log](../artifacts/tts-v4/full-offline-final.log) |
| GUI bổ sung sau rà soát cuối | **29 passed / 30,51 s**, [log](../artifacts/tts-v4/history-presence-final.log): card audio thiếu, context Details sau cancel, popup sau clear, chuyển nguồn/player; không lặp toàn bộ suite cho các chỉnh sửa UI này |
| V4 logic | 20 đoạn pause/resume; cancel terminal + restart; legacy stopped; shutdown interrupted; lease commit bị fence; output không đổi |
| GUI mock | Dialog 2.000 đoạn/search/STT, live progress/cancel độc lập playback, thiếu file ngoài app, reuse dialog, snapshot input mới, clear No/Yes/toàn bộ ngoài filter, chặn paused clear, toggle/Unicode/no-jump |
| GUI CUDA | GUI thật, DOCX 20, CUDA node proof, hai lane; WAV/MP3/seek/volume/pause/×, history/popup, canceled restart, editor tạo job mới, clear giữ file |
| GUI CPU | CPU inference thật sau fault injection GPU; lần chạy cuối **EXIT 0**, checkpoints/25 audio bảo toàn |
| Crash/reopen | GUI fixture thật, no orphan, interrupted → 12/12, giữ hash 2 audio |
| Light/Dark + DPI | 6/6 native process đạt ở 100/125/150%; normal/maximized/900×580; popup/player/toggle/header/history geometry |

Không gọi test mock là inference thật. Ảnh layout dùng fixture metadata để kiểm tra hình học; bar phát mẫu WAV thực đã tạo ở lượt CUDA. Các số liệu runtime nằm trong report GUI thật riêng. Playback xác minh Qt giải mã, có duration/position; không thay nghiệm thu nghe bằng tai của người dùng.

## F. Ảnh kiểm chứng

Tất cả trong `artifacts/tts-v4`:

| Ảnh | Đường dẫn |
|---|---|
| Hàng Loạt Light 100% | [light-1-files.png](../artifacts/tts-v4/ui-verified/light-1-files.png) |
| Hàng Loạt Dark 100% | [dark-1-files.png](../artifacts/tts-v4/ui-verified/dark-1-files.png) |
| Light/Dark 150% | [Light](../artifacts/tts-v4/ui-verified/light-1.5-files.png), [Dark](../artifacts/tts-v4/ui-verified/dark-1.5-files.png) |
| Input tách ON | [dark-1-input.png](../artifacts/tts-v4/ui-verified/dark-1-input.png) |
| Input tách OFF | [dark-1-input-off.png](../artifacts/tts-v4/ui-verified/dark-1-input-off.png) |
| Popup Xem câu | [dark-1-popup.png](../artifacts/tts-v4/ui-verified/dark-1-popup.png) |
| Player chung đang phát | [dark-1-player.png](../artifacts/tts-v4/ui-verified/dark-1-player.png) |
| Player + DPI 150% | [dark-1.5-player.png](../artifacts/tts-v4/ui-verified/dark-1.5-player.png) |
| Full-height history/maximized | [dark-1-maximized.png](../artifacts/tts-v4/ui-verified/dark-1-maximized.png) |
| Header CUDA thật | [bulk.png](../artifacts/tts-v4/real-gpu/bulk.png) |
| Editor tạo lại thật | [input-split-off](../artifacts/tts-v4/real-gpu/input-split-off.png), [input-split-on](../artifacts/tts-v4/real-gpu/input-split-on.png) |

## G. Files changed

- UI: `transcomic/ui/tts_page.py`, `tts_history.py`, `tts_models.py`; mới `tts_audio_dialog.py`, `tts_split.py`.
- Playback: `transcomic/tts/player.py`.
- Policy/persistence/output guard: `transcomic/tts/storage.py`, `scheduler.py`, `output.py`. Không thay `engine.py`, `parallel.py`, `process_engine.py` hoặc CUDA pins.
- Harness: mới `transcomic/tts/v4_smoke.py`, opt-in dispatch trong `transcomic/app.py`; cập nhật `source_smoke.py`, `scripts/tts_gui_check.py` cho giao diện/semantics V4.
- Tests: mới `test_tts_v4.py`, `test_tts_v4_gui.py`; sửa expectations card/player/cancel ở `test_tts_hotfix_gui.py`, `test_tts_redesign.py`.
- Docs: README, workflow hiện tại, báo cáo này và ghi chú baseline cũ.
- Migration: marker policy additive; không rewrite job stopped cũ hoặc schema dịch. Không cài/gỡ dependency, không đổi API keys/Kira/Gemini/quota/export/update logic.

Git status đã có nhiều file TTS chưa commit từ phiên trước. Giữ các thay đổi đó; snapshot trước task ở `artifacts/tts-v4/before-status.txt`, `before-diff.txt`, `before-hashes.json`, `before-freeze.txt`. Danh sách cuối được lưu khi bàn giao, không dùng git reset/clean/checkout.

Snapshot cuối: [git status](../artifacts/tts-v4/after-status.txt), [tracked diff --stat](../artifacts/tts-v4/after-diff-stat.txt), [cả file untracked](../artifacts/tts-v4/after-files.json), [dependency/hash check](../artifacts/tts-v4/after-environment.json). So sánh xác nhận engine, shared pool, version và release journal giữ nguyên byte; pip freeze không đổi. `process_engine.py` không được sửa trong task, hash hiện tại cũng được ghi để đối chiếu tiếp.

## H. Release status và giới hạn

Giữ version **1.0.4**, HEAD và release journal. Không commit/git add, không Auto Release/BAT, không build EXE/Installer, không GitHub upload/publish. Không thay `.venv` hoặc CUDA/cuDNN.

Windows sạch/embedded GPU acceleration pack vẫn **PARTIAL** từ task phân phối trước; V4 không cài pack/model mới và không tuyên bố nghiệm thu Installer. Hướng dẫn thao tác mới: [tts-workflow.md](tts-workflow.md).
