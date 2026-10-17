# One-click TTS Setup và Windows release readiness

**Trạng thái mới nhất:** xem [Windows distribution và kiểm thử Installer](windows-distribution-report.md). Installer nội bộ cuối đã chứa bản sửa CRT, qua native one-click/restart/reinstall trong Sandbox sạch và frozen CUDA hai lane trên host: **READY FOR USER INSTALLER TEST**, chưa publish. Nội dung one-click bên dưới được giữ làm lịch sử phiên trước, bao gồm các giới hạn build/license tại thời điểm đó.

17/10/2026 · source **1.0.4** · **PARTIAL về phân phối Windows**. Bootstrap đã có mã và inference thực; chưa build TransComic EXE/Installer, chưa có nghiệm thu Windows sạch không Python. Không gọi kết quả source GUI là nghiệm thu bản phân phối.

## 1. Kiến trúc cài đặt

Giữ Kokoro ONNX, scheduler lease/ID/output, CUDA engine và shared-process hiện có. Installer cơ bản dùng profile **ONNX Runtime CPU duy nhất** cùng GUI/HTTPS/NumPy/SoundFile/LAME/phonemizer/dictionaries/Qt Multimedia. `scripts/tts_packaging.py` từ chối build base từ môi trường GPU, để không vô tình nhét hàng GB CUDA vào mọi Installer. Manifest release CPU đã có từ trước; không cài CPU wheel chồng vào `.venv` GPU của người phát triển.

Bootstrap Python chuẩn (`download.py`, `managed_runtime.py`, `setup.py`) không import ONNX Runtime GPU để mở GUI. Model/voice tách khỏi EXE. Máy NVIDIA tương thích được tự chuẩn bị **runtime riêng**: Python embedded 3.13.14 chính thức + các archive PyPI đã pin; không có pip, không chạy setup.py, không dùng Python hệ thống hoặc `.venv` của developer. `.whl` được giải nén xác định; hai sdist thuần dữ liệu/Python `jieba` và `unidic-lite` chỉ lấy package và notices, không chạy mã build. Không host lại CUDA wheel trên GitHub trong task này.

Interpreter embedded có `_pth` cố định (stdlib zip, site-packages riêng, worker nguồn đi kèm ứng dụng), không import site/user-site. Worker chạy `-I -B`, bỏ PYTHONHOME/PYTHONPATH khỏi environment. CPU và GPU có thư mục riêng, mỗi profile chỉ chứa một distribution ORT. Nếu CPU runtime trong base hợp lệ thì tái sử dụng; bootstrap cũng có đường tải runtime CPU riêng khi thiếu runtime. Codec parent vẫn thuộc bootstrap/base Installer, được kiểm chứng WAV/MP3 trước Ready.

**Phân biệt:** CPU/GPU embedded đã chạy inference thực trên Windows host đang có công cụ phát triển. GUI vẫn là source launcher trong bài thử này. Không có bằng chứng frozen GUI trên máy không Python; phần đó còn PARTIAL/BLOCKED theo mục 9.

## 2. Luồng một nút

**Text to Speech → Cài đặt → Tải model**:

1. Chụp cấu hình từ controls, khóa đổi variant/adapter trong lúc setup. Hardware discovery và mọi I/O/probe chạy trên utility thread.
2. Kiểm tra model/cache, tải đúng variant và đủ 54 voice; bỏ qua file đã đúng size/SHA.
3. Kiểm tra CUDA Driver API (`nvcuda.dll`), architecture và compute capability; không bắt buộc `nvidia-smi` trong PATH, không cài driver, không chọn AMD/Intel cho CUDA.
4. Dùng CUDA đang hoạt động nếu có; nếu base chỉ có CPU và NVIDIA phù hợp, chuẩn bị GPU embedded từ các artifact đã pin. Không có NVIDIA thì dùng CPU base hoặc chuẩn bị CPU embedded khi cần.
5. Xác minh archive, giải nén staging, kiểm tra toàn bộ installed tree; chỉ chạy executable sau integrity validation.
6. Khởi tạo Kokoro thật trong đúng process, chạy probe. GPU cần node profiling CUDA thực, không chỉ provider name. Tạo rồi giải mã WAV **và** MP3 để xác minh codec.
7. Promote runtime và current pointer sau probe; ghi setup state và hiện **Kokoro — Sẵn sàng / Thiết bị: CPU hoặc CUDA GPU**. Download 100% riêng lẻ không làm `runtime_ready=True`.

