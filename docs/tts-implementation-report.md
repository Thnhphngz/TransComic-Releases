# Bàn giao TTS Kokoro — 17/10/2026

> Báo cáo lịch sử của lần triển khai đầu. Giao diện, workflow xác nhận/Stop và môi trường khởi chạy đã được thay thế ở [đợt sửa runtime/UI](tts-runtime-ui-redesign.md); không dùng các mô tả UI dưới đây làm hướng dẫn hiện tại.

**Trạng thái: triển khai mã nguồn và CPU/GPU local đã hoạt động; PARTIAL ở xác minh hybrid thật và điều kiện phân phối bundle. Chưa phát hành.**

## A. Chức năng

Đã thêm Text to Speech trên sidebar với ba tab Tạo âm thanh / Lịch sử / Giọng đọc & Cài đặt. Import nhiều TXT/DOCX, thư mục, drag/drop, paste; sửa bản sao nguồn, sửa/gộp/chia/skip segment, mẫu tên `{name}`/`{index}`. Ba chế độ tách theo yêu cầu literal-dot, không ngoại lệ `Mr.`/`3.14`.

TTS dùng model thật, không dùng mock để tạo sản phẩm. Mock chỉ phục vụ fault injection, hybrid leasing, race/recovery và test không có mạng. Ngôn ngữ/voice lấy từ catalog hash đã xác minh. Không voice cloning, không quảng cáo tiếng Việt.

Chưa có Finalize Partial và đổi thứ tự tài liệu đã xác nhận; hai thao tác này là tùy chọn. Auto chưa tự chọn hybrid vì không có benchmark hybrid thật chứng minh lợi ích ổn định. Không kết luận chất lượng đọc tương đương người bản ngữ chỉ dựa trên decode/nonsilence.

## B. Engine và đóng gói

- Kokoro ONNX 0.6.1, model v1.0; revision `1939ad2a8e416c0acfeecc08a694d14ef25f2231`.
- 54 voice bins có tên; 9 locale thuộc 8 ngôn ngữ: English US/UK, Spanish, French, Hindi, Italian, Japanese, Portuguese Brasil, Mandarin. Mỗi locale đã tổng hợp câu mẫu thật; không kiểm tra nghe chuyên môn tất cả 54 giọng.
- Model tiêu chuẩn 325.532.232 bytes; quantized 92.361.116 bytes. Cả hai tải và kiểm tra SHA-256, tạo audio CPU được. Chưa đánh giá chủ quan chất lượng nhẹ để khuyến nghị thay mặc định.
- Nhật dùng bản Misaki 0.7.4 tương thích Python 3.13, jaconv thay extension mojimoji cần compiler. Dictionary được đóng gói, không tự tải khi đọc.
- Audit PyInstaller CPU tìm đủ dependencies: 1 runtime, 1.889 data entries, 5 binary entries, 641 hidden imports tại lần audit. Đây là kiểm kê, chưa phải frozen install test.
- [Nguồn, checksum, giấy phép và gate còn lại](tts-licenses.md), [notices](tts-third-party-notices.md).

## C. CPU / GPU

Fixture benchmark: 4 câu cố định, tổng 9,984 giây audio, không gồm load/probe trong thời gian xử lý.

| Backend | Xử lý | Audio / giây xử lý | Load + probe | RSS tại mốc đo |
|---|---:|---:|---:|---:|
| CPU (runtime CPU 1.24.4) | 6,566 s | 1,520× realtime | 3,016 s | 509 MiB |
| CPU (môi trường CUDA) | 6,526 s | 1,530× | 3,895 s | 507 MiB |
| CUDA / GTX 1650 Ti | 1,226 s | 8,141× | 5,967 s | 590 MiB |
| Hybrid thật | SKIP | Không có số đo | RAM gate | Máy 8 GiB, không đủ 4 GiB RAM trống |

RSS là memory process ở các mốc, không phải peak liên tục/VRAM. Không suy rộng tốc độ sang mọi máy hoặc mọi đoạn dài. Benchmark evidence: `artifacts/tts/cpu-only.json`, `cuda-benchmark.json`.

