# Release Candidate 1.0.4 — final audit

> Đây là kết quả RC trước khắc phục. Hồ sơ Windows distribution tiếp theo có
> phạm vi và quyền build mới; xem [quyền phân phối và source đi kèm](windows-distribution-rights.md)
> cùng `artifacts/windows-distribution`. Không dùng trạng thái cũ dưới đây để
> thay cho kết quả kiểm thử artifact mới.

17/10/2026 · **BLOCKED — DO NOT RELEASE** · **0 lần build Installer**. Quyền một Installer nội bộ đã được người dùng cấp **sau khi audit đạt**; license gate chưa đạt nên không chạy PyInstaller/ISCC compile, không tạo Installer RC hoặc cài đè bản đang dùng.

## A. Release Audit

| Hạng mục | Trạng thái | Bằng chứng / giới hạn |
|---|---|---|
| BUILD_LOCAL | PASS, quyền có điều kiện | `scripts/build_local.py` tạo `.build-local.json` trong staging, spec đọc marker; Inno dùng `/DBUILD_LOCAL`. Không bypass guard; marker unit fixture không phải một build sản phẩm. |
| PyInstaller/spec | FAIL cho nghiệm thu RC | Đã sửa thiếu staging helper/catalog/notices và package data; regression staging qua. PyInstaller 6.22.0 / Python 3.13.14 x64 / PySide6 6.11.1 hiện có. Môi trường developer là GPU, target base CPU chưa được chuẩn bị/xác minh riêng; `TTS_CPU_BUILD_REQUIRED` được giữ. Chưa có frozen evidence. |
| Inno Setup | PASS static, native NOT RUN | AppId/dir/architecture/privileges/mutex giữ nguyên; helper `/ ?` xác nhận Inno Setup 6 family, không compile. PE fixed version tool 0.0.0.0 không được báo thành phiên bản Inno thực. [Help](../artifacts/rc-audit/inno-help.txt). |
| License | **FAIL / BLOCKED** | [License audit](release-candidate-license-audit.md), native eSpeak/source provenance và hồ sơ GPL/LGPL/Qt/codecs/redistribution chưa đầy đủ. |
| 95 artifacts | **PASS** | 95 cache đúng hash/size, 95 URL reachable, 95 metadata nguồn khớp pin; target Windows AMD64 / CP313 hoặc pure data. [Machine report](../artifacts/rc-audit/artifacts.json), [platform check](../artifacts/rc-audit/platform-validation.json). |
| Runtime bootstrap | PASS static/source; frozen NOT RUN | Source và runtime độc lập đã chạy; staging có worker sources/catalog/notices. Chưa build frozen nên không gọi đây là PASS trên máy không Python. |
| CPU fallback | PASS source runtime | Smoke mới với injection GPU preparation failure, CPU embedded inference và WAV/MP3 thực. [Report](../artifacts/rc-audit/cpu-fallback-smoke.json). |
| CUDA | PASS source runtime | Smoke mới tự chọn CUDA khi bootstrap ORT được injection là thiếu; GPU thật, ORT 1.24.4, 1.950 CUDA nodes, WAV/MP3. [Report](../artifacts/rc-audit/gpu-smoke.json). |
| Data preservation | PASS static/fixtures, native PARTIAL | Không đổi DB/schema/keys/cache/output. ISS chỉ cài 2 EXE, không UninstallDelete; backup source/config xác minh hash. Chưa nghiệm thu install/update/uninstall thật. |
| Updater | PASS offline contracts, native FAIL/NOT RUN | AppId/repo/path giữ nguyên. RC source và public đều 1.0.4; không được tự offer same-version update. Chưa có Installer RC để thử upgrade. |

Static bootstrap review: `run_transcomic.py` gọi `multiprocessing.freeze_support()`; `dev_runtime.launch()` trả về ngay khi frozen nên không re-exec `.venv`. Spec giữ Qt platform/imageformat/style/SVG/Network và thêm Multimedia; helper TTS gom dictionary/native libraries/metadata, setup catalog và tám worker source riêng. Worker embedded dùng interpreter app-managed và `_pth` cố định, không Python hệ thống. HTTPX/SSL/certifi, SQLite và DOCX dependencies nằm trong build target; sự hiện diện thực tế của mọi DLL/CA bundle phải được kiểm tra trong archive/frozen run sau build, không suy từ static review.

### Repository và backup