Nếu GPU lỗi, tự dùng CPU hợp lệ, thông báo ngắn; không có wizard kỹ thuật hoặc câu hỏi cài runtime/CUDA riêng. Fingerprint catalog/driver/runtime lưu CPU fallback; scheduler dùng backend đã probe và cập nhật khi fallback, không lặp thử GPU ở từng job. Driver/runtime thay đổi hoặc người dùng nhấn nút setup lại cho phép kiểm tra lại.

Không thêm bước Python/pip/PowerShell/PATH/DLL thủ công cho người dùng. Bước chọn nơi xuất khi tạo audio vẫn là lựa chọn output của TTS, không phải bước cài đặt.

## 3. CUDA và song song

Giữ nguyên `.venv`: ORT GPU **1.24.4**, cuBLAS **12.9.2.10**, CUDA runtime **12.9.79**, NVRTC/NVJitLink **12.9.86**, cuDNN **9.27.0.42**, cuFFT **11.4.1.4**, cuRAND **10.3.10.19**. Driver/GPU baseline: GTX 1650 Ti 4 GB / 610.62. Python embedded pin 3.13.14 cùng ABI CP313 đã được kiểm chứng; không tuyên bố đây là Python mới nhất.

Kokoro engine giữ `preload_dlls(directory='')`, DLL-directory handles và PATH **chỉ trong process inference**. Các DLL nằm trong runtime đã xác minh: `cublasLt64_12.dll`, `cublas64_12.dll`, `cudart64_12.dll`, `cudnn64_9.dll` cùng thư viện phụ. Không ghi System32 hoặc PATH hệ thống. Không dùng TensorRT.

Protocol 2 của runtime mới giữ **một Kokoro session/process**, tối đa hai lane qua IPC có giới hạn frame/queue/timeout. `ManagedLane` dùng giao diện lane của scheduler cũ; claim, commit, retry, numbering, pause và cancel không được viết lại. Gate RAM/VRAM vẫn áp dụng; thiếu `nvidia-smi` chỉ làm giảm concurrency thận trọng, không phủ nhận GPU có thể chạy. Không ép 2 lane trên mọi máy, không thử 3–4.

**Kết quả thực:**

- [Embedded CUDA](../artifacts/tts-setup/embedded-gpu-report.json): ORT 1.24.4, **1.950 CUDA nodes**, executable/prefix nằm trong runtime được quản lý; WAV/MP3 hợp lệ. Các archive tải thật từ nguồn đã pin.
- [SetupFlow tự chọn GPU thực](../artifacts/tts-setup/automatic-gpu-flow-report.json): bootstrap được injection thiếu ORT, CUDA Driver API vẫn dùng GPU host thật; flow tự chọn CUDA, dùng runtime/cache đã xác minh và probe **1.950 CUDA nodes**, WAV/MP3 hợp lệ, Ready, HTTP bị chặn. Không ép backend bằng tham số cấu hình của flow và không dùng GPU source `.venv` cho inference. Tái lập bằng `tts_setup_fallback_check.py --gpu-success`; lượt này kiểm tra auto-selection/cache, còn cold GPU artifact download đã được kiểm chứng trong embedded CUDA report.
- [Embedded CPU](../artifacts/tts-setup/embedded-cpu-report.json): CPU inference và WAV/MP3 thật bằng interpreter riêng. Lần đầu phát hiện thiếu `cloudpickle`; đã bổ sung artifact pin 3.1.2 và chạy lại thành công.
- [GUI CPU từ fixture trống](../artifacts/tts-setup/fresh-gui-cpu-report.json): một click tải model/54 voice/runtime thực, WAV/MP3 và playback, restart Ready và giữ **2 history runs**, setup lại với HTTP bị chặn vẫn thành công. ORT bootstrap được injection là thiếu và NVIDIA không có; Qt/encoder parent vẫn chạy từ source. [Ready 125% sau sửa nhãn](../artifacts/tts-setup/fresh-gui-cpu/ready-final.png), [toàn trang sau restart](../artifacts/tts-setup/fresh-gui-cpu/restart.png).
- [Scheduler với runtime độc lập](../artifacts/tts-setup/managed-scheduler-report.json): **20/20**, width=2, peak **2 session.run chồng thời gian ở host**, pause/resume giữ 4 hash, hủy **0,126 giây**, không orphan. Không tuyên bố đã profile CUDA kernel overlap.
- [Source CUDA regression](../artifacts/tts-setup/source-cuda-report.json): 20/20, peak 2, giữ 4 audio qua pause; hủy active=2 khoảng **0,197 giây**; reopen giữ cancelled; clear history giữ **25 audio**, WAV/MP3/playback đạt. Đây là bài `.venv` bổ sung, không thay bằng chứng embedded.
- CPU fallback thực: cố ý làm chuẩn bị GPU lỗi, sau đó setup tự cài/tái sử dụng CPU embedded, probe và encode/decode hai format, lưu negative cache; không dùng source CPU inference để giả lập kết quả embedded.