CUDA đã qua probe có node GPU trong ORT profile và batch 3/3 audio thật, backend mỗi đoạn là `CUDAExecutionProvider` (`gpu-batch-final/report.json`). Không nhầm CUDA ordinal 0 với DXGI adapter 1. CuDNN cần NC1D padding cho convolution 1D, thuật toán DEFAULT và đủ DLL tìm thấy trên Windows; tắt fallback tự động để lỗi không bị ghi thành công GPU giả.

DirectML trên Intel UHD và GTX 1650 Ti đều lỗi ConvTranspose; cả standard/light được thử, không báo thành công GPU. Auto báo rõ rồi chuyển CPU sau lỗi probe; GPU/Hybrid chỉ định tạm dừng và có nút Tiếp tục CPU xác nhận. Giới hạn CUDA arena 2 GiB không đồng nghĩa tổng VRAM process luôn dưới 2 GiB.

Hybrid mock kiểm tra 121 đoạn, hai worker dùng chung queue, không trùng segment/tên file, hoàn tất đảo thứ tự an toàn. Hybrid thật còn cần máy có RAM trống đủ; không nới gate để chạy ép.

## D. Hàng loạt và output

WAV PCM16 mono 24 kHz; MP3 encode LAME thật, bitrate 96/128/192 kbps, decode kiểm tra. Một segment dài vẫn chỉ một audio, nội bộ stream chunks không giữ cả chương trong RAM.

Ba lựa chọn nơi xuất, dialog xác nhận đầy đủ; không fallback đường dẫn khi USB mất. `0001.wav/mp3`, tối thiểu 4 chữ số, ổn định qua retry. `Chap 9_TTS_inprogress` chỉ đổi `Chap 9_Ntts` khi xác minh đủ audio quản lý. Có collision, permissions, disk-full guards. Không merge/overwrite âm thầm.

Real batch 5/5 WAV từ TXT + DOCX manual break + paste; Pause sau audio đầu, đóng/mở DB, Resume giữ hash đầu và chỉ tạo 4 audio còn lại (`real-batch/report.json`). GUI flow cũng kiểm tra xác nhận output, cấu hình cố định, retry, lịch sử và shutdown đợi commit.

## E. Lịch sử, playback và recovery

SQLite TTS riêng tránh write lock dịch; snapshots/UUID/revision/attempt/config/hash/path/duration/backend/timestamps. Migration idempotent, không sửa DB dịch thật. Manifest + DB intent phục hồi crash giữa rename/commit. Không nhận audio dựa trên tên đơn thuần; decode/hash phải khớp. Worker cũ bị fence theo revision/attempt.

Qt Multimedia mini-player trong TTS: play/pause, prev/next, seek, volume, liên tục theo thứ tự. WAV và MP3 thật đã phát với position/duration hợp lệ. Thiếu file dừng/báo. Relink kiểm tra manifest đúng run/document/segment; xóa một/nhiều lịch sử giữ WAV/MP3. Không tự prune hoặc autorun sau restart.

## F. GUI

Ảnh native Windows, DPR thực được assert 1,0 / 1,25 / 1,5; Light/Dark, ba tab và cửa sổ 900×580. Sidebar cũ giữ IDs, Settings vẫn cuối; TTS lazy-load, translation toolbar không thay đổi. Danh sách dùng QAbstractTableModel, test 2.000 hàng không widget mỗi dòng.

| DPI | Light | Dark |
|---|---|---|
| 100% | [Tạo âm thanh](../artifacts/tts/gui/light-1-create.png) | [Tạo âm thanh](../artifacts/tts/gui/dark-1-create.png) |
| 125% | [Tạo âm thanh](../artifacts/tts/gui/light-1.25-create.png) | [Tạo âm thanh](../artifacts/tts/gui/dark-1.25-create.png) |
| 150% | [Tạo âm thanh](../artifacts/tts/gui/light-1.5-create.png) | [Tạo âm thanh](../artifacts/tts/gui/dark-1.5-create.png) |

Ảnh `*-small.png`, `*-settings.png`, `*-history.png` và JSON hình học cùng thư mục. Thanh công cụ TTS cuộn ngang khi không đủ chỗ, không đè vùng click. Settings cuộn dọc.