Branch `main`, HEAD `92cbacd1633630bdc4b0e656165e764c2efb52da` (Release 1.0.4); trước đó 1.0.3/1.0.2. Source working tree đã dirty và có TTS untracked từ các phiên trước. Không commit/reset/clean. Local tag inventory lưu tại `artifacts/rc-audit/before-tags.txt`; tag phân phối remote thuộc repository khác.

Đã đọc lại GitHub **GET-only** tag `v1.0.4`, public non-draft/non-prerelease, published `2026-10-16T19:09:35Z`. [Remote snapshot](../artifacts/rc-audit/current-public-release.json). Installer cũ: **112.999.091 byte**, SHA-256 `150168af9076a6a7f4e2cab960e7a1797ec1e23a0a876f952c9c487d9fd0e184`, khớp asset digest remote. [Baseline](../artifacts/rc-audit/existing-installer-before.json). Không sửa release/tag/assets.

Backup source/config **326 files**, ZIP đã đọc lại từng entry để đối chiếu SHA, tại `D:/TransComic-SecureBackup/RC-Audit-20261017-c90b3b404e3e43c68a77abe023d51fe3/source-build-backup.zip`; SHA-256 `6f50df5634af6af5bfa29bb7b4e1a8f8e90720cca5c89dea7ef404598645b182`. [Backup scope](../artifacts/rc-audit/backup.json). Không sao chép DB/key/document/audio người dùng; không cần thay đổi dữ liệu thật trong audit này. Không xóa các root backup/archive/runtime.

## B. One-click TTS

Luồng source hiện tại: **Tải model → kiểm tra hệ thống/cache → tải model + 54 voice → chuẩn bị CPU/CUDA → kiểm tra hash/archive/tree → inference thật → kiểm tra WAV và MP3 → Sẵn sàng**. Không thêm wizard hoặc thao tác Python/pip/CUDA/PATH/DLL cho người dùng.

| Phần tải standard | Nguồn | Bytes |
|---|---|---:|
| Model + 54 voice | Hugging Face ONNX Community, revision `1939ad2a8e416c0acfeecc08a694d14ef25f2231` | 353.733.192 |
| CPU embedded + dependencies khi base thiếu CPU runtime | Python.org + PyPI, pin exact version/SHA | 127.798.682 |
| GPU embedded + dependencies khi cần | Python.org + PyPI NVIDIA/ORT pins đã kiểm chứng | 2.003.058.653 |

Cold total standard/CPU **481.531.874 bytes**, standard/GPU **2.356.791.845 bytes**; không phải dung lượng giải nén. Light model tùy chọn 92.361.116 bytes, không thêm model mới. [Bảng từng artifact](tts-setup-artifacts.md). Lượt RC dùng HEAD/metadata và hash cache: **không tải lại payload của 95 artifact**, không dùng `.download.part`. Chỉ tải thêm một archive nguồn provenance Windows **427.032 bytes** và checksum/metadata nhỏ để so sánh eSpeak native; không chạy/thay binary, không đổi catalog runtime.

Cache ở `%LOCALAPPDATA%/TransComic/TTS/Models/<revision>` và `Runtimes/Downloads/<SHA>`, runtime activated trong `Runtimes/<catalog-worker-hash>-cpu|cuda`. NVIDIA tương thích được thử CUDA bằng Driver API và inference thật; không có/khởi tạo thất bại dùng CPU hợp lệ. Runtime không báo Ready chỉ vì download 100%. Hai worker hiện tại không đổi; không thử 3–4 worker.

## C. Build và Installer

**Chưa build.** Một lượt build được giữ nguyên vì điều kiện audit chưa đạt. Installer RC filename/path/size/SHA/time/signature: **N/A**. Không gọi EXE cũ là bản RC mới. [Quyết định machine-readable](../artifacts/rc-audit/release-gate.json) giữ `builds_attempted=0`, `public_release_allowed=false`. Exit 0 của tiện ích artifact audit chỉ xác nhận artifact check, không cấp quyền vượt license gate.

Đường local test hợp lệ là `build_local.py` (dirty snapshot có hashes), output thư mục duy nhất chưa tồn tại; convention hiện có là `TransComic-Setup-1.0.4-devtest-windows-x64.exe`. Không dùng canonical `--release-build` yêu cầu clean commit, vì người dùng cấm commit và đây là local RC. Không dùng Auto Release hoặc tạo metadata/tag public cho RC cùng version.

