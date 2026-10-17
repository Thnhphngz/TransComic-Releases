# Sửa runtime và thiết kế lại TTS — 17/10/2026

> Báo cáo lịch sử. CUDA trong `.venv` đã được người dùng sửa tiếp; UI và hotfix mới nằm ở [tts-cuda-parallel-hotfix.md](tts-cuda-parallel-hotfix.md). Không dùng mô tả thiết bị/panel thu gọn dưới đây làm hướng dẫn hiện tại.

**Phạm vi: mã nguồn 1.0.4 và môi trường phát triển đã kiểm chứng. Chưa phát hành. Clean Windows không Python: NOT VERIFIED.**

## 1. Root cause

GUI trước sửa thực sự chạy bằng `C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe run_transcomic.py`, prefix Python hệ thống. Interpreter này không tìm thấy cả `onnxruntime` lẫn `kokoro_onnx`; benchmark trước đó chạy ở `D:\TransComic-TestRuntime\tts-cpu`/`tts-cuda`. Đây là hai môi trường khác nhau, không phải bằng chứng inference thành công trong GUI của người dùng. [Ghi nhận interpreter cũ](../artifacts/tts/original-source-interpreter.json).

Đã tạo `.venv` **riêng dự án**, không system-site-packages, cài dependency CPU đã pin, `pip check` không lỗi. `run_transcomic.py` chọn env có readiness marker trước khi import app; frozen không re-exec. GUI, engine process và toàn bộ package ONNX/Kokoro của lượt CPU thật đều nằm trong `.venv`. [Bằng chứng entry point, prefix, package paths và process engine](../artifacts/tts/real-entrypoint-cpu-150/report.json).

Start cũ phụ thuộc `Outputs.confirm` từ nút Xem trước/Xác nhận; job paused chưa có thư mục bị khóa bởi điều kiện chỉ cho draft xác nhận. Giao diện mới tự plan/confirm nội bộ khi Start, cho phép chuẩn bị output cho lượt paused/stopped/failed chưa được cấp thư mục và tiếp tục cấp thư mục gián đoạn, giữ snapshot/IDs/path đã cấp. Không còn confirmation gate ẩn.

Trong kiểm thử mở rộng còn phát hiện race Stop: process bị hủy đúng giữa timeout nhận phản hồi và kiểm tra liveness, bị nhận nhầm là lỗi segment. Đã kiểm tra cancellation ở cả receive và worker exception boundary, trả lease chưa commit về pending. Hai regression fault injection tái tạo đúng race này.

## 2. Những thay đổi UI

- **DOCX / TXT**: một hàng/tài liệu; dòng nguồn, đoạn hợp lệ, audio thành công/tổng, trạng thái, tiến độ, Chi tiết. File đọc lỗi có hàng Đọc lại, các file tốt được giữ. Drop trực tiếp lên bảng, nhiều file/thư mục, duplicate không nhập lại.
- **Nhập văn bản**: editor lớn, tên nội bộ và bộ đếm ký tự/dòng/đoạn; không cần TXT vật lý.
- **Chi tiết**: mở theo stable document ID, chỉ tải đoạn của tài liệu đó; chỉnh snapshot, Phát/Dừng, tạo lại lỗi, Quay lại.
- **Lịch sử bên phải**: combo chọn tài liệu, metadata, audio thành công, inline Phát/Dừng, mini-player trong panel; resize/collapse và nhớ lựa chọn độ rộng/hiển thị. Thu panel dừng phát; callback playback đến muộn được fence bằng generation.
- Cấu hình chung ở trang chính: language, voice, speed, split, format, device, output, engine/runtime. Layout chuyển 4/3/2 cột theo chiều rộng.
- Cài đặt riêng: model variant, adapter, bitrate, downloader/hash/progress/cancel, sửa runtime và log; không giấu voice/speed trong đây.
- Đã bỏ nút Gộp/Chia, sửa nguồn/tên thư mục, mẫu tên, Dán văn bản, Tiếp tục CPU, Xem trước/Xác nhận, output path edit/pick riêng, thư mục gần nhất, dropzone và player toàn chiều ngang. Cơ chế dữ liệu cũ không bị xóa theo UI.

