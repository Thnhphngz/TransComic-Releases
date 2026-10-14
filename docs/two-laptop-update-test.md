# TransComic — Thử cài và tự cập nhật trên laptop 2

**TWO-LAPTOP UPDATE TEST PACKAGES READY**

**NATIVE UPDATE IMPLEMENTED — AWAITING LAPTOP 2 INSTALL TEST**

Đây là bộ thử nghiệm, chưa xác minh native install/update và chưa sẵn sàng phân phối gia đình. Laptop 1 chưa chạy installer; laptop 2 chưa được thao tác.

## File cần chuyển sang laptop 2 trước tiên

Chỉ chép installer **0.1.0** và hướng dẫn này. Không chép source, DB/key của laptop 1, artifacts logs hoặc toàn bộ build directory.

`artifacts/two-laptop-update-test/0.1.0/installer/TransComic-Setup-0.1.0-laptop-test-windows-x64.exe`

SHA-256: `5376652da75aa1f1ba0cb6cabc03000b0e999cfd9e3f83986fd36a46a35d0056`

Bytes: 112890973

## Các bước trên laptop 2 (người dùng thực hiện)

1. Kiểm tra Windows 11 x64 và nguồn file được chuyển trực tiếp từ laptop 1.
2. Trong PowerShell, chạy `Get-FileHash -Algorithm SHA256 -LiteralPath 'C:\duong-dan\TransComic-Setup-0.1.0-laptop-test-windows-x64.exe'`. Thay đường dẫn cho đúng; so toàn bộ hash với giá trị bên trên.
3. Khi hash khớp, chạy installer 0.1.0 bằng tài khoản Windows đang dùng. Giữ đường dẫn mặc định `%LOCALAPPDATA%\Programs\TransComic`; không chọn thư mục tùy chỉnh trong đợt thử updater này.
4. Nếu SmartScreen cảnh báo, ghi lại nội dung và xác minh lại nguồn/hash. Không tắt SmartScreen, Defender hoặc tự bỏ qua cảnh báo để đạt test. Gửi ảnh cảnh báo nếu Windows chặn.
5. Mở app bằng shortcut, vào Cài đặt và kiểm tra phiên bản **0.1.0**. Kiểm tra app/helper tồn tại trong thư mục cài và entry TransComic trong Installed apps; ghi lại shortcut/icon, đường dẫn và phiên bản.
6. Tạo TXT/DOCX nhỏ giả (không chứa dữ liệu riêng), nhập vào app, sửa thủ công vài dòng bản dịch, đổi theme/settings, tạo trạng thái queue/history nếu có thể bằng thao tác offline. Không cần API thật để thử bước cài đặt.
7. Đóng/mở lại app; kiểm tra văn bản, bản dịch sửa tay và theme/settings còn nguyên. SQLite nằm tại `%LOCALAPPDATA%\TransComic\transcomic.sqlite3`, ngoài thư mục chương trình.
8. Gửi kết quả cài đặt: Windows version, app version, đường dẫn cài, ảnh shortcut/Installed apps, khả năng mở/đóng, dữ liệu/theme giữ lại và mọi cảnh báo. Không gửi API key, DPAPI blob hoặc DB cá nhân.
9. Nếu thử uninstall/reinstall: đóng app trước, ghi nhận dữ liệu giả; uninstall từ Windows Installed apps, kiểm tra thư mục dữ liệu giả còn, cài lại **đúng installer 0.1.0** và kiểm tra dữ liệu/theme. Đây là reinstall, không được ghi là update đã đạt.

**Chưa chạy installer 0.1.1 trực tiếp trên laptop 2 để thay cho bài thử tự cập nhật.** Chưa có GitHub Release 0.1.1 thì bước Kiểm tra cập nhật có thể báo chưa có bản phát hành; đó không phải bằng chứng update hỏng.

## Khi đã được phê duyệt và có Release 0.1.1 thật

