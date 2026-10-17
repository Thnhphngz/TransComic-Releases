# Windows distribution và One-click TTS — 17/10/2026

## A. Đã sửa gì?

- `TransComic.spec`: chuyển GUI sang dạng thư mục, để thư viện Qt/audio có thể thay thế; không đưa ORT, Kokoro, phonemizer/eSpeak hoặc CUDA vào GUI. Updater helper vẫn nằm cạnh EXE.
- `scripts/tts_packaging.py`: lọc PDF/Virtual Keyboard không dùng, audit DLL/PYD thực tế trước Inno. Payload cuối có **131 DLL/PYD**, gồm 14 thư viện Qt đã đối chiếu source, không có DLL CUDA.
- `scripts/build_local.py`: bắt buộc source/notices kit hợp lệ, kiểm tra SHA và source worker/bootstrap, audit payload rồi mới tạo Installer. Build không cài đặt hoặc publish.
- `installer/TransComic.iss`: cài toàn bộ thư mục ứng dụng và ThirdParty; giữ AppId, vị trí per-user, chính sách upgrade và dữ liệu ngoài thư mục cài đặt.
- `managed_engine.py`: xử lý đường dẫn Windows dài, dữ liệu eSpeak/MeCab tương đối. Phát hiện thêm trên Sandbox: Python embedded thiếu MSVC C++ runtime mà ORT cần. Bản sửa source mới cho worker đăng ký `_internal` và `_internal/PySide6` bằng `AddDllDirectory`, giữ handle đến hết process. Không sửa PATH/System32, không cài redistributable hệ thống, không sửa runtime cache đã xác minh.
- `concurrency.py` và TTS page: Auto dùng metadata runtime đã probe từ process riêng khi GUI không chứa ORT; config tạm không được lưu vào preset.
- `distribution_smoke.py`: opt-in chỉ cho frozen EXE và profile thử riêng; chỉ cho HTTP artifact chính thức, chụp GUI, tạo/phát WAV/MP3, restart và kiểm tra cache. Khi setup lỗi, báo cáo mới có cả log kỹ thuật.

Các engine/scheduler cũ, lease/ID, catalog pin và giới hạn hai worker được giữ nguyên.

## B. Hồ sơ phân phối

Kit thực tế gồm **528 file**: source upstream đã pin, source/build scripts, worker/bootstrap tương ứng, notices/attribution, license và hướng dẫn thay thư viện. Không chỉ hứa cung cấp source sau.

- Qt/PySide/shiboken, FFmpeg, libsndfile/codecs và LAME dùng thư viện ngoài EXE; nguồn tương ứng và hướng dẫn thay thế đi kèm.
- Source tám file worker và bootstrap được cấp GPL-3.0-or-later cho các bản sao worker được giao. Không đổi giấy phép toàn bộ GUI/dịch/updater.
- Model/voice, Python embedded, ORT, phonemizer/eSpeak và dictionary được tải từ upstream đã pin, có SHA-256. NVIDIA tải trực tiếp từ nguồn PyPI chính thức; không đưa DLL GPU vào Installer CPU. Không cài driver hoặc Toolkit.
- Điều kiện Microsoft, NVIDIA và license thành phần được cung cấp; liên kết điều khoản nằm cạnh nút Tải model.
- Virtual Keyboard GPL-only không dùng được loại khỏi payload. Corresponding source khớp bootstrap mới nằm trong `artifacts/windows-distribution/compliance-crt-fix`; manifest SHA-256: `96c2ead7a49527f55d82db495eaf45c548e7310a61de775d6fb4b4b05cd96bca`.

Chi tiết: [quyền và source](windows-distribution-rights.md), [license TTS](tts-licenses.md). Các audit RC cũ được giữ làm lịch sử.

## C. Installer đã tạo

**Lượt 3 đã tích hợp bản sửa MSVC và đạt kiểm thử native trong Windows Sandbox sạch.** Đây là lượt đóng gói bổ sung được người dùng duyệt riêng, dùng để bàn giao thử nội bộ.

| Thuộc tính | Lượt đóng gói cuối |
|---|---|
| File | `artifacts/windows-distribution/internal-build-crt-fixed/installer/TransComic-Setup-1.0.4-devtest-windows-x64.exe` |
| Dung lượng | **314.043.221 byte / 299,49 MiB** |
| SHA-256 | `b3f791dbc13570c70ff160bba8c03ae9dd82503c2e962cf898860f6e1618a632` |
| Thời gian | **163,75 giây** |
| Version | 1.0.4, file version 1.0.4.0 |
| Kiến trúc | payload/helper x64; Inno bootstrap x86, chỉ cài Windows x64 |
| Chữ ký | **Unsigned**, Authenticode NotSigned |
| Build | CPU venv riêng, lock pin hợp lệ, source/notices và native payload gate PASS |

