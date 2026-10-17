# TTS V4.1 — audio output, history, checkbox và Undo

TransComic **1.0.4**, source hotfix, 17/10/2026. Các lượt thử dùng SQLite và TXT/DOCX/audio fixture ngoài dữ liệu người dùng. Không gọi API dịch.

## 1. Audio output

Backend là **Qt Multimedia 6.11.1 / QMediaPlayer + QAudioOutput**, FFmpeg/WASAPI trên Windows; WAV, MP3, card và popup dùng chung một controller. Mã cũ tạo output duy nhất lúc mở trang và không đăng ký thông báo thay đổi thiết bị. Qt chụp default thành endpoint cụ thể tại constructor, không tự giữ một “default động”: vì vậy sau khi đổi mặc định/kết nối tai nghe, endpoint cũ có thể vẫn là loa. Đây là lỗi vòng đời đã xác định từ mã; không có log phiên trước để khẳng định mọi trường hợp người dùng nghe qua loa đều có cùng nguyên nhân.

Nguồn chính thức: [Qt 6.11.1 QAudioOutput constructor/setDevice](https://github.com/qt/qtmultimedia/blob/v6.11.1/src/multimedia/audio/qaudiooutput.cpp), [QMediaDevices thông báo default/output thay đổi](https://doc.qt.io/qt-6/qmediadevices.html). Qt Windows theo dõi default role **eMultimedia**, xem [nguồn Windows](https://github.com/qt/qtmultimedia/blob/v6.11.1/src/multimedia/windows/qwindowsaudiodevices.cpp).

Hotfix tạo output mới cho mỗi audio mới, giữ volume/mute, gỡ output cũ trước khi gắn output mới. Không chọn index 0, không lưu ID endpoint, không sửa Windows default hay Volume Mixer. Resume cùng nguồn/thiết bị giữ output hiện tại; tránh stop/recreate ngay khi backend còn đang khởi động. `audioOutputsChanged` được nhận qua queued connection, so sánh default và danh sách ID: thay đổi sẽ **dừng và bỏ source**, tạo output mới, thông báo nhấn Phát lại. Không tự chuyển bài đang nghe sang loa hoặc phát chồng. Không có output hợp lệ thì dừng và báo lỗi; không ảnh hưởng worker TTS. Không thêm dropdown chọn thiết bị.

Windows hiện liệt kê **Headphones (ROBOT RB510)** là default và **Speakers (Realtek(R) Audio)** là đầu ra còn lại. Kết quả phát thực tế được ghi trong phần kiểm thử bên dưới. Agent kiểm tra endpoint Qt chọn, duration/position/state và giải mã; không thể xác nhận bằng tai âm thanh vật lý. Đổi Windows default, ngắt Bluetooth và cấu hình output riêng của ứng dụng không bị tự động thao tác trên máy người dùng. Các tình huống đó được mô phỏng; kiểm chứng routing riêng trong Volume Mixer và nghe trực tiếp là **PARTIAL**.

## 2. Lịch sử và xóa toàn bộ

Nguyên nhân: HistoryPanel SELECT tất cả documents, gồm tài liệu nháp đã persist khi import. Clear lại kiểm tra tất cả runs có tài liệu, nên draft ngăn xóa ngay cả khi mọi history đã kết thúc. Nút header `⋯` còn cần mở menu trung gian.

Thêm cột TTS SQLite **runs.history_accepted INTEGER NOT NULL DEFAULT 0**, idempotent. Scheduler chỉ đánh dấu khi Start đã qua kiểm tra trạng thái, ngôn ngữ/voice và có segment đủ điều kiện, ngay trước khi khởi động coordinator; nếu thread không khởi động được thì phục hồi flag. Lỗi runtime/reconcile sau Start đã chấp nhận vẫn có lịch sử. Import, folder scan, sửa nháp, preview, đổi voice/speed, cancel picker, lỗi xác nhận output không đánh dấu. Không đổi bảng dịch/API scheduler.

Migration giữ lịch sử legacy không phải draft (kể cả ready), lượt đã có started hoặc segment success/hash, kể cả audio ở một run mang trạng thái draft. Do schema cũ không ghi sự kiện Start riêng, một checkpoint legacy không phải draft không thể luôn phân biệt với output đã chuẩn bị nhưng chưa chạy; ưu tiên giữ nó. Không xóa hàng cũ và không coi audio có bằng chứng đã tạo là nháp để ẩn. Flag mới chỉ lọc card, dữ liệu nháp vẫn ở database/danh sách file.

Header có nút trực tiếp **Xóa lịch sử**, tooltip **Xóa toàn bộ lịch sử TTS**; menu từng card giữ nguyên. Dialog **Xóa toàn bộ lịch sử TTS?** nêu rõ chỉ xóa metadata, giữ audio/tài liệu gốc và không thể hoàn tác, áp dụng cả ngoài bộ lọc. Nút **Hủy** mặc định/Esc; **Xóa lịch sử** màu đỏ, destructive role. Chặn đang chạy và history paused/recoverable, không tự hủy; Completed/Cancelled/Failed được xóa. Draft không bị xóa hoặc chặn thao tác. Xóa bằng transaction SQLite/cascade metadata, không unlink file/folder/model/runtime. Popup mất record đóng an toàn.

## 3. Checkbox và focus

Checkbox mặc định Qt delegate được canh bên trái ô. `CenterCheckDelegate` lấy kích thước indicator từ style, căn theo tâm visualRect ở cả hai chiều; native scale/DPR thực hiện phần raster. Nhấn toàn ô checkbox hoặc Space đổi đúng stable row ID, không tạo checkbox widget mỗi hàng. Header chọn tất cả giữ nguyên.

Viền focus cell xuất phát từ State_HasFocus của native item view painting. `TtsTable`/`TtsDelegate` chỉ áp dụng các bảng TTS: bỏ focus rect native, giữ nền chọn hàng và bổ sung nét chấm mảnh màu accent khi vào bằng Tab hoặc dùng bàn phím. Không đặt NoFocus, không chặn mũi tên/Tab hoặc editor. Action/checkbox delegate cũng có cue bàn phím. Không thay stylesheet trang Dịch/SRT/Queue.

## 4. Ctrl+Z trong Chi tiết

Editor delegate là **QLineEdit** native: Undo trong lúc sửa vẫn do Qt xử lý. Khi Enter/chuyển ô hủy editor, Ctrl+Z trên `TtsTable` gọi Undo tối thiểu cho **lần commit gần nhất**. Model giữ segment/document/run ID, text trước/sau và revision dự kiến; chỉ Undo khi ID có trong scope hiện tại, revision/text vẫn khớp và run không chạy/pausing/stopping/cancelled. Commit và Undo gọi cùng store.edit, tăng revision, đưa đoạn về pending và đồng bộ bảng/store; không phục hồi audio cũ thành success và không thay filename/checkpoint/đánh số.

Không có chuỗi Undo nhiều lần hoặc Redo sau commit. Sửa bên ngoài đổi revision, xóa segment hoặc chuyển sang tài liệu khác thì Undo từ chối, không tìm hàng theo chỉ số hiển thị. Khi worker chạy, editor/Undo bị khóa; không thay snapshot inference.

## 5. Giải thích hai Settings — giữ nguyên code/hành vi

**Adapter tự động** là giá trị `device_id=-1`, lựa chọn adapter cho GPU execution provider, không phải thiết bị âm thanh. Với **CUDA**, Auto dùng NVIDIA ordinal **0**; không đưa DXGI index của Intel vào CUDA. Với **DirectML**, `preferred_device()` chọn DXGI adapter có dedicated memory lớn nhất (fallback 0). Giá trị adapter cụ thể truyền cho provider; không làm cho provider vốn không có trong runtime xuất hiện. Backend Auto chọn CUDA nếu có, chỉ chọn DirectML khi không có CUDA; không có GPU provider thì CPU. Nếu GPU probe/khởi tạo thất bại, Auto chuyển CPU, không tự thử DirectML thứ hai. Không có việc Intel CPU và NVIDIA GPU tự chạy chung chỉ vì chọn Auto. Máy này vẫn dùng CUDA đã xác minh, số lane vẫn do cấu hình/benchmark/resource gate riêng quyết định.

**Tiêu chuẩn · 326 MB + voice** chọn variant `standard`, file ONNX `onnx/model.onnx` **325.532.232 byte**, khoảng 325,5 MB thập phân (310,5 MiB), nhãn 326 MB làm tròn. Đây là dung lượng model đĩa/download, **không** phải RAM/VRAM/runtime hay phí. Variant nhẹ hiện có là quantized 92.361.116 byte; hotfix không đổi lựa chọn/mặc định này. `+ voice` là dữ liệu conditioning của các giọng Kokoro, không phải voice cloning/model engine mới: catalog hiện có **54 bin × 522.240 byte = 28.200.960 byte**, cài kèm bộ voice đã checksum. Standard + voice tổng **353.733.192 byte** trước derived cache/runtime.

`ModelManager` lưu theo revision cố định `1939ad2a8e416c0acfeecc08a694d14ef25f2231`, kiểm tra size/SHA256; voice được ghép thành `verified-voices.npz` cùng metadata hash để dùng lại. Cache model/voice tách khỏi phiên bản ứng dụng. Update app không tự tải lại asset còn đúng revision/hash; Install bỏ qua file hợp lệ, chỉ tải asset thiếu/hỏng. Revision mới hoặc chủ động gỡ model có thể cần tải lại. Không thay hai control Settings, catalog, engine, DLL/runtime/provider options hay dependencies trong V4.1.

## 6. Kết quả kiểm thử

**GUI native: PASS 6/6 cấu hình**, Light/Dark × DPR 1/1,25/1,5. Kiểm tra centered checkbox ở hàng cao, click ngoài mép indicator vẫn đúng tài liệu, không focus rect trắng, editor commit/Undo, popup, clear confirmation, resize 900×580 và maximized, player không đổi hình học card. Ảnh được mở kiểm tra trực tiếp; JSON/screenshot ở `artifacts/tts-v41/native`.

**CUDA thật: PASS**, normal launcher `python run_transcomic.py --tts-v4-smoke ...`, external fixture/cache, không HTTP. DOCX 20/20, pause/resume giữ hash 4 audio. Timeline ghi peak **2 session.run chồng thời gian ở host**; không tuyên bố đã profile CUDA kernel overlap. Runtime GPU 1.24.4, probe xác minh **1.950 node CUDA**, session CUDA + CPU. Hủy active=2 mất **0,217 giây**, giữ 1 audio, không orphan/late commit; reopen giữ cancelled. MP3 một đoạn, editor đổi tên/text tạo WAV job mới 3 đoạn, collision/persistence/shared popup/player đều qua. Clear giữ hash **25 audio**. [Report CUDA](../artifacts/tts-v41/real-gpu/report.json).

**WAV/MP3 routing: PASS ở mức endpoint/backend**, file thật phát tiến triển trên `Headphones (ROBOT RB510)`, trùng Qt default tại playback; không chọn loa Realtek. Đóng × dừng độc lập inference; popup/card dùng cùng player. **PARTIAL** cho nghe bằng tai, đổi default vật lý, Bluetooth unplug và Volume Mixer override: không tự thay thiết lập Windows hoặc ngắt thiết bị người dùng. Mock test có device-change/no-output/không tự resume, không lấy bằng chứng này thay cho hardware test.

Regression mới **7/7 PASS**: import/edit/picker cancel/output failure không có history, invalid voice không chấp nhận, runtime failure sau Start giữ history; migration legacy audio hai lần; clear No/Yes đúng nút thật và truy vấn SQLite connection khác, giữ draft/source/audio; checkbox và keyboard focus; native/committed Undo và revision/document fence; đổi/mất output. Regression GUI cũ đã cập nhật **29/29 PASS**.

Sau khi cả hai normal-launcher GUI process thoát, mở lại **TtsStore** trên từng database fixture: history/documents đều **0**, mỗi root vẫn có **25 audio**. Lưu danh sách SHA256 sau mở lại trong [history-reopen.json](../artifacts/tts-v41/history-reopen.json), xác minh clear không chỉ là ẩn card trong phiên GUI hiện tại.

**CPU fallback thật: PASS**, cố ý làm khởi tạo GPU lỗi trong harness rồi chạy inference/encode/playback CPU thực. DOCX 20/20, pause/resume giữ hash 3 audio; hủy active=1 mất **0,119 giây**, giữ 1 audio, không orphan/late commit, cancelled giữ sau mở lại; MP3/WAV/editor job mới và clear giữ 25 audio. WAV/MP3 đều chọn endpoint ROBOT RB510. [Report CPU](../artifacts/tts-v41/real-cpu/report.json). Injection chỉ nằm trong harness opt-in, không thay engine/môi trường sản xuất.

**Focused toàn bộ TTS: 100 passed, 80,42 giây**, gồm core/output/identity, acceleration/parallel, runtime và GUI V4/V4.1. [Log focused](../artifacts/tts-v41/focused.log).

**Full offline cuối: PASS — 1.238 passed, 490,43 giây (8 phút 10 giây)**, gồm regression Kira/Gemini/translation/export/update, core TTS và GUI. [Log full cuối](../artifacts/tts-v41/full-offline-final.log). Môi trường test đặt `.venv/Scripts` đầu PATH, `TRANSCOMIC_RELEASE_OFFLINE_TESTS=1`; fixture/runtime bên ngoài workspace, không gọi dịch trả phí.

Lượt full hoàn chỉnh trước đó có **1.237 pass, 1 fail** ở fixture audio mới: tone 100 ms có thể kết thúc trước Qt position notification, khiến assert playback không ổn định khi suite lớn. Đã kéo fixture thành **3 giây**, giữ nguyên assertion/routing code; regression V4.1 chạy lại **7/7 PASS** (lần cuối sau bổ sung bảo toàn legacy ready: **5,32 giây**). [Log lần full phát hiện fixture timing](../artifacts/tts-v41/full-offline-fixture-timing.log). Full cuối ở trên đã bao gồm cả sửa fixture và migration cuối.

Không dùng benchmark 31,7% của phiên trước làm số đo hotfix. Lượt full trước đó bị gián đoạn để sửa **PATH của tiến trình kiểm thử**: test BAT fixture gọi Python hệ thống thiếu cryptography khi `.venv/Scripts` chưa đứng đầu PATH. Hai test đó chạy lại **2/2 PASS** sau khi sửa environment của test, không cài dependency hoặc sửa release code.

## 7. Files và giới hạn phát hành

- Production: `transcomic/tts/player.py`, `storage.py`, `scheduler.py`; `transcomic/ui/tts_page.py`, `tts_history.py`, `tts_models.py`, `tts_audio_dialog.py`.
- Tests: mới `tests/test_tts_v41.py`; sửa fixture/expectations `test_tts_gui.py`, `test_tts_hotfix_gui.py`, `test_tts_v4_gui.py` để không mặc định coi import là history. Các test card/popup dùng accepted fixture rõ ràng.
- Harness: `scripts/tts_gui_check.py`, `transcomic/tts/v4_smoke.py` bổ sung checkbox, editor, confirmation, endpoint và nút dialog mới.
- Docs: báo cáo này và `docs/tts-workflow.md`. Workspace đã có thay đổi chưa commit từ nhiều task trước; diff tracked toàn repo không phải chỉ hotfix.

Giữ **1.0.4**, không commit, không chạy release BAT/Auto Release của project, không build EXE/Installer, không publish GitHub. Full regression có test launcher/release giả trong thư mục fixture riêng, không phát hành project thật. Không chỉnh release journal, API key, database/audio/model người dùng hoặc môi trường CUDA. Snapshot trước task: `artifacts/tts-v41/before-*`.

Hash đối chiếu xác nhận **engine.py, process_engine.py, parallel.py, catalog.py, version.py và release journal không đổi**, `pip freeze` giống hệt trước task. HEAD vẫn `92cbacd1633630bdc4b0e656165e764c2efb52da`. [Environment/hash audit](../artifacts/tts-v41/after-environment.json).

`git diff --stat` tracked toàn workspace: **15 files, 130 insertions, 15 deletions**, giống baseline trước hotfix do các file TTS đã untracked sẵn. Không stage chúng để tạo diff. Xem [tracked diff stat](../artifacts/tts-v41/after-diff-stat.txt), [git status](../artifacts/tts-v41/after-status.txt), `before-hashes.json` và `after-hashes.json` để đối chiếu đúng 8 source/harness TTS thay đổi trong task này.

## 8. Ảnh nghiệm thu native

| Nội dung | Light 100% | Dark 150% |
|---|---|---|
| Hàng chọn, checkbox giữa, lịch sử trực tiếp | [ảnh](../artifacts/tts-v41/native/light-1-selected-centered-checkbox.png) | [ảnh](../artifacts/tts-v41/native/dark-1.5-selected-centered-checkbox.png) |
| Xác nhận xóa | [ảnh](../artifacts/tts-v41/native/light-1-clear-confirm.png) | [ảnh](../artifacts/tts-v41/native/dark-1.5-clear-confirm.png) |
| Chi tiết đang sửa | [ảnh](../artifacts/tts-v41/native/light-1-details-editing.png) | [ảnh](../artifacts/tts-v41/native/dark-1.5-details-editing.png) |
| Player chung | [ảnh](../artifacts/tts-v41/native/light-1-player.png) | [ảnh](../artifacts/tts-v41/native/dark-1.5-player.png) |

Thư mục `artifacts/tts-v41/native` có đủ Light/Dark × 100/125/150%, popup, input/settings, cửa sổ 900×580 và maximized; JSON ghi DPR thực tế và assertion geometry/click/editor/output.