Ảnh native dùng fixture tổng hợp để kiểm tra layout, không phải bằng chứng inference:

| DPI | Light | Dark |
|---|---|---|
| 100% | [Danh sách file](../artifacts/tts/redesign-ui/light-1-files.png) | [Danh sách file](../artifacts/tts/redesign-ui/dark-1-files.png) |
| 125% | [Danh sách file](../artifacts/tts/redesign-ui/light-1.25-files.png) | [Danh sách file](../artifacts/tts/redesign-ui/dark-1.25-files.png) |
| 150% | [Danh sách file](../artifacts/tts/redesign-ui/light-1.5-files.png) | [Danh sách file](../artifacts/tts/redesign-ui/dark-1.5-files.png) |

Cùng thư mục có ảnh Input/Details/Settings/900×580 và JSON DPR/hình học. Kiểm tra không chồng config, đúng hit rectangle delegate, đúng file khi click Chi tiết, nút chính còn trong vùng nhìn thấy, panel tự thu ở cửa sổ hẹp.

## 3. Luồng TTS

**Start:** kiểm tra dependency + model + inference probe; freeze một snapshot dùng chung. Cạnh nguồn không picker; tùy ý/paste chỉ picker tại Start. Cancel không cấp output/chạy worker. Không đổi voice/speed của lượt cũ từ các control hiện tại.

**Pause:** khóa claim mới, cho đoạn sở hữu hoàn tất rồi paused. **Stop:** hủy process ONNX, không terminate Python/Qt thread; parent giữ SQLite/encode/manifest nên child không thể ghi đến muộn. Hiển thị Đang dừng đến khi cleanup xong. **Resume:** reconcile decode/hash/revision, bỏ qua audio hợp lệ, xử lý phần pending; lỗi cần tạo lại có xác nhận.

Tên `TenFile_TTS_inprogress` → `TenFile_Ntts` chỉ khi đủ audio hợp lệ. `0001.wav/mp3` ổn định qua retry/restart. Không đổi thư mục ngầm, không ghi đè xung đột, không xóa audio khi xóa lịch sử. Relink xác minh manifest và hash.

Lỗi segment độc lập tiếp tục các đoạn khác; lỗi hệ thống/disk/runtime pause. Auto fallback GPU → CPU một lần, giữ audio; GPU-only không fallback. Runtime check không tự tải model/dependency, lỗi thân thiện trong UI, traceback xoay vòng trong `TTS/Logs/technical.log`.

## 4. Kiểm thử thực tế

| Nhóm | Bằng chứng/kết quả |
|---|---|
| Entry point CPU 100% | `python run_transcomic.py`; `.venv` CPU; 10 WAV cạnh nguồn, MP3 custom và playback, 10 audio từ nhập văn bản; [report](../artifacts/tts/real-entrypoint-cpu-100/report.json) |
| Entry point CPU 150% | Cùng entry point; 10 WAV, MP3 phát position 96 ms/duration 1056 ms, Cancel picker, 10 audio paste; [report](../artifacts/tts/real-entrypoint-cpu-150/report.json) |
| Stop CPU sau sửa race | 1 audio trước/1 sau, 0,122 giây; PID worker 1476 đã thoát, không worker còn sống; giữ hash audio đầu khi Resume |
| DOCX + TXT, Pause/reopen/Resume | 2 tài liệu, 12 audio; Pause từ 1 lên 2 vì đoạn đã cấp; đóng/mở GUI và toàn bộ DB handles; giữ hash 2 audio đã hoàn thành và snapshot speed 1,25x khi UI đổi 2x |
| GPU CUDA | GUI thực trong env CUDA riêng, GTX 1650 Ti, CUDAExecutionProvider được probe/profiling; WAV/MP3/paste/Stop/Resume đạt; Stop 0,123 giây, 1 audio trước/sau, PID 14988 đã thoát; [report](../artifacts/tts/real-entrypoint-gpu-125/report.json); bản CPU mặc định không chứa CUDA |
| Máy không Python | **NOT VERIFIED**; không có phép thử phân phối độc lập trong nhiệm vụ này |