Lần kiểm tra hủy runtime mới đầu tiên nhận thấy cycle lane→pool giữ process handle lâu hơn cần thiết trên Windows; đã phá cycle khi close và xác minh lại việc PID biến mất. Không sửa CUDA engine hoặc pool source đã hoạt động. Không dùng benchmark **31,7%** cũ làm số đo throughput của task này.

## 4. Artifact, dung lượng, hash và giấy phép

Manifest được sinh **ở bước chuẩn bị source/build**, từ PyPI JSON của đúng version và checksum trên trang release Python.org, rồi đi kèm app; end user không resolve version hoặc lấy hash mới từ response tải xuống. Chỉ HTTPS với nguồn ban đầu allowlist, SHA-256/kích thước pin; không secrets, link token hay script tải về rồi thực thi.

| Thành phần | Download bytes | Nguồn/phiên bản | License |
|---|---:|---|---|
| Python embedded x64 | 10.964.839 | Python.org 3.13.14 | PSF-2.0 |
| Model standard | 325.532.232 | ONNX Community / revision cố định | Apache-2.0 |
| 54 voice bin | 28.200.960 | cùng revision model | Apache-2.0 |
| CPU embedded + dependencies, gồm interpreter | 127.798.682 | ORT CPU 1.24.4 + lock | hỗn hợp, xem notices |
| GPU embedded + dependencies, gồm interpreter | 2.003.058.653 | ORT GPU 1.24.4 + đúng NVIDIA pins ở trên | hỗn hợp/NVIDIA EULA |

Standard + voices = **353.733.192 byte**. Khi CPU runtime đã bundled, máy CPU chỉ cần tải phần model/voice này. Với bootstrap thiếu CPU runtime hoàn toàn, tổng cold download standard + CPU là **481.531.874 byte**. Với GPU runtime mới, tổng standard + GPU là **2.356.791.845 byte**. Đây là download size, không phải footprint giải nén hoặc RAM. Model nhẹ tùy chọn 92.361.116 byte không bị tự tải/thay cho standard.

Xem **[bảng đủ 95 artifact/file model, SHA-256, URL, license và cache](tts-setup-artifacts.md)**; [manifest/machine audit](../artifacts/tts-setup/release-readiness.json); runtime catalog: `transcomic/tts/setup-catalog.json`. Mỗi voice có hash riêng, không đặt một hash giả cho cả nhóm. Hash Python embedded: `90b4e5b9898b72d744650524bff92377c367f44bd5fbd09e3148656c080ad907`.