Inno hiện tại: AppId `{CB58C770-47B7-42DC-A2CA-409DDF456487}`, mặc định `{localappdata}/Programs/TransComic`, per-user `PrivilegesRequired=lowest`, x64compatible, Windows 10+, mutex `TransComic.Desktop.Running`, `UsePreviousAppDir=yes`. Start Menu shortcut có, Desktop tùy chọn mặc định bỏ chọn; không file association mới. `[Files]` chỉ app EXE + update helper. AppPublisher không được khai riêng; không tự thêm publisher/certificate.

Cấu hình chưa có Authenticode signing; SignTool không được phát hiện. Installer public cũ `NotSigned`, signer null theo [inspection](../artifacts/rc-audit/existing-installer-signature.json); trạng thái đó không phải chữ ký của RC chưa tồn tại. Hash/Ed25519 update metadata không thay Authenticode. Không khẳng định Windows/SmartScreen tin cậy; warning/policy vẫn cần nghiệm thu trên máy đích.

## D. Windows clean install

**BLOCKED** vì chưa được qua gate để build. Kiểm thử native Installer trong máy cách ly: **NOT RUN**. Windows sạch không Python/model/runtime: **NOT RUN**, không PASS. Các cache/test root đã tồn tại chỉ được dùng cho audit và smoke revalidation, không làm bằng chứng fresh install mới. Không dùng VM không GPU passthrough làm bằng chứng CUDA.

## E. Kiểm thử

- Focused packaging/staging, permission separation, runtime/setup/checksum, updater readiness: **71 PASS, 34,14 giây**. [Log](../artifacts/rc-audit/focused-verified.log).
- Full offline sau sửa đóng gói: **1.275 PASS, 753,75 giây (12:33), exit 0**, [log](../artifacts/rc-audit/full-offline.log). Không có smoke runtime hoặc hash cache hàng GB chạy song song.
- CPU fallback và CUDA smoke mới: **PASS**, WAV/MP3 encode/decode, HTTP bị chặn; parent ORT missing và GPU failure là injection được ghi rõ, CPU/GPU inference là thật. Không dùng `.venv` cho inference embedded. Không phải frozen app test.
- Baseline được bảo vệ: người dùng xác nhận 16/16 trên máy phát triển; bài source GUI trước có playback, history/cache restart, Light/Dark/DPI 6/6. Những kết quả này là baseline, không tự ghi thành kiểm thử Installer RC mới.
- Bản cài: playback, Light/Dark/DPI, TXT/DOCX/editor/export/API config, update, SQLite migration/native uninstall: **NOT RUN** vì không có RC Installer. Full offline vẫn kiểm tra các contract/fixture tương ứng, không gọi API dịch trả phí.
- Một focused preliminary fail do tên thư mục staging test lặp khi chạy lại, guard no-overwrite hoạt động đúng; test được đổi sang UUID, không xóa staging cũ và không nới guard. Log thất bại giữ riêng, không tính PASS.

## F. Giấy phép

[License audit chi tiết](release-candidate-license-audit.md) phân biệt use/download/bundle/auto-download/notice cho model/voice, ORT, Python, Qt, codecs, eSpeak/phonemizer, dictionaries, NVIDIA, Microsoft, translation/TLS libraries, PyInstaller và UI assets. [56 package inventory](../artifacts/rc-audit/package-licenses.json) và [notices](tts-third-party-notices.md). Wrapper MIT đã xác minh lại, native/source/distribution dossier chưa đạt. Không kết luận tất cả package đều tự do phân phối vì tải được bằng pip.

## G. Dữ liệu, update, uninstall và rollback

App files và user data tách nhau: app `%LOCALAPPDATA%/Programs/TransComic`, translation DB/config/DPAPI keys ở `%LOCALAPPDATA%/TransComic`, TTS DB/history/model/voice/runtime/logs trong `TTS`; audio ở output do người dùng chọn. Updater cache riêng trong `Updates`. Không có developer absolute paths được thêm vào product config; đường dẫn máy trong artifact JSON chỉ là evidence.

Restart/cache reuse đã có source evidence và smoke mới không HTTP. Installer static không có UninstallDelete/user-data cleanup, không add migration, không xóa output. SafeExit/mutex và helper path/trust contracts giữ nguyên. Nghiệm thu native install/update/uninstall chưa có; không xác nhận dữ liệu thật qua các bước chưa chạy.

