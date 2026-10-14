# Workspace cleanup và isolated installer test

**CLEANUP PASS + ISOLATED INSTALL BLOCKED**

## Kết quả 28 mục

1. Trước cleanup: 84 thư mục .pytest_*, 26904 regular files, 2773070366 bytes. Không đi qua alias/junction khi tính inventory.
2. Archive 61 thư mục; danh sách chi tiết trong archive-receipt.json/manifest ngoài workspace.
3. Dung lượng logic 862,979,993 bytes (823.00 MiB), 8443 file và 2130 alias. Giữ cả verified copy và bản gốc nên dung lượng vật lý lớn hơn khoảng gấp đôi, thêm bản restore mẫu.
4. Kho: `D:\TransComic-TestArchive\archive-20261014-222611-79115cbe`. Không trộn D:\TransComic-SecureBackup, không ghi đè đợt cũ.
5. Mỗi file thường có size/SHA-256; mỗi alias có raw target; directory structure và aggregate hash kiểm chứng được. So source→verified copy→moved original đều khớp. Manifest atomic trước move, receipt sau move; không delete source/archive.
6. Giữ 23 thư mục; xem bảng lý do bên dưới. Cache có thể cập nhật lại do pytest.
7. Các junction vòng lặp/alias bất thường không được duyệt. Alias pytest *current trỏ đến sibling có số suffix và plain directory trong cùng candidate được lưu nguyên link, không traverse. Target tuyệt đối còn dùng original workspace path; link ở archive có thể dangling và sẽ hoạt động khi restore đúng vị trí. Không dùng archive alias để chạy test.
8. Root 109 mục trước → 48 ngay sau archive; cuối 48 mục, 23 thư mục .pytest_* còn lại. Số mục cuối gồm tài liệu/script báo cáo mới được yêu cầu.
9. Không thấy lỗi thiếu dependency do archive. Kết quả toàn bộ test giữ nguyên trong log/XML; không thay/xóa/nới test để che lỗi.
10. Restore rehearsal có dữ liệu thật của fixture tại `D:\TransComic-TestArchive\archive-20261014-222611-79115cbe\restore-data-sample\.pytest_docx_1`; copy lại từ archived original rồi so toàn bộ hash/link metadata. Không ghi đè thư mục đang có trong project. Bản restore được giữ lại.
11. Git HEAD `6fd3f061c3c78fcae3ec4ebd467858346441ff56`, branch `main`, dirty tree. Git status và hash tất cả tracked files trước/sau archive trùng. Runtime allowlist của build cuối vẫn khớp. Chỉ bổ sung tool archive/test/báo cáo, không sửa backend.
12. Lượt 1: 795 passed, 0 failed, 0 errors, 1 skipped, XML suite time 199.531s; Lượt 2: 795 passed, 0 failed, 0 errors, 1 skipped, XML suite time 198.710s. Chạy nối tiếp sau archive, không archive đồng thời regression.
13. WindowsSandbox.exe không tìm thấy tại System32; không tự bật Optional Features, Hyper-V hoặc reboot.
14. Không tìm thấy Get-VM/VBoxManage/vmrun, service vmcompute/vmms hoặc VM product được đăng ký. Host là ASUS TUF, HypervisorPresent=true chỉ là dấu hiệu hypervisor, không phải bằng chứng guest. Không xác minh được guest cách ly sẵn dùng.
15. Chưa chạy installer trong guest hoặc host. ISOLATED_INSTALL_BLOCKED. Temp LOCALAPPDATA của smoke app không được coi là Sandbox.
16. Shortcut/AppId/registry uninstall chưa được kiểm tra bằng cài đặt thực tế; ISS có cấu hình tương ứng nhưng không thay thế evidence guest.
17. App đã cài trong guest chưa được kiểm thử. App EXE build cuối chạy trực tiếp trên host với temp DB/HTTP guard đạt, tách rõ khỏi installer test.
18. Host frozen smoke không lỗi DLL/Qt plugin, DPR đo thật và Light/Dark ghi trong windows-smoke/report.json. Guest PySide6/DLL chưa kiểm thử.
19. Không mở/chỉnh SQLite/DPAPI/key của host. Không chuyển dữ liệu/credential thật vào guest. Guest data persistence chưa có bằng chứng vì install bị chặn.
20. Uninstall giữ SQLite/DPAPI/fixture files: chưa thực hiện, chưa kết luận.
21. Reinstall giữ dữ liệu: chưa thực hiện, chưa kết luận. Cùng phiên bản sẽ không chứng minh upgrade 0.1.0→0.1.1.
22. Safe Exit trong guest chưa thực hiện. Host smoke quan sát exit code0 thật; idle/GUI workflow đóng được. Lỗi timing 900ms gián đoạn của đợt trước vẫn là rủi ro chưa kết luận sửa; auto-install chưa ready.
23. Chưa chạy native updater E2E, không gọi native helper. Metadata/helper presence và mock regression được giữ; không mở khóa update/install.
24. Không build lại installer trong lượt này; file build cuối giữ nguyên, hash/version/size/PE kiểm tra lại trực tiếp.
25. Không gọi Kira/Gemini thật, không reset live API ledger. Tests/GUI dùng fixtures và HTTP mock.
26. Không sửa backend dịch/scheduler/DB schema/DPAPI. Tool mới chỉ thao tác .pytest_* và archive được xác minh.
27. Không tag/commit/push/draft/upload/publish. Không copy tài khoản/token GitHub host.
28. Blocker: cần Windows guest thật được xác minh để install/uninstall/reinstall, registry/shortcut, DPAPI giữ dữ liệu và Safe Exit mock. Chưa chứng minh upgrade/native updater/máy sạch; binary unsigned dirty devtest. Không dùng host làm phương án dự phòng.

