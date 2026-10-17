# TTS: hoàn thiện CUDA, hotfix giao diện và xử lý song song

> Báo cáo baseline trước V4. Giao diện lịch sử/player và ý nghĩa Dừng đã được thay bằng [TTS UX/UI V4](tts-ux-v4.md); dùng [workflow hiện tại](tts-workflow.md) để thao tác. Số đo CUDA trong báo cáo này được giữ làm bằng chứng lịch sử.

Ngày kiểm tra: 17/10/2026. Source TransComic **1.0.4**. Đây là báo cáo source và kiểm thử cục bộ; **chưa build/phát hành**. Dữ liệu kiểm thử được tạo riêng ở `D:\TransComic-TestRuntime`, không dùng tài liệu, database hay output của người dùng.

## 1. CUDA trước và sau

Giữ nguyên môi trường `.venv` mà người dùng đã sửa. Không chạy pip install/uninstall, không đổi Python/driver/CUDA/cuDNN, không cài PyTorch, không ghi System32 hoặc PATH hệ thống.

| Thành phần | Cấu hình thực tế được giữ |
|---|---|
| GPU | NVIDIA GeForce GTX 1650 Ti, 4 GiB VRAM; driver 610.62 |
| ONNX Runtime GPU | 1.24.4, build CUDA 12.8 |
| cuBLAS | `nvidia-cublas-cu12==12.9.2.10` |
| CUDA runtime | `nvidia-cuda-runtime-cu12==12.9.79` |
| NVRTC / NVJitLink | 12.9.86 / 12.9.86 |
| cuDNN | `nvidia-cudnn-cu12==9.27.0.42` |
| cuFFT / cuRAND | 11.4.1.4 / 10.3.10.19 |

Chỉ có distribution `onnxruntime-gpu`; không cài chồng wheel CPU. Providers vẫn là TensorRT, CUDA, CPU; ứng dụng ưu tiên **CUDA đã probe**, không tự chọn TensorRT. File pin dành riêng profile CUDA: [requirements-tts-cuda.lock](../requirements-tts-cuda.lock). `setup_tts_runtime.py` nhận diện GPU hiện có và kiểm tra import/preload thay cho cài CPU lock.

Inference process thực hiện `preload_dlls(directory='')` trước session. Những đường dẫn `nvidia/*/bin` được thêm bằng DLL directory handle và PATH **trong process inference**, để cuDNN nạp được thư viện con. Đã tìm thấy `cublasLt64_12.dll`, `cublas64_12.dll`, `cudart64_12.dll`, `cudnn64_9.dll`; kiểm kê đầy đủ kèm hash ở [inventory](../artifacts/tts/continue-gpu-bundle-inventory.json).

Probe GUI xác nhận audio không rỗng, hữu hạn, có biên độ; profile ghi **1.950 node CUDA**, session CUDA + CPU. Đây là inference thật, không suy từ danh sách providers. Các CUDA provider options đang hoạt động được giữ nguyên, gồm arena 2 GiB, DEFAULT convolution search, max workspace, NC1D padding và tắt TF32.

`pip freeze` trước/sau giống nhau: [trước](../artifacts/tts/continue-cuda-before-freeze.txt), [sau](../artifacts/tts/continue-cuda-after-freeze.txt). `pip check` còn cảnh báo metadata: Kokoro 0.6.1 yêu cầu distribution tên `onnxruntime`, trong khi GPU wheel cung cấp cùng module. Không cài CPU để làm mất cảnh báo; import và inference CUDA/CPU đều đã kiểm tra thực tế.

Bài đo ngắn cùng 4 câu, voice af_heart, speed 1, 9,984 giây audio: trước **1,235 s / 8,084x**; lần đo cuối khi không chạy full suite **1,220 s / 8,182x**, load + probe **4,484 s**. Một lần đo xen lúc full suite chạy đạt 7,314x; đo lại khi rảnh không tái hiện giảm tốc. Bài ngắn này chỉ đối chiếu bảo toàn runtime, không dùng để chọn concurrency. [Trước](../artifacts/tts/continue-cuda-before-benchmark.json), [sau khi rảnh](../artifacts/tts/continue-cuda-idle-final-benchmark.json).