## G. Kiểm thử

- Full offline regression: **1.179 PASS** trong 531,80 s (`full-offline-verified.log`), gồm Kira Multi-Key/monitor, Gemini, documents, editing, validation, export, updater, theme và schema.
- Focused bàn giao sau điều chỉnh CUDA: **43 PASS** trong 29,82 s (`focused-handoff.log`).
- Real local: 14 trường hợp chuẩn WAV/MP3/speed/long/locale, không lỗi. Đoạn dài 1.000 ký tự → 62,778 s audio, xử lý 59,659 s ở lần thử đó. Slow 0,5x → 5,525 s; fast 2x → 1,365 s cùng câu.
- Real CPU batch 5 audio, restart/resume; real GPU batch 3 audio; WAV/MP3 Qt playback PASS. Model nhẹ CPU PASS. DirectML FAIL được xử lý như backend không tương thích; hybrid thật SKIP có lý do RAM.
- Safety tests: 0/1/120/1.001 audio, stable names, Unicode, duplicates, source unchanged, corrupt/silent audio, cancel/hash model download, collisions, stale worker, disk-full/permission/USB, recovery/relink/history deletion, explicit regenerate, dynamic hybrid và GUI shutdown.
- Regression cũ có race test shutdown Kira: sửa riêng barrier test để chờ HTTP mock handler được gọi thay vì bộ đếm trước gửi. Không sửa logic dịch Kira.

## H. File, dependencies và cache

- Mới: `transcomic/tts/{catalog,models,engine,adapters,documents,audio,output,storage,scheduler,devices,player,japanese}.py`, UI `tts_page.py`, icon audio.
- Tích hợp nhỏ: `ui/main.py`, `workspace_v2.py`, `update_panel.py` (sidebar, lazy page, safe exit và updater idle). Không sửa scheduler dịch hoặc API key code.
- Đóng gói/dev: `TransComic.spec`, `pyproject.toml`, `requirements-release.lock`, `scripts/tts_{packaging,real_check,real_batch,gui_check}.py`.
- Tests: `test_tts.py`, `test_tts_gui.py`; cập nhật kỳ vọng sidebar và barrier Kira test. README, tài liệu và ignore model/audio.
- Cache app: `<data directory>/TTS/Models/<revision>`, DB `<data>/TTS/tts.sqlite3`. Model thử ngoài repo: `D:\TransComic-TestRuntime\tts-models`.
- Ba venv phát triển CPU/DirectML/CUDA ở `D:\TransComic-TestRuntime`; không đổi runtime ứng dụng cài đặt. CPU requirements pin, một runtime duy nhất trong bundle; CUDA là môi trường nghiên cứu riêng.
- Audio, model, logs/screenshots ở `artifacts/tts` hoặc external cache, không vào Git. `git diff --check` không lỗi whitespace; không commit tự động.

## I. Kiểm tra thủ công

Xem [12 bước sử dụng](tts-workflow.md): mở TTS → cài model → chọn giọng/speed → nhập tài liệu → tách/biên tập → xác nhận thư mục → Start → nghe → History → Resume/Relink khi cần. Bản source cần môi trường dev TTS đã chuẩn bị; mục tiêu bundle không yêu cầu người dùng cuối cài Python/pip, nhưng chưa có bản bundle TTS để cài trong nhiệm vụ này.

## J. Phát hành

Version vẫn **1.0.4**, HEAD vẫn `92cbacd1633630bdc4b0e656165e764c2efb52da`. Không chạy Auto Release, không build EXE/Installer, không GitHub publish, không commit. Không gọi API dịch thật hoặc dùng tài liệu/DB riêng của người dùng trong test.

Release journal giữ nguyên timestamp 17/10/2026 02:10 và SHA-256 `d8d940c2e3d8d40cf6fff7dd229e903408525246964eeaec1796abdb1ad20bef`; không xóa backup/history/journal.

**Còn lại trước khi nói hoàn thành toàn bộ:** hybrid thật trên máy đủ RAM; license/corresponding-source gate của binary dependencies; kiểm chứng frozen app/installer ở nhiệm vụ được phép build sau này. Không coi mock hoặc resource inventory là thay thế cho những bước này.