1. Chỉ sau khi baseline cài thành công và release đã upload/remote-verify/publish theo đợt riêng, mở app **0.1.0 đã cài**.
2. Kết thúc công việc, chờ mọi request/worker kết thúc, thoát sửa ô; không để app đang pause hoặc có HTTP in-flight.
3. Vào Cài đặt → Kiểm tra cập nhật. Kiểm tra popup hiện bản mới **0.1.1**, chọn Tải và cài đặt.
4. App tải và xác minh file, đối chiếu lại release qua HTTPS; helper xác minh lại, nhận COMMIT sau đóng dữ liệu, chờ app/bootloader thoát, rồi cài per-user. Không tự mở thêm app trong lúc cập nhật.
5. App mở lại phải báo **0.1.1**. Kiểm tra lại dữ liệu giả, bản dịch sửa tay, jobs/history, theme/settings và đường dẫn/AppId không đổi. DPAPI chỉ được kiểm chứng bằng blob giả tạo ngay trên laptop 2; chưa có bằng chứng DPAPI ở lượt chuẩn bị này.
6. Xem `%LOCALAPPDATA%\TransComic\Updates\install-0.1.1.json`: COMPLETED chỉ được ghi sau version/registry khớp và app mới xác nhận UI/SQLite đã mở. Gửi trạng thái (không gửi dữ liệu cá nhân).
7. Nếu UNKNOWN, restart pending, app bị chặn mở hoặc cài lỗi: giữ nguyên receipts/locks và ghi nhận process/status. Không chạy lại installer, xóa lock/journal, hoặc bấm thử nhiều lần khi kết quả chưa rõ. Cần kiểm tra thủ công phiên bản cài và process trước recovery.

## 25 câu trả lời bàn giao

1. Baseline0.1.0 mới: có, dùng native implementation mới; artifact devtest cũ không ghi đè.
2. Candidate0.1.1 mới: có, cùng logic source; chỉ version overlay trong staging.
3. Installer0.1.0: `artifacts/two-laptop-update-test/0.1.0/installer/TransComic-Setup-0.1.0-laptop-test-windows-x64.exe`. Installer0.1.1: `artifacts/two-laptop-update-test/0.1.1/installer/TransComic-Setup-0.1.1-laptop-test-windows-x64.exe`.
4. Hash0.1.0: `5376652da75aa1f1ba0cb6cabc03000b0e999cfd9e3f83986fd36a46a35d0056`. Hash0.1.1: `a91e61a3aff9edd1ea7c199b40196942d13d02add46e69c3db4f5a60668b51d1`.
5. Cùng Inno AppId `{CB58C770-47B7-42DC-A2CA-409DDF456487}`; APP_ID metadata/app vẫn `TransComic.Desktop`.
6. Cùng mặc định per-user `%LOCALAPPDATA%\Programs\TransComic`; UsePreviousAppDir=yes. Updater chỉ chấp nhận đúng mặc định, registry HKCU và version PE khớp; custom/moved directory bị chặn.
7. Native helper đã được kích hoạt bằng code theo ngữ cảnh xác thực, không env bypass: frozen Windows + registered app + fixed path/version + local pipe peer PID/creation time/image + HTTPS release + READY/COMMIT/ACK + app/process/bootloader exit. JSON safe_exit_verified riêng không cấp quyền.
8. Helper x64 được đóng gói trong cả hai bản; packaged `--self-check` exit0, `--plan` file tùy ý exit2. Probe không cài, không native handoff.
9. Busy/paused/inflight/editor/transaction/background work chặn handoff, không kill hoặc đổi retry. Store/log phải đóng trong900ms trước COMMIT; chậm hoặc lỗi không cho cài. Outcome unknown fsync trước executor, lock độc quyền; unknown không replay và chặn mở app giữa lúc installer có thể còn chạy.
10. Source VERSION0.1.0 giữ nguyên. Baseline0.1.0 và candidate0.1.1 có PE0.1.0.0/0.1.1.0; source logic hashes bằng nhau; candidate overlay được khai báo. Không reserve production journal.
11. Internal manifest đúng version/tag/platform/arch/name/size/SHA/min-updater0.1.0; offline validator đạt. Không invent releaseID/assetID. Những ID/remote bytes chỉ được kiểm tra sau upload thật.
12. File cho GitHub tương lai nằm trong `0.1.1/release-assets/`: canonical EXE, transcomic-update.json, SHA256SUMS.txt. Release notes ở `0.1.1/release-notes.md`. Không upload source/build report/test evidence. Chưa upload hoặc publish; chỉ là file local đã chuẩn bị.
13. Popup giữ manual/background/304/modal/duplicate/close protections; full và frozen Windows smoke đạt. Không đổi Liquid GlassV3.
14. Mock tests bao phủ busy/inflight/unsafe exit/PID reuse/hash/path/downgrade/installer failure/unknown/restart failure/no concurrent execution/success. Native channel transport thực chỉ trao đổi byte, không xác minh native installer E2E.
15. Hai full trên cùng mã cuối: **861 passed, 1 skipped** (198.963s) và **861 passed, 1 skipped** (199.247s). Không nới900ms, không skip thêm, không reset ledger. Lượt trước chạy đồng thời PyInstaller có 1 fail tại retry concurrency=1: sau join10s mới thấy49/50 batch; giữ nguyên log/XML regression-build-overlap-failed. Hai lượt cuối chạy tuần tự sau build. Tranh chấp tài nguyên là suy luận; không coi các lượt đạt là chứng minh mọi lỗi timing đều đã hết.
16. Cả hai EXE chạy Windows thật DPR1/1.25/1.5, Light/Dark, popup/SRT/Queue Clear/SearchReplaceUndo/TXT-DOCX/render/SafeExit/process exit0. Dữ liệu giả ở TestRuntime ngoài source.
17. Không native Qt crash trong sáu smoke cuối và hai full cuối.
18. Không mở DB/API key thật để smoke; package allowlist/archive scan không user DB/DOCX/TXT/Git/TestArchive. Public dependency docx/templates/default.docx và certifi/cacert.pem được phân biệt. Không xóa TestRuntime/TestArchive.
19. Kira/Gemini thật0. GitHub chỉ đọc metadata/preflight; GUI dùng MockTransport, nonexecutable .testdata.
20. Installer trên laptop1:0; helper chỉ self-check/invalid CLI. Không native updater handoff trên host.
21. Tag/Release mới:0, không commit/tag/push.
22. Upload GitHub0; BAT vẫn preflight/remote writes locked. Internal không cần Ed25519/Authenticode; Signed Stable verifier không được hạ cấp.
23. Source vẫn dirty/untracked, main, HEAD `6fd3f061c3c78fcae3ec4ebd467858346441ff56`, chưa origin. Cần review và commit/provenance trước public release; không đổi origin sang public distribution repo. git diff --check exit0. Các byte runtime khớp staged inputs; wheel/toolchain provenance sạch chưa được tuyên bố.
24. Người dùng làm theo bước cài0.1.0 và gửi kết quả phía trên; không cài0.1.1 trực tiếp để thay update test.
25. Blockers: baseline native install/keep-data/DPAPI và native update chưa thử trên laptop2; chưa có Release0.1.1, source provenance dirty, remote coordinator activation/publication cần phê duyệt riêng. Không READY_FOR_FAMILY_DISTRIBUTION.