Các phép thử trên dùng fixture mới ngoài workspace và DB production, chỉ model local đã xác minh; không API dịch. Playback xác nhận Qt nhận file thật, duration/position tiến và không lỗi; không thay thế nghiệm thu chất lượng giọng bằng nghe của người dùng. Lượt kiểm tra Stop rút ngắn **chỉ các đoạn chưa tạo** trước Resume để giới hạn thời gian thử; audio đã thành công được so hash, không sửa lại.

Ba report thực tế lần lượt có **8 + 9 + 8 = 25 checkpoint PASS**, không FAIL ở các lượt bàn giao; clean-Windows và Hybrid thật không nằm trong số PASS này.

## 5. Hiệu năng

Benchmark explicit ProcessEngine: cùng câu tiếng Anh 4 lần, `af_heart`, 1x, audio 9,984 giây; thời gian dưới đây **không gồm load/probe**. Sampling RSS 50 ms cho parent và descendants, không phải VRAM hay cam kết peak tuyệt đối.

| Backend | Inference | Audio/giây xử lý | Load + probe | RSS mẫu lớn nhất |
|---|---:|---:|---:|---:|
| CPU | 6,643 s | 1,503x | 4,026 s | 542,5 MiB |
| CUDA | 1,251 s | 7,982x | 7,047 s | 853,3 MiB |

[CPU JSON](../artifacts/tts/process-benchmark-cpu.json), [GPU JSON](../artifacts/tts/process-benchmark-gpu.json). VRAM chưa đo ở lượt mới. Benchmark trước cùng fixture đạt CPU 1,530x/GPU 8,141x ([số liệu cũ](../artifacts/tts/cuda-benchmark.json)); không kết luận thay đổi tốc độ có ý nghĩa từ một lần đo, vì env/process boundary và tải nền khác nhau. Mục tiêu thay process là khả năng hủy an toàn.

GUI regression có 2.000 đoạn: bảng chính vẫn số hàng tài liệu, Chi tiết chỉ selected document; progress không truy vấn lại toàn bộ text segment. Thêm audio out-of-order giữ persistent index, không model reset làm mất vị trí cuộn. Hybrid thật **PARTIAL** do thiếu RAM; giữ gate, không ép nạp hai session.

## 6. Regression

- Focused bàn giao: **58 PASS**, 33,32 s, không FAIL/SKIP; [log](../artifacts/tts/redesign-focused-handoff.log). Bao gồm Start/cancel, legacy paused, split snapshot, import retry, playback/history, file ownership/recovery, Auto/GPU strict và hai race Stop.
- Full offline sau triển khai chính: **1.190 PASS**, 491,69 s; [log](../artifacts/tts/redesign-full.log).
- Lượt full kế tiếp phát hiện **1 FAIL / 1.195 PASS** ([log giữ nguyên](../artifacts/tts/redesign-full-final.log)): test playback dùng tone 100 ms đã kết thúc trước assert, source URL còn tồn tại không đồng nghĩa PlayingState. Đổi fixture test thành 3 giây và chờ trạng thái đang phát thực sự; không đổi production playback để chiều test.
- **Full offline bàn giao: 1.196 PASS**, 453,99 s, **0 FAIL / 0 SKIP**; [log](../artifacts/tts/redesign-full-handoff.log). Đã chạy lại toàn bộ suite sau sửa đồng bộ test.
- GUI matrix: **6/6 cấu hình PASS**, light/dark × 100/125/150%; bốn view, Settings và small window. Các JSON trong `artifacts/tts/redesign-ui`.
- `pip check`, import audit packaging và `git diff --check`: PASS. Resource inventory không phải phép thử frozen.