## Thư mục giữ lại

| Thư mục | Lý do |
|---|---|
| `.pytest_cache` | Source/test reference needs review |
| `.pytest_final_retry_speed` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_baseline` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_complete` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_delivery` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_final` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_final_gate` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_first` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_uncertainty_final` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_language_verified` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_barrier` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_baseline` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_complete` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_complete_final` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_delivery` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_final` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_final_report` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_full1` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_full2` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_releasecheck` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_multilingual_verified` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_v2_complete` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |
| `.pytest_v2_verified` | Unknown reparse: test_directory_junction_loop_d0/chapters/loop |

## Khôi phục và bằng chứng

Archive giữ `verified/<name>` và `originals/<name>` độc lập. Trước restore: dừng pytest/app/build/helper, xác minh manifest/hash và đường dẫn, đảm bảo original workspace path chưa tồn tại; copy hoặc move toàn bộ folder từ originals về đúng original path bằng PowerShell LiteralPath hoặc tool no-follow, không overwrite. Đối chiếu file/hash/raw aliases sau restore. Không dùng alias trong archive để traverse dữ liệu. Kho archive và restore mẫu được giữ, không tự dọn.

`scripts/archive_pytest_outputs.py` mặc định inventory-only; `--apply` là hành động archive trong phạm vi đã duyệt. Nó không dùng release flags, không cài đặt/phát hành. Process gate, file exclusive-open, reparse validation, source hash, git tracked và destination boundaries đều được kiểm tra.

Logs mới: artifacts/workspace-cleanup/archive-tests*.log, inventory.json, archive-run.log, archive-receipt.json, restore-data-verification.json, regression-1/2.log/xml, windows-smoke/report.json và ảnh. Không overwrite artifacts/first-local-build. artifacts/isolated-install/environment.json/artifact-check.json/acceptance.json ghi blocker và hash actual.

Test archive đầu có 1 lỗi expectation Win32 raw symlink target mang prefix \?\; test được sửa để đối chiếu os.readlink nguyên gốc. Implementation giữ nguyên raw target. Lượt test gate sau đó đạt 4 passed. Không thay test Safe Exit/timeout/skip cũ.

## Artifact giữ nguyên

| File | SHA-256 | PE/version |
|---|---|---|
| TransComic.exe | `56bbbb87c91d24adc0f5cb18ab041efdbb719d368faa96d2b81ca92387d3abd8` | x64 / 0.1.0.0 |
| TransComic-UpdateHelper.exe | `c2bd8e171a7450541ebf6978a01c4a893bae701df1f2d561545ec39c0895edfc` | x64 / 0.1.0.0 |
| TransComic-Setup-0.1.0-devtest-windows-x64.exe | `81b3265687afdd643bdd255add951e20e4dabd7d4ec165538dd60027e6fd0201` | x86 / 0.1.0.0 |

Installer chưa được thực thi. Chưa có install log, installed files inventory hoặc guest screenshots; không thay bằng ảnh/mock dựng.