Version RC **1.0.4** bằng version public nên updater phải từ chối same-version offer, không bypass SemVer để ép cập nhật. Upgrade thực sang version public tiếp theo cần phê duyệt version riêng. Rollback runtime chỉ chạy profile thuộc trusted catalog hiện tại; cross-catalog rollback còn PARTIAL. Không tự phục hồi DB cũ đè tiến độ mới. Long paths/Unicode/permission errors có offline/source coverage; Program Files/admin install, profile khác/ổ đĩa khác và native update vẫn cần môi trường cách ly.

## H. Source modifications

1. `scripts/build_local.py`: thêm exact allowlist `scripts/tts_packaging.py`, setup catalog, calibration, hai notices; optional legacy descriptor nếu tồn tại. Trước đây staging thiếu helper nên spec không thể import hook; JSON/notices cũng bị bỏ sót. Không mở glob user data hoặc tắt gate.
2. `pyproject.toml`: thêm `setup-catalog.json` vào package data, tránh mất catalog khi cài package.
3. `scripts/rc_release_audit.py`: read-only artifact/platform/cache/remote metadata/installed license inventory; không build/install/publish.
4. `tests/test_rc_release_audit.py`: 95 artifact/exclusive ORT/platform/secret URL/checksum/cache partial, gate fail-closed và chạy resource hook từ staging bằng dependency stubs; không tạo EXE/Installer.
5. `docs/tts-third-party-notices.md`: ghim MIT source commit của wrapper và ghi rõ native gate; thêm hai báo cáo RC và liên kết audit hiện tại.

Không đổi engine/scheduler/worker concurrency/model catalog/version/journal, SQLite schema, API key policy, updater protocol hoặc UI. Dependency pins không đổi; không chạy pip install/uninstall. Working tree trước task đã có nhiều thay đổi; [before stat](../artifacts/rc-audit/before-diff-stat.txt) / snapshot cuối được giữ riêng, không gán toàn bộ diff cho task này.

Git tracked diff toàn workspace: **16 files changed, 140 insertions(+), 15 deletions(-)**; baseline trước task **15 files, 132 insertions, 15 deletions**. Script/test/report mới và một số tài liệu TTS vẫn untracked từ trước nên không nằm hết trong stat. [After stat](../artifacts/rc-audit/after-diff-stat.txt), [status](../artifacts/rc-audit/after-status.txt), [config diff](../artifacts/rc-audit/build-config.diff). README, tts-licenses và báo cáo one-click được thêm liên kết đến audit RC hiện tại. [Preservation SHA/dependency check](../artifacts/rc-audit/preservation-check.json) xác nhận HEAD, engine, parallel/process engine, scheduler, catalog, version, journal và `pip freeze` giữ nguyên.

## I. Đánh giá RC

**BLOCKED — DO NOT RELEASE.** Artifact integrity/network/source smoke và staging regression đã qua, nhưng license/source/redistribution gate chưa đóng và môi trường build CPU riêng chưa xác minh. Không chạy build chỉ để xem có thành công. Windows clean/frozen test thiếu là bước tiếp theo sau khi các gate trước build đạt, không được đổi thành PASS bằng source/mock.

## J. Các bước còn lại

1. Đóng các blocker trong [license audit](release-candidate-license-audit.md): eSpeak binary/source provenance, corresponding source/notices và policy GPL/LGPL/Qt/codecs/NVIDIA/Microsoft.
2. Chuẩn bị CPU build environment cách ly, giữ nguyên `.venv` GPU; chạy lại preflight/focused phù hợp. Quyền một build có điều kiện đã có, không cần hỏi lại chỉ vì marker BUILD_LOCAL.
3. Khi audit PASS mới dùng entry point local hợp lệ, output unique, không overwrite Installer cũ; ghi size/SHA/time/signature thực của RC và kiểm tra archive không lẫn private data.
4. Dùng Windows 10/11 x64 test riêng, profile/cache/DB trống: cài RC, mở TTS, bấm **Tải model**, tạo/phát WAV/MP3, restart không tải lại; CPU-only và NVIDIA thật kiểm tra đúng backend. Người thử không cần Python/pip/PowerShell/CUDA/cuDNN thủ công.
5. Smoke chức năng dịch bằng fixtures, không API trả phí; thử safe update/uninstall/data retention trong VM/máy test có backup. Không cài đè production hoặc gán version giả để ép updater.

Chưa có artifact để gửi nghiệm thu cài đặt; bản public đang hoạt động được giữ nguyên.