Tổng cộng **ba lượt build**, mỗi lượt đều có quyền tương ứng: một lượt ban đầu và hai lượt bổ sung được duyệt riêng. Không tự chạy thêm build. Lượt 1 chứa Virtual Keyboard không dùng; lượt 2 đã loại chúng nhưng Sandbox phát hiện thiếu đường dẫn CRT ở worker. Hai artifact cũ được giữ để đối chiếu, không dùng để bàn giao.

Kit nêu ở mục B đã nằm trong Installer cuối, dưới `ThirdParty`. Dung lượng bao gồm source/notices tương ứng. File `SHA256SUMS.txt` nằm cạnh Installer. Artifact công khai trong `releases/1.0.4` không bị thay thế.

## D. One-click TTS

Luồng người dùng: **Text to Speech → Cài đặt → Tải model**. Ứng dụng tự tải model/voice, Python embedded và runtime phù hợp; kiểm tra size/SHA, chạy inference và xác minh WAV/MP3 trước khi báo Sẵn sàng.

Máy NVIDIA tương thích ưu tiên CUDA, có CPU fallback; máy CPU không cần GPU pack. Người dùng không cần cài Python, pip, CUDA Toolkit, cuDNN hoặc tự chép DLL. GPU vẫn cần driver phù hợp đã có sẵn.

Model và runtime ở `%LOCALAPPDATA%\TransComic\TTS\Models` và `Runtimes`; history/settings ở dữ liệu ứng dụng. Audio theo thư mục xuất của lượt tạo, nằm ngoài thư mục cài đặt. Cache hợp lệ được dùng lại sau restart/update. Không hứa chuyển dữ liệu/API key giữa hai máy; Windows DPAPI vẫn ràng buộc tài khoản/máy.

## E. Kiểm thử và giới hạn bằng chứng

| Kiểm tra | Kết quả |
|---|---|
| Focused sau bộ lọc DLL | **93 PASS**, 3,10 giây |
| Full offline trước build lượt 2 | **1.294 PASS**, 550,90 giây |
| Focused sau sửa MSVC | **126 PASS**, 8,49 giây |
| Full offline sau sửa MSVC | **1.296 PASS**, 506,95 giây; xem `full-offline-crt-fix.log` và XML |
| Artifact upstream | **95/95 SHA-256 PASS** |
| EXE cuối, editor ngoài checkout | PASS: TXT/DOCX, export, search/undo, queue clear, Light/Dark, updater mock, Safe Exit |
| EXE cuối, CPU trên host | PASS: 4 WAV + 4 MP3, playback, restart, history, không HTTP tải thêm; 16 audio cũ nguyên SHA |
| EXE cuối, CUDA trên host | PASS: 1.950 node GPU, hai lane đồng thời, WAV/MP3, playback, restart, không HTTP tải thêm; 16 audio cũ nguyên SHA |
| Native Installer trong Sandbox sạch | **PASS**: cài bản công khai → nâng cấp lượt 3, seed SQLite/settings/source giữ SHA, uninstall registration và helper self-check đạt |
| One-click trên Sandbox sạch, Installer cuối | **PASS**: 86 request artifact chính thức từ profile rỗng, CPU inference, 4 WAV + 4 MP3, playback, restart, 2 lịch sử, lần setup tiếp theo không HTTP |
| Native reinstall sau tạo TTS | **PASS**: **4.590 file** khớp SHA trước/sau, gồm model/voice/runtime/cache, SQLite/settings, 4 WAV, 4 MP3 và source mẫu |
| Phép thử cô lập nguyên nhân CRT | PASS: máy sạch tái hiện lỗi import khi thiếu đường dẫn CRT; bootstrap mới chạy ORT 1.24.4, 24.064 mẫu, peak 0,729 |
| Kiểm thử artifact lượt 2 trước sửa CRT | FAIL tại probe ORT; giữ lại log lịch sử, không báo Ready giả |

