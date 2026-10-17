# TransComic v1.1.0 — release gates

17/10/2026. Phạm vi được chủ sở hữu cấp quyền: build, commit/push/tag và phát hành công khai v1.1.0 khi các gate đạt. Không chạy Auto Release để tránh tự chọn version khác. Không cài lên host, gọi API dịch trả phí hoặc dùng dữ liệu người dùng.

## Updater v1.0.4 thực tế

Đọc PYZ và thực thi module updater từ EXE công khai, SHA-256 `bd9beeced901f6ae268586ce8daa699af8b7a0e613d379b237c33b58dcd78924`. Sandbox cài từ Installer công khai cũng thu đúng SHA này trước nâng cấp. Không chỉ đọc source mới.

- Endpoint: `https://api.github.com/repos/Thnhphngz/TransComic-Releases/releases/latest`.
- SemVer nhận 1.1.0 mới hơn 1.0.4. Installer canonical: `TransComic-Setup-1.1.0-windows-x64.exe`, dưới giới hạn 512 MiB.
- `transcomic-update.json`: metadata format 2, policy/channel `internal`, HTTPS và SHA-256. Không đổi sang manifest ký số mà bản cũ không hiểu.
- `SHA256SUMS.txt` giữ đúng hai mục: Installer và manifest. Source ZIP và build-manifest dùng `ThirdParty-SHA256SUMS.txt` riêng.
- Code cũ đã check/download/confirm lại tag+manifest+checksums/prepare plan/helper.validate với bytes Installer mới. AppId, per-user install path và mutex giữ nguyên.
- Native helper chờ đúng process thoát an toàn, giữ file Installer đã xác minh, dùng `/VERYSILENT /NORESTART /SP- /SUPPRESSMSGBOXES /DIR=...`, kiểm tra version/registration và startup receipt trước báo COMPLETED. Không xóa profile/cache.

## Kết quả trước publish

| Gate | Bằng chứng |
|---|---|
| Focused | 203 PASS |
| Full offline | 1.298 PASS, 573,36 giây; chặn HTTP dịch thật |
| Build | CPU venv riêng, lock pins, PyInstaller/Inno; 210,22 giây |
| Metadata | GUI/app/helper/Installer 1.1.0; PE 1.1.0.0; AppId giữ nguyên |
| Frozen GUI | Light/Dark, DPR thực 1,0 / 1,25 / 1,5; TXT/DOCX/export/search/undo/queue/popup update/Safe Exit PASS |
| CPU thật | 4 WAV + 4 MP3, playback/restart/history; cache không HTTP; 24 audio cũ giữ SHA |
| CUDA thật | 1.950 node GPU, overlap peak 2 lane; WAV/MP3/playback/restart; cache không HTTP; 24 audio cũ giữ SHA |
| Sandbox sạch | Không Python registry, CUDA Toolkit hoặc MSVC CRT trong System32; cài mới candidate, xác minh binary v1.0.4 từ Installer công khai, nâng lên v1.1.0 PASS |
| One-click sạch | Tải artifact chính thức từ profile rỗng; inference CPU/WAV/MP3/playback/restart PASS; setup lần hai không HTTP |
| Data | SQLite/settings/source mẫu giữ SHA sau native upgrade; toàn bộ profile TTS/model/voice/runtime/audio giữ SHA sau reinstall |
| Source/notices | Kit 528 file, 33 component; manifest `6faf423c209a7331664a4e97d5770d84c572e07f84525fe96282e203a006a025`; native payload 131 DLL/PYD, không ORT/CUDA/Qt Virtual Keyboard/PDF trong GUI |

Một lượt GUI đặt scale trực tiếp 1,5 trên Windows có DPR nền 1,25 đã tạo DPR 1,875 và chạm assertion về sidebar. Giữ log lỗi; ba lượt sau chuẩn hóa scale theo DPR Windows đều đạt đúng 100/125/150%. Không dùng lượt 187,5% làm bằng chứng cho 150%.

## Artifact

- Installer: `TransComic-Setup-1.1.0-windows-x64.exe`, 314.030.052 byte.
- SHA-256: `02a9f7edbb5cc7afaa2d421e30d25faefe058b07701487bb75acd5fd09c71a6e`.
- **UNSIGNED**. Không có chứng chỉ Authenticode; không tuyên bố Windows đã tin cậy publisher.
- App/helper x64; Inno bootstrap x86, target Windows x64.
- Kit có source/build scripts/notices/terms và quyền thay thư viện; chỉ worker copies được cấp GPL-3.0-or-later, không tự đổi giấy phép toàn GUI.

## Provenance và Git

Yêu cầu lần này đặt kiểm thử artifact trước commit. Build sử dụng snapshot source đã scan và ghi SHA của từng input; sau gate, chỉ commit source/docs/tests được phân loại. Manifest công khai gắn final source commit và đối chiếu từng input với snapshot. Không gọi snapshot chưa commit là clean commit tại thời điểm build.

Repository phát hành trước đây chỉ có README trên main và không có remote trong clone source. Nhiệm vụ này cấp quyền push source. Dùng đúng `origin=https://github.com/Thnhphngz/TransComic-Releases.git`, giữ lịch sử source và lịch sử remote bằng merge, không force-push hay sửa tag/release cũ. Scan toàn bộ 488 blob lịch sử trước push không phát hiện credential theo bộ lọc release. JSON catalog/calibration và CUDA lock được thêm vào allowlist chính xác; JSON tùy ý vẫn bị từ chối.

## Giới hạn và hậu kiểm

Evidence riêng trong `artifacts/release-1.1.0`, `artifacts/windows-distribution/frozen-v110-*.json` và thư mục Sandbox được metadata trỏ tới; không upload profile, logs riêng, DB hoặc API keys.

Kết quả Sandbox không phải **REAL MACHINE UPDATE PASS**. Sau publish cần xác minh latest/anonymous download bằng updater trong binary 1.0.4 và thử GUI update trong môi trường riêng nếu khả dụng. Laptop thứ hai và nghe trực tiếp Bluetooth: **AWAITING USER UPDATE TEST**. Không đồng bộ dữ liệu giữa hai máy.

Người dùng máy thứ hai: mở v1.0.4 → Kiểm tra cập nhật → tải/cài v1.1.0 → mở lại → TTS → Cài đặt → Tải model nếu cần. Không gỡ bản cũ.