Full suite bao gồm Kira Multi-Key/Live Monitor, Gemini, TXT/DOCX/export, search/replace/undo/redo, SQLite, native updater và theme. Không sửa production scheduler/API dịch để làm test pass. Những thay đổi barrier Kira test/sidebar đã có từ lượt triển khai trước được giữ.

## 7. File đã thay đổi

Lượt sửa này: `run_transcomic.py`, `transcomic/dev_runtime.py`, `transcomic/app.py` (harness isolated); `tts/runtime.py`, `process_engine.py`, `scheduler.py`, `output.py`, `player.py`, `source_smoke.py`; `ui/tts_page.py`, `tts_models.py`; `scripts/setup_tts_runtime.py`, `tts_gui_check.py`, `tts_process_benchmark.py`; tests TTS GUI/redesign; lock/extra test Pillow; README/hướng dẫn/báo cáo.

`.venv` có một bản ORT CPU 1.24.4, Kokoro 0.6.1; không cài vào Python hệ thống. Không đổi schema dịch hoặc API key. Không cần migration phá dữ liệu cho đổi UI; lỗi import lưu trong preferences TTS hiện có. Các UUID/revision/path/manifest cũ được giữ. Legacy recovery có regression riêng.

Workspace có cả code TTS chưa commit từ lượt trước. [Git diff --stat](../artifacts/tts/redesign-diff-stat.txt), [git status --short](../artifacts/tts/redesign-git-status.txt); diff stat chỉ tính file tracked, các module TTS mới còn untracked nên phải đọc kèm status. Không git add/commit.

## 8. Hạn chế còn lại

- **NOT VERIFIED:** ứng dụng frozen trên Windows sạch không Python; multiprocessing freeze/codec/Qt plugins/VC++ dependency phải thử trong nhiệm vụ được phép build. `.venv` không chứng minh Installer hoạt động.
- **PARTIAL:** gate phân phối binary licenses/corresponding source cho phonemizer/eSpeak, LAME, libsndfile và dictionaries; xem [audit giấy phép](tts-licenses.md). Chưa đóng gate bằng resource inventory.
- **PARTIAL:** Hybrid thật cần máy đủ RAM. DirectML model này lỗi ConvTranspose ở lần thử trước; CUDA hoạt động trên máy thử, không hứa mọi GPU.
- Chưa đo VRAM trong benchmark mới, chưa chứng nhận chất lượng phát âm bằng chuyên gia/người bản ngữ. Kokoro v1.0 không tiếng Việt.

## 9. Người dùng kiểm thử

Đóng phiên cũ → `python run_transcomic.py` → Text to Speech → **Cài đặt**, kiểm tra runtime/model (tải model nếu chưa có) → chọn voice/speed trên trang chính → **Thêm file** TXT → chọn **Cạnh file nguồn** hoặc **Thư mục tùy ý** → **Bắt đầu** → chọn tài liệu trong Lịch sử, **Phát/Dừng** → mở **Chi tiết** → thử **Dừng/Tiếp tục**. Chọn **Lượt mới** để nhập nội dung mới. Hướng dẫn đầy đủ: [tts-workflow.md](tts-workflow.md).

## 10. Giới hạn phát hành

Version vẫn **1.0.4**, HEAD `92cbacd1633630bdc4b0e656165e764c2efb52da`. Không commit, không build EXE/Installer chính thức, không chạy BAT/Auto Release, không publish GitHub, không API dịch thật, không xóa DB/lịch sử/audio/model cache người dùng.

Release journal SHA-256 vẫn `d8d940c2e3d8d40cf6fff7dd229e903408525246964eeaec1796abdb1ad20bef`, timestamp 17/10/2026 02:10. Kira/Gemini/updater production semantics không đổi trong lượt sửa runtime/UI này. Mã nguồn dừng ở trạng thái để người dùng nghiệm thu; hạn chế phân phối nêu tại mục 8.