## Ghi chú kỹ thuật và bằng chứng

Named pipe first-instance, reject-remote, DACL user hiện tại/SYSTEM; bounded message128KiB; không pickle. Helper copy pinned không write/delete đến READY. Win32 transport probe xác minh peer PID, roundtrip1/8192/131072byte và timeout/cancel I/O; không chạy installer. Đã phát hiện/sửa trường hợp client kết nối trước accept: thu GetOverlappedResult(True) sau event, giữ logs lỗi trước sửa. [Microsoft ConnectNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-connectnamedpipe), [CPython implementation](https://github.com/python/cpython/blob/3.13/Modules/_winapi.c).

PyInstaller one-file app/helper có bootloader process riêng; helper chờ process handles đã xác minh, restart dùng PYINSTALLER_RESET_ENVIRONMENT=1 và app startup acknowledgement thay vì chỉ chờ process sống1giây. Trước khi gọi Inno, helper phục hồi DLL search hệ thống rồi restore sau launch. [PyInstaller common issues](https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html).

App/helper x64; Inno bootstrap có thể x86 nhưng payload/target x64 theo ISS. AppMutex bảo vệ app còn mở, installer không auto-close/restart app. Code helper chạy installer không nâng quyền, fixed canonical asset, hash reverify dưới handle no-write/delete. Timeout không kill installer, giữ UNKNOWN/lock để recovery thủ công.

`artifacts/two-laptop-update-test/acceptance.json`, `build-audit.json`, `package-report.json`, `metadata-verification.json`, `source-final-before-regression.json`, `source-review.json`, `privacy-scan.json`, `channel-probe.json`, `regression-1/2.log/xml`, mỗi version có build inputs/report, PyInstaller/ISCC logs, staging source và windows/<scale>/report.json/screenshots. Artifact cũ được đối chiếu hash và giữ nguyên. Các lượt preliminary/transport lỗi được giữ, không dùng thay cặp gate cuối.