CPU/CUDA trên host là runtime riêng với PATH được làm sạch, không phải bằng chứng máy phát triển là Windows sạch. Sandbox xác nhận không có Python registry hoặc MSVC CRT trong System32, không có CUDA Toolkit. File driver NVIDIA vẫn hiện diện/compute có thể được hệ thống host chuyển tiếp; không gọi đây là máy vật lý CPU-only.

Phép thử cô lập nguyên nhân CRT trước build dùng runtime/model công khai đã xác minh và preseed. Bài nghiệm thu Installer cuối dùng Sandbox mới, **không preseed model/runtime**: chỉ map read-only hai Installer và SQLite/source mẫu. Đã chạy đủ one-click và reinstall, không dùng kết quả source để thay cho kết quả artifact.

NVIDIA trên máy Windows sạch vật lý khác và nghe trực tiếp bằng thiết bị Bluetooth chưa được thực hiện trong phiên này. CUDA hai lane được xác minh trên EXE cuối với runtime riêng, không dùng CUDA Toolkit. Playback tự động xác nhận player tiến thời gian; nghe thực tế trên thiết bị vẫn thuộc nghiệm thu người dùng.

Lần Sandbox đầu dừng trước Installer do script đếm `$null` thành một registry item; đã sửa array guard và giữ log riêng. Những lần sau thu được lỗi ORT thực. Không xóa bằng chứng thất bại.

Bằng chứng: `artifacts/windows-distribution/final-acceptance.json`, `clean-native-acceptance.json`, `sandbox-crt-fixed-test.json`, `frozen-crt-fixed-*.json`, `crt-build-execution.json`, `crt-fixed-signature.json`, build report, full/focused logs và XML. Metadata trỏ đến từng thư mục Sandbox ngoài checkout; manifest trước/sau reinstall được giữ nguyên. Ảnh `ready.png`, `completed.png`, `restart.png` nằm trong thư mục bằng chứng Sandbox.

## F. Dữ liệu và những phần giữ nguyên

- Không mở/sửa/xóa SQLite, API key, audio, model hoặc source tài liệu của người dùng. Thử nghiệm dùng profile và seed tổng hợp riêng.
- `.venv` CUDA không thêm/bớt package; so sánh pip freeze trùng trước/sau. Engine, scheduler, catalog và calibration được giữ nguyên ngoài các sửa bootstrap/Auto mô tả ở mục A.
- Version, HEAD, release journal, Installer công khai và backup còn nguyên SHA. Không commit/push, chạy Auto Release, tạo tag, upload GitHub hoặc tăng version.
- Seed SQLite/settings/source được giữ khi native upgrade; toàn bộ profile TTS mẫu 4.590 file giữ SHA sau native reinstall. Profile CPU/CUDA cũ trên host giữ nguyên 16 audio mỗi profile và mở lại đủ lịch sử.
- Các backup, thư mục thử và artifact cũ trên D được giữ lại. Chỉ guest Sandbox mới tạo kết thúc vòng đời của nó; bằng chứng đã xuất ra thư mục riêng.

## G. Release readiness

**READY FOR USER INSTALLER TEST**

Installer cuối chứa bản sửa CRT, đã qua native one-click/restart/reinstall trên Windows Sandbox sạch và frozen CPU/CUDA trên host. Source/notices kit, build CPU riêng và payload đã xác minh; không còn blocker kỹ thuật cụ thể đã phát hiện trong đợt này.

Giữ nguyên 1.0.4, unsigned, không publish hoặc cài đè bản host đang dùng. Chưa kết luận sẵn sàng phát hành công khai. Mỗi lượt build bổ sung đã được báo cáo/duyệt theo Mục 7; không có lượt 4.

## H. Cách nghiệm thu trên máy Windows khác

1. Chép Installer trong mục C sang máy Windows x64 khác; đối chiếu `SHA256SUMS.txt` rồi cài thử. Không dùng hai artifact cũ.
2. Mở Text to Speech → Cài đặt → Tải model; chờ Sẵn sàng.
3. Tạo WAV và MP3 từ văn bản mẫu; kiểm tra player và thiết bị audio mặc định.
4. Đóng/mở lại, kiểm tra history và không tải model/runtime lại.
5. Nếu máy NVIDIA tương thích, kiểm tra CUDA và hai worker trong điều kiện đủ tài nguyên.
6. Chỉ thử update/reinstall sau khi có bản sao dữ liệu thử, đối chiếu history/settings/model/voice/runtime/audio và source.

Không yêu cầu cài Python/CUDA/cuDNN thủ công. Chưa có quyền publish GitHub.