Tham chiếu cơ chế session/provider: [Kokoro with_session](https://github.com/thewh1teagle/kokoro-onnx/blob/main/examples/with_session.py), [with_provider](https://github.com/thewh1teagle/kokoro-onnx/blob/main/examples/with_provider.py), [ONNX Runtime CUDA EP và preload](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html), [Python runtime packages](https://onnxruntime.ai/docs/get-started/with-python.html).

## 2. Khả năng chạy trên máy khác — PARTIAL

**A — bundle GPU:** helper đóng gói đã thu thập ORT, NVIDIA native libraries và metadata/notices. Tuy nhiên DLL của bộ GPU đang cài có tổng **2.890.389.760 byte**, khoảng 2,69 GiB, chưa tính interpreter/dictionaries/model và chưa nén. Updater app hiện giới hạn một download 512 MiB. Không thể đưa cả bộ này vào luồng cập nhật hiện tại rồi coi là sẵn sàng phát hành.

**B — CPU app + acceleration pack riêng:** phương án được chuẩn bị trong mã. CPU runtime đầy đủ thuộc profile Installer CPU; model/voice được tải có kiểm tra hash. GPU pack dùng interpreter riêng được đóng gói, không gọi Python/pip hệ thống. Pack lưu tại `<data>/TTS/AccelerationPacks`, tách khỏi install/update/model cache để không tải lại hàng GiB mỗi lần cập nhật app.

Đã có mã quản lý descriptor tin cậy đi kèm app, URL release chính thức cố định, size/hash archive và từng file, chặn traversal/reparse/symlink/file thừa, hủy tải/giải nén, probe CUDA trước khi atomically đổi pointer, tái sử dụng pack đã xác minh và rollback về pack trước trong catalog tin cậy. Worker dùng stdio có giới hạn frame, `-I -B`, parent death watch và Stop riêng. Pack ABI 1 hiện chạy **một worker**, không giả vờ hỗ trợ concurrency của source runtime.

**Chưa có pack/descriptor chính thức**, vì vậy giao diện chưa hiện nút tải một gói không tồn tại. Test worker stdio đã tạo WAV/MP3 thật với CUDA, Stop 0,028 s, process/thread thoát; nhưng tái sử dụng dependency của `.venv`; đó là test transport phát triển, **không chứng minh portable runtime**. [Bằng chứng IPC](../artifacts/tts/continue-pack-protocol-final-report.json).

Đã kiểm kê các license file của ORT và bảy NVIDIA packages, cùng danh sách DLL/hash. [License inventory](../artifacts/tts/continue-gpu-bundle-inventory.json), [notices và các gate còn lại](tts-licenses.md). Còn phải hoàn tất phạm vi redistribution NVIDIA, corresponding source/notices của eSpeak/phonemizer và codec/dictionary trước khi phân phối binary. Đây là kiểm kê kỹ thuật, chưa phải nghiệm thu toàn bộ license bundle.

**Chưa kiểm chứng trên Windows sạch không Python, máy không NVIDIA hoặc máy NVIDIA khác; chưa build embedded pack/Installer.** CPU fallback thật trên máy hiện tại đã đạt khi cố ý làm khởi tạo GPU thất bại. AMD/Intel không được gắn nhãn CUDA. Profile build CPU production vẫn từ chối môi trường GPU-only vì thiếu distribution CPU trong release lock; không nới chốt release để làm test xanh.

## 3. Benchmark TTS song song

Một model/session trong **một process có thể hủy**, các lane gọi session qua thread riêng. Phonemizer dùng lock của tokenizer/thư viện; không khóa toàn bộ inference. Mỗi lane giữ lease, output queue và segment identity riêng. Audio có backpressure; chỉ parent được commit manifest/SQLite/file.

Tập cố định 32 đoạn ngắn/dài khác nhau, 91,989 giây audio/lượt, af_heart, en-us, WAV, speed 1. Thứ tự đo 1, 2, 1, 2; thời gian gồm load process/model, probe, encode, SQLite, manifest và finalize. [Số đo và timeline gốc](../artifacts/tts/continue-parallel-report.json).

| Workers | Thời gian toàn lượt | Throughput trung vị | RAM peak lấy mẫu | VRAM toàn GPU peak | Lỗi | Kết luận |
|---|---|---|---|---|---|---|
| 1 | 18,836 / 17,217 s | 5,113x | 916,5 MiB | 1.105 MiB | 0; 32/32 mỗi lượt | Baseline |
| 2 | 13,960 / 13,369 s | 6,735x | 979,5 MiB | 2.141 MiB | 0; 32/32 mỗi lượt | PASS; throughput tăng 31,7% |
| 3 | Không chạy | — | — | — | Không áp dụng | SKIP: không đủ RAM trống |
| 4 | Không chạy | — | — | — | Không áp dụng | SKIP: không đủ RAM trống |

GPU utilization peak 56% → 78%; CPU peak 116,75% → 214,17% (100% tương ứng một logical core). RAM là RSS cộng parent/children lấy mẫu; VRAM là toàn GPU, không phải process-only. Khoảng lấy mẫu khoảng 0,2 s cộng thời gian nvidia-smi, không bảo đảm bắt đỉnh tức thời.

Đo riêng sau khi full suite kết thúc: load + probe một worker **4,821 s**, pool hai worker **3,648 s**; cả hai xác minh 1.950 node CUDA. Đây là lần đo startup riêng, có ảnh hưởng cache/thứ tự khởi tạo; không dùng chênh lệch này để kết luận pool load nhanh hơn. [Startup report](../artifacts/tts/continue-startup-report.json).

Timeline có **hai lệnh `session.run` chồng thời gian ở host**, peak 2. Đây là bằng chứng concurrent calls và tốc độ toàn lượt tốt hơn; chưa dùng CUDA profiler để khẳng định các kernel thực thi chồng nhau trên thiết bị.

Mặc định chung là 1. Profile đo đã lưu cho đúng GPU/driver/Python/providers/ORT/Kokoro/model revision/voice/language/format; cấu hình khác giữ 1. Mức 2 chỉ được dùng nếu RAM/VRAM trống vượt gate, không tự tăng vì GPU utilization thấp. Nâng cao cho phép kiểm thử 1–4 nhưng vẫn kiểm tra tài nguyên. GPU pool lỗi/OOM: dừng nhóm, trả lease chưa commit, giảm về 1 GPU rồi CPU fallback nếu cần; không retry vô hạn. OOM được kiểm tra bằng fault injection, không cố làm Windows cạn RAM.

## 4. GUI

- Tab **TTS Hàng Loạt**, **Nhập văn bản**, **Chi tiết** đồng bộ Light/Dark Liquid Glass; bỏ device dropdown trên trang chính, chọn backend tự động.
- Bảng file có checkbox từng hàng/chọn tất cả, Thêm file, Nhập thư mục, Xóa file đã chọn, Xóa toàn bộ. Xóa danh sách đã chạy chỉ bỏ khỏi lượt hiện tại, giữ lịch sử/audio. Đang chạy phải Dừng trước; kéo thả trực tiếp vào bảng.
- Tách **Xuống dòng / Theo dấu câu / Không tách**; Không tách tạo đúng một audio logic. Snapshot `combined` cũ vẫn đọc được nhưng không còn được chọn mới. Đổi cách tách đồng bộ cả bảng Xem câu đang mở.
- Lịch sử cố định bên phải, kéo dài vùng làm việc, cuộn riêng, không có nút ẩn. Card gọn, tải từng nhóm 20 tài liệu; segment table là model/view, không tạo một widget/audio buffer mỗi dòng.
- Card file có **Xem câu**, hiển thị mọi trạng thái. Card văn bản nhập có **Nghe** ngoài; chỉ khi nghe mới hiện player trong card, có pause/resume/seek/volume. Một player dùng chung, Dừng thu player; phát liên tục bỏ qua đoạn chưa hoàn thành.
- Menu `⋯` chứa thao tác quản trị; Open folder disabled khi chưa có/mất folder, có Liên kết lại. Dừng playback tách khỏi Dừng inference.
- Popup lỗi nonmodal, metadata/backend/runtime/ID, traceback mở rộng và Sao chép lỗi; lọc secrets/đường dẫn nhạy cảm, dedup cùng lỗi/job. GPU fallback thành công không spam popup.
- Progress cập nhật theo segment IDs, chỉ aggregate card liên quan; không tải source snapshots của toàn lịch sử mỗi tick. Full refresh chỉ lấy metadata của các card đang hiển thị.

Ảnh native dùng fixture audio tổng hợp cho bố cục, tách biệt bài inference thật:

| Giao diện | 100% | 150% |
|---|---|---|
| Light | [Toàn trang](../artifacts/tts/continue-ui-verified/light-1-files.png) | [Toàn trang](../artifacts/tts/continue-ui-verified/light-1.5-files.png) |
| Dark | [Toàn trang](../artifacts/tts/continue-ui-verified/dark-1-files.png) | [Toàn trang](../artifacts/tts/continue-ui-verified/dark-1.5-files.png) |

Ma trận còn có 125%, tab nhập, Chi tiết, Cài đặt và resize 900×580. Ảnh inference GUI thật: [hàng loạt](../artifacts/tts/continue-real-gui/files.png), [chi tiết](../artifacts/tts/continue-real-gui/details.png), [nhập văn bản](../artifacts/tts/continue-real-gui/input.png).

## 5. Output và bảo toàn dữ liệu

Giữ các sửa dở của `tts/output.py` và bổ sung hồi quy. Cùng job/document có manifest hợp lệ được nhận lại, kể cả DB chưa lưu được folder sau cấp phát. Folder job khác/không rõ chủ được giữ nguyên và cấp suffix duy nhất; kiểm tra lại khi mkdir và finalize để xử lý race. Không merge hoặc xóa folder trùng tên.

`TenFile_TTS_inprogress` → `TenFile_Ntts` khi mọi audio hợp lệ; filename giữ `0001.wav`, `0002.wav`… theo sequence, không theo thứ tự hoàn tất. Intent/manifest trước commit, hash/revision/attempt fencing, reconcile khi Resume. Final target xuất hiện giữa chừng thì dùng suffix an toàn. Lỗi ghi/ổ mất không tự đổi nơi lưu. Hash audio cũ được đối chiếu khi resume và nghe.

Regression cố tình cho worker thứ hai hoàn tất trước, kiểm tra mapping/filename/không duplicate. Test collision, cấp phát gián đoạn, finalize, relink, retry, revision cũ đều dùng output fixture. Không xóa audio/cache/database thật.

## 6. Stop / Resume / crash

- **2 worker CUDA đang bận:** Stop từ GUI **0,226 s**, active trước Stop = 2; một audio đã commit giữ nguyên trước/sau, worker process thoát, không có audio mới sau stopped. Resume thành công. Không cam kết con số này cho mọi máy/lượt.
- **1 worker CPU fallback:** Stop 0,048 s, không còn child, Resume đạt; checkpoint bắt đúng khoảng giữa các đoạn (active = 0), nên không dùng nó để khẳng định latency hủy CPU đang inference. Test process/IPC và hồi quy cancellation kiểm tra thêm nhánh đang chạy.
- Pause hai worker: trước 2 audio, hai lease đang chạy hoàn tất thành 4 rồi ngừng cấp mới. Đóng/mở GUI, Resume giữ hash 4 audio và speed snapshot 1,25 dù control hiện tại đổi thành 2; DOCX 145 dòng + TXT 2 dòng hoàn tất **147 audio**.
- **Hard crash GUI thật:** helper chỉ kill PID fixture có root/command đã xác minh trong khi active = 2. Child tự thoát khi parent chết; mở lại normal launcher, reconcile/resume đủ 12 audio, giữ nguyên hash của 2 file đã commit, không orphan. Chỉ text pending của fixture được rút ngắn để giới hạn thời gian recovery; không thay audio đã thành công. [Crash report](../artifacts/tts/continue-crash-report.json).

## 7. Tests và bằng chứng

Normal launcher `python run_transcomic.py` được dùng qua các smoke flag chỉ dành source, dùng cùng GUI, project interpreter và scheduler production. Không gọi API dịch thật.

| Nhóm | Kết quả / phạm vi |
|---|---|
| Focused cuối | **83 passed / 47,70 s**; [log](../artifacts/tts/continue-focused-verified.log) |
| Full offline cuối | **1.218 passed / 472,95 s**; [log](../artifacts/tts/continue-full-offline-verified.log) |
| GUI CUDA thật | 13 checkpoints: WAV/MP3 inference + Qt playback, picker Cancel, input, Stop/Resume, 145-line DOCX, reopen, inline player, checkbox/clear, Copy error, resize |
| GUI CPU thật | 8 checkpoints; fault injection GPU DLL initialization rồi inference CPU thật, WAV/MP3 + playback |
| Parallel CUDA | 4 lượt × 32/32; host concurrent session calls peak 2 |
| Crash/reopen | GUI bị kill khi hai lane bận, no orphan, resume 12/12 |
| Light/Dark/DPI | **6/6 process PASS**, native 100%, 125%, 150%; đủ tabs/settings/small window, control không chồng lấn |
| Acceleration pack | Mock tải/hash/rollback/cancel/traversal/file thừa; IPC CUDA thật trong runtime phát triển |
| Máy sạch / embedded binary | **PARTIAL — chưa kiểm chứng; không có Installer/pack chính thức** |
| 3–4 workers | **SKIP — không đủ RAM an toàn** |

[GUI CUDA JSON](../artifacts/tts/continue-real-gui/report.json), [CPU fallback JSON](../artifacts/tts/continue-real-cpu/report.json). Các bài playback xác minh Qt Multimedia tiến position/duration và giải mã WAV/MP3; không thay thế nghiệm thu thính giác của người dùng.

Full offline lần đầu: **1.210 passed, 3 failed** ở ba test cấu hình/staging CPU release. Nguyên nhân: môi trường GPU-only hợp lệ không có distribution CPU mà release lock yêu cầu. Đã sửa **fixture riêng của ba test** để mô phỏng profile CPU, không sửa production release gate; bổ sung test riêng chứng minh gate thực tế vẫn từ chối CPU lock trên GPU-only. Không cài CPU đè GPU. [Log gốc](../artifacts/tts/continue-full-offline.log).

Lệnh regression:

```powershell
$env:TRANSCOMIC_RELEASE_OFFLINE_TESTS='1'
.venv/Scripts/python.exe -m pytest -q
```

## 8. Files changed, dependency và migration

Các file mới TTS và một số integration đã có từ phiên trước, chưa commit; giữ nguyên thay đổi hợp lệ. Không reset/clean/checkout. Diff tracked không thể hiện hết các file untracked, vì vậy kiểm tra cả [git status](../artifacts/tts/continue-handoff-git-status.txt), [git diff --stat](../artifacts/tts/continue-handoff-diff-stat.txt) và [danh sách đầy đủ](../artifacts/tts/continue-handoff-changed-files.json).

| Nhóm | Files |
|---|---|
| Runtime / scheduler | `transcomic/tts/engine.py`, `process_engine.py`, `runtime_manager.py`, `parallel.py`, `concurrency.py`, `calibration.json`, `scheduler.py`, `storage.py` |
| Output / split / player / errors | `tts/output.py`, `documents.py`, `player.py`, `diagnostics.py`, `runtime.py` (thông báo phù hợp chọn backend tự động) |
| GUI | `ui/tts_page.py`, `tts_models.py`, `tts_history.py`, `tts_errors.py` |
| Pack chuẩn bị | `tts/acceleration.py`, `pack_engine.py`, `pack_worker.py`, `scripts/tts_packaging.py`, `requirements-tts-cuda.lock`, package data trong `pyproject.toml` |
| Kiểm tra / launcher | `scripts/setup_tts_runtime.py`, `tts_process_benchmark.py`, `tts_parallel_benchmark.py`, `tts_gui_check.py`, `tts_pack_protocol_check.py`, `tts_crash_check.py`, TTS source/crash smoke và app flags |
| Hồi quy | `test_tts.py`, `test_tts_gui.py`, `test_tts_redesign.py`, `test_tts_hotfix.py`, `test_tts_hotfix_gui.py`, `test_tts_parallel.py`, `test_tts_acceleration.py`; ba fixture release CPU |
| Tài liệu | Báo cáo này, `tts-workflow.md`, README, ghi chú báo cáo UI trước |

Không đổi installed dependencies trong nhiệm vụ. Không thêm migration dữ liệu để đổi UI/song song; dùng schema TTS hiện hữu, preference và config JSON. Schema TTS trước đó có phép bổ sung nullable `documents.started/ended`; không có migration phá dữ liệu hoặc sửa schema dịch. Production logic Kira/Gemini không bị thay đổi trong lượt này; chỉnh đồng bộ test Live Monitor đã có từ phiên trước được giữ.

## 9. Cách sử dụng

1. Đóng phiên source cũ, mở bằng `python run_transcomic.py`, chọn **Text to Speech**.
2. **TTS Hàng Loạt → Thêm file/Nhập thư mục** hoặc kéo TXT/DOCX vào bảng; văn bản dán dùng tab riêng.
3. Chọn ngôn ngữ được hỗ trợ, voice, speed, cách tách, WAV/MP3 và nơi lưu. Môi trường này đã có model; máy chưa có dùng Cài đặt để tải model/voice có kiểm tra hash.
4. Bấm **Bắt đầu**. Kiểm tra nhãn CUDA GPU/CPU và số đoạn thực tế đang xử lý ở thanh tiến độ; không phải mọi voice/format đều tự bật 2.
5. Mở **Xem câu** trong card file để nghe đoạn thành công; văn bản nhập bấm **Nghe**, điều chỉnh seek/volume/pause, bấm **Dừng** để thu player.
6. **Tạm dừng** cho đoạn đang chạy hoàn tất; **Dừng** hủy inference. **Tiếp tục** giữ snapshot/numbering/audio hợp lệ. Xóa toàn bộ chỉ dọn lượt hiện tại, giữ lịch sử/audio.
7. Nếu lỗi: mở Chi tiết kỹ thuật → **Sao chép lỗi**, gửi nội dung đã lọc secrets. Folder bị mất dùng menu `⋯ → Liên kết lại`.

## 10. Release status

- **Version vẫn 1.0.4**, HEAD vẫn `92cbacd1633630bdc4b0e656165e764c2efb52da`.
- Không commit, không git add, không chạy Auto Release/BAT, không build EXE/Installer, không upload/publish GitHub.
- Release journal SHA-256 giữ `d8d940c2e3d8d40cf6fff7dd229e903408525246964eeaec1796abdb1ad20bef`.
- Version source SHA-256 giữ `30a9fc904d5d643cdfa70acd9b559c81b98839a2986bbcfebd1446369cbd94c2`.
- Source CUDA/hotfix/song song có bằng chứng chạy thật; **phân phối binary và Windows sạch còn PARTIAL**. Chưa thể gọi đây là bản Installer đã sẵn sàng cho mọi máy.