Rà soát primary sources: [Python embedded](https://docs.python.org/3.13/using/windows.html#the-embeddable-package), [Python 3.13.14 files/checksum](https://www.python.org/downloads/release/python-31314/), [ORT CUDA requirements/preload](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html), [CUDA 12.9 EULA và redistributables](https://docs.nvidia.com/cuda/archive/12.9.1/eula/index.html), [cuDNN 9.27 terms](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.27.0/reference/eula.html).

**License gate vẫn PARTIAL:** không suy rằng wheel NVIDIA tùy ý được bundle/host lại. Luồng mới tải trực tiếp artifact upstream và giữ notices, không tự republish GPU pack. Base Installer vẫn cần hoàn tất provenance/corresponding source cho eSpeak binary, nghĩa vụ GPL phonemizer/eSpeak, LGPL LAME/libsndfile, dictionary/Qt/FFmpeg notices và terms NVIDIA cho người dùng. Wrapper `espeakng-loader` thiếu license metadata được ghi rõ REVIEW_REQUIRED, không gán bừa giấy phép. Không đổi license toàn repository hoặc coi audit này là phê duyệt phát hành.

Microsoft binary inventory: Python embedded đã xác minh chứa `vcruntime140.dll` **120.400 byte** và `vcruntime140_1.dll` **49.776 byte**, cùng file version **14.42.34438.0**; [SHA-256 từng DLL](../artifacts/tts-setup/microsoft-runtime-inventory.json). Không gán PSF license của Python cho các DLL Microsoft. Điều kiện phân phối phải đối chiếu [Microsoft Redistribute Visual C++ files](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170) và terms áp dụng; không tự cài VC redistributable hoặc thay System32 trong task này. Việc runtime còn cần DLL hệ thống nào trên Windows sạch vẫn thuộc gate Installer chưa chạy.

## 5. Cache, resume, integrity và rollback

Root production: `%LOCALAPPDATA%/TransComic/TTS` (từ data path hiện có), tách `%LOCALAPPDATA%/Programs/TransComic` và `TTS` không nằm trong cache updater `TransComic/Updates`.

- Model/voice: `Models/<model-revision>/...`; verified NPZ riêng, không xóa sau đóng app/update.
- Runtime archives: `Runtimes/Downloads/<upstream-sha256>`; `.download.part` cùng cache, không ở TEMP/output/source documents.
- Runtime đã xác minh: `Runtimes/<catalog-and-worker-hash>-cpu|cuda`; `current.json` active/previous.
- Staging ngẫu nhiên trong Runtimes, probe trước promotion; failure/cancel chỉ dọn đúng staging do lần gọi đó tạo. Runtime trước, cache hợp lệ, model, history và audio giữ nguyên.
- Resume dùng Range và Content-Range đã kiểm tra. Server trả 200 thì khởi động lại đúng file; timeout/408/429/5xx retry có giới hạn 3 request, file hợp lệ không tải lại. URL lỗi vĩnh viễn hoặc hash sai không báo Ready.
- Giải nén chặn absolute/drive/UNC/backslash/`..`, reserved Windows names, link/reparse, duplicate entries và expansion limit; kiểm tra dung lượng trống. File thực thi được kiểm tra từ **archive hash pin + worker source tin cậy**, không tin `installed.json` tự khai hash. Thêm/sửa binary rồi giả manifest cũng bị từ chối.
- Khi giải nén, kiểm tra thư mục cha mới một lần thay vì lặp filesystem walk cho từng file; verify dùng inventory không theo reparse. Giữ kiểm tra hash file, không bỏ integrity để tăng tốc.
- Mọi đường dẫn runtime dùng Win32 extended-length path, không đòi bật LongPathsEnabled. GUI thực đã phát hiện lỗi khi staging ngắn đổi tên sang SHA đầy đủ khiến một file ORT vượt 260 ký tự; regression mới kiểm tra cài, promotion và mở lại với đường dẫn dài.
- Runtime hỏng được dựng lại trong staging; sau probe mới quarantine thư mục hỏng và promote, rollback rename nếu promotion lỗi. Không ghi đè runtime đang hoạt động trong lúc tải.
- Rollback API chỉ chấp nhận profile đã được catalog/source hiện tại tin cậy (CPU↔CUDA); không chạy bản runtime lịch sử không còn thuộc catalog. Các thư mục và archive cũ được giữ để phục hồi/đối chiếu. Cross-version catalog rollback cần trusted history trong release tương lai và chưa được nghiệm thu trong task này.

Cleanup tự động giới hạn staging lỗi; không tự purge active/previous hoặc cache archive cần để xác minh/repair. Disk full dừng với trạng thái thử lại. Không âm thầm xóa audio/model để lấy chỗ.

## 6. GUI và vòng đời

Giữ trang TTS V4.1, lịch sử, player, checkbox và Ctrl+Z. Chỉ sửa Settings/setup: nút chính **Tải model**, tiến độ MB/giai đoạn, Hủy tải, **Thử lại**, trạng thái Chưa tải/Sẵn sàng/CPU fallback. Không thêm dropdown CPU/CUDA/audio hoặc wizard. Không còn bắt người dùng bấm Sửa runtime để cài pip.

Callback/timer TTS sau shutdown được chặn và timer input/history filter được dừng, tránh đọc SQLite đã đóng khi người dùng thoát ngay sau cancel/setup. Runtime/model probe không tạo run/document/history.

Native UI matrix **6/6 PASS** cho Light/Dark ở DPR 1/1,25/1,5, gồm resize khi đang chuẩn bị, cancel, lỗi/retry và ready CPU fallback. Matrix dùng mock flow được ghi rõ trong JSON/ảnh, không giả là hardware inference. Bài download/inference thật riêng ở mục 3/7.

Ảnh GUI thật phát hiện QLabel trạng thái bị co thấp hơn văn bản nhiều dòng ở 125%; đã đặt vertical size policy Minimum, bổ sung GUI regression và assertion height-for-width vào cả sáu lượt matrix chạy lại. Kiểm tra cached runtime thật sau sửa: Ready, nhãn **54/54 logical pixels**, giữ **2 history runs**, không HTTP; [geometry report](../artifacts/tts-setup/fresh-gui-cpu/final-layout.json). Không coi matrix cũ thiếu assertion này là đủ bằng chứng chống cắt chữ.

| Trạng thái | Light 100% | Dark 150% |
|---|---|---|
| Đang tải | [ảnh](../artifacts/tts-setup/native/light-1-progress.png) | [ảnh](../artifacts/tts-setup/native/dark-1.5-progress.png) |
| Retry | [ảnh](../artifacts/tts-setup/native/light-1-retry.png) | [ảnh](../artifacts/tts-setup/native/dark-1.5-retry.png) |
| Ready/fallback | [ảnh](../artifacts/tts-setup/native/light-1-ready-fallback.png) | [ảnh](../artifacts/tts-setup/native/dark-1.5-ready-fallback.png) |

## 7. Kiểm thử và tình trạng hiện tại

- Focused toàn bộ TTS: **123 pass, 68,13 giây** trước bổ sung guard callback, atomic lifecycle và long-path. Focused cuối setup/shutdown/V4.1: **34 pass, 13,07 giây**, gồm cài/promotion/restart vượt 260 ký tự, probe lỗi không đổi active pointer, cancel, rollback, repair từ archive đã xác minh và nhãn trạng thái không bị co cắt.
- Download offline: Range/restart/cache reuse; server bỏ Range; 404/503/timeout; hash/range sai; cancel; disk full/permission; path traversal/ZIP; manifest giả; catalog ORT exclusive; pipeline Ready chỉ sau probe; fallback/negative cache và GUI responsiveness/retry.
- CPU/GPU embedded thực, codecs, nguồn source CUDA, shared scheduler hai lane/cancel: PASS theo các JSON nêu trên. CPU fallback thực có injection ở bước GPU, CPU inference/codec thực.
- **Full offline cuối: 1.265 PASS, 623,77 giây (10:23), exit 0** sau sửa UI/hướng dẫn lỗi, không có workload cài runtime chạy song song. [Log đầy đủ](../artifacts/tts-setup/full-quiet-final.log). Bao gồm regression dịch/Kira/Gemini dùng mock HTTP, TTS, GUI, SQLite/history, output, undo và updater/release fixtures; không dùng API dịch thật.
- Các lượt trước chạy chồng workload có lỗi timing ở mock Kira; lượt kế tiếp dừng khoảng 71% để sửa lỗi nhãn phát hiện qua ảnh. Không tính lượt dừng là PASS, không sửa Kira hoặc nới threshold.
- Cold setup GUI cuối: **PASS**, root fixture mới `one-click-fresh-gui-cpu-longpath`, không seed model/runtime từ cache khác, không resume fixture. Tải và probe CPU embedded thực, tạo **2 WAV + 2 MP3**, playback tiến vị trí, restart Ready, history **2→2**, explicit setup lần hai khi cấm HTTP vẫn PASS; **1.201 timer ticks** trong setup chứng minh GUI còn xử lý event. Không khẳng định đã nghe bằng tai hoặc đây là Windows sạch. [Report](../artifacts/tts-setup/fresh-gui-cpu-report.json).
- Harness trước dùng QTest.qWait hết 20 phút vì GIL làm chậm utility thread; đã đổi vòng chờ harness sang sleep nhường GIL. Lượt tiếp theo tạo/phát WAV/MP3 nhưng phát hiện lỗi đường dẫn dài khi restart; đã sửa production runtime và chạy lại từ fixture trống như trên. Các lượt chưa qua không được tính PASS; report lỗi được giữ.
- Windows sạch/frozen GUI không Python: **PARTIAL, chưa chạy**; không có VM/sandbox được provision cho task. Không dùng VM không passthrough làm bằng chứng CUDA.
- Update/cache preservation: kiến trúc install/data/update root được đối chiếu; không đổi updater/schema dịch/API settings. Update Installer thực/frozen rollback chưa chạy nên PARTIAL.

## 8. Files và build configuration

Mới: `transcomic/tts/download.py`, `managed_runtime.py`, `managed_engine.py`, `managed_worker.py`, `setup.py`, `setup-catalog.json`; `tests/test_tts_setup.py`, `test_tts_setup_gui.py`; các script `tts_setup_catalog.py`, `tts_managed_check.py`, `tts_managed_scheduler_check.py`, `tts_setup_gui_check.py`, `tts_setup_matrix.py`, `tts_setup_fallback_check.py`, `tts_release_readiness.py`.

Sửa: `models.py` dùng downloader resume chung; `runtime_manager.py` nhận runtime độc lập/CPU preference; `runtime.py` đổi hướng dẫn lỗi sang nút Tải model hiện có; `scheduler.py` chỉ thêm lựa chọn factory/backend và shared lanes protocol 2; `tts_page.py` nối flow/Settings, size policy nhãn và guard shutdown; `scripts/tts_packaging.py` CPU-base guard, catalog và worker source data. Không đổi `engine.py`, `parallel.py`, `process_engine.py`, model catalog, version, release journal hoặc cài lại dependencies. Không migration SQLite mới trong task này.

Dependency lock mới là **artifact lock JSON** có URL/size/SHA; giữ nguyên manifests `.venv` CUDA/release pins hiện tại. `scripts/tts_setup_catalog.py` chỉ dùng khi chuẩn bị source/build; không được GUI gọi để resolve metadata online. `tts_release_readiness.py` tạo audit read-only, không build/install/publish.

Tài liệu: thêm `docs/tts-one-click-setup.md`, `docs/tts-setup-artifacts.md`; cập nhật `docs/tts-workflow.md` và liên kết từ `README.md`. Báo cáo thực nghiệm, ảnh, audit và snapshot đặt tại `artifacts/tts-setup/`; audio/model/runtime kiểm thử nằm ngoài repo trong root fixture riêng, không dùng tài liệu người dùng.

Git diff/status trước task đã có nhiều thay đổi/untracked từ phiên trước. Giữ nguyên; baseline ở `artifacts/tts-setup/before-*`. Tracked `git diff --stat` toàn workspace: **15 files changed, 132 insertions(+), 15 deletions(-)** (baseline 130 insertions); TTS/scripts/tests/docs phần lớn đã untracked từ trước, vì thế stat này không mô tả toàn bộ code mới. [Snapshot stat](../artifacts/tts-setup/after-diff-stat.txt) và [status](../artifacts/tts-setup/after-status.txt).

Đối chiếu SHA trước/sau xác nhận `engine.py`, `parallel.py`, `process_engine.py`, model `catalog.py`, `version.py` và `.release-state/journal.json` không đổi. `pip freeze` giữ nguyên. HEAD vẫn `92cbacd1633630bdc4b0e656165e764c2efb52da`; không commit tự động.

## 9. Release readiness và giới hạn build

**Kết luận: PARTIAL.** Subtask build/frozen nghiệm thu **BLOCKED bởi quyền build hiện tại**: `TransComic.spec` yêu cầu marker `permission=BUILD_LOCAL`, Inno yêu cầu `BUILD_LOCAL`, và yêu cầu này giữ quy tắc không build EXE nếu chưa được cấp quyền riêng. Không tự tạo marker/bypass gate. Đã chuẩn bị resource collection/CPU profile và test harness độc lập; chưa chạy PyInstaller/ISCC/Installer.

Không kết luận READY FOR PUBLIC RELEASE. Version vẫn **1.0.4**, repo vẫn `Thnhphngz/TransComic-Releases`; không commit, push, release BAT/Auto Release, tạo tag/Release, upload Installer hoặc sửa journal. Python embedded/DLL tải cho test là upstream runtime artifacts, không phải TransComic EXE build/phát hành mới.

## 10. Bước nghiệm thu tiếp theo cho người duy trì

1. Hoàn tất license/notices/corresponding-source và terms download trước khi phân phối.
2. Cấp quyền riêng cho **BUILD_LOCAL nội bộ**, dùng môi trường build CPU độc lập với `.venv` GPU hiện có; kiểm tra frozen app có đủ worker source/catalog/codec/Qt resources.
3. Trên Windows 10/11 x64 sạch không Python/model/runtime: cài nội bộ, bấm **Tải model** một lần, tạo/phát WAV/MP3, restart không download, kiểm tra thiếu mạng/cancel/retry/VC runtime và giữ dữ liệu khi update 1.0.4. Test GPU bằng phần cứng NVIDIA thật; VM CPU không chứng minh CUDA.

Các bước này dành cho nghiệm thu release của người duy trì, không phải thao tác kỹ thuật bắt người dùng cuối làm. Chỉ chốt version public khi người dùng phê duyệt.
