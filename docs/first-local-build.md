# First local build — TransComic 0.1.0 devtest

**FIRST LOCAL BUILD PASS**

Hoàn tất popup cập nhật, SRT placeholder và build Windows thật. Đây là kết quả build cục bộ; chưa cài đặt hoặc phát hành.

## Source và toolchain

HEAD `6fd3f061c3c78fcae3ec4ebd467858346441ff56`, branch `main`, **dirty devtest snapshot**. Hash từng input và Git status nằm trong `artifacts/first-local-build/build-0.1.0-devtest-final/build-inputs.json`; artifact không đại diện cho clean commit.

Python 3.13.14; PyInstaller 6.22.0; PySide6 6.11.1; cryptography 50.0.2; Inno compiler 6.7.3 (header iscc.log); Windows AMD64. Tool discovery không hardcode user path. Toàn bộ inventory Git/gh/dependency trong build-report.json.

## 27 mục bàn giao

1. Popup Liquid Glass hoàn thành, dùng Dialog V3, release notes hiển thị plain text; X/Escape xử lý như Để sau.
2. Chỉ manual check với candidate Internal đã xác minh và UPDATE_AVAILABLE mới mở popup; auto-check, offline, invalid, same version, no release không mở. Không giành modal khác.
3. Nút Tải và cài đặt đóng dialog, chuyển trang Cập nhật và gọi downloader hiện có. Mock download xác minh size/SHA; sau tải UI ghi rõ chưa chạy bộ cài. Installer vẫn khóa.
4. Để sau không tải/cài/đổi version; giữ candidate và cho phép popup ở manual check tiếp theo. Kiểm tra lặp không tạo popup trùng.
5. Dịch file SRT nằm ngay sau Dịch; SVG subtitles do dự án tạo, cùng nét copper. Giữ index các trang cũ.
6. Trang giữa màn hình có Dịch file SRT, Chức năng đang được cập nhật và mô tả. Không có import/export/parser/scheduler/API/button giả.
7. Unit test xác minh giữ manuscript, target chips, current selection. Frozen smoke giữ bản thảo/target và Search/Replace/Undo khi đổi trang/theme.
8. Source VERSION 0.1.0, PE fixed version 0.1.0.0; không reserve/bump version. Các test version carry trong full suite đạt.
9. PyInstaller thật thành công cho app và external helper, dùng spec hiện có trên snapshot allowlist có BUILD_LOCAL marker.
10. ISCC thật 6.7.3 thành công. ISS giữ AppId, per-user PrivilegesRequired=lowest, target x64compatible, shortcut/uninstall entry; không có lệnh xóa user data.
11. App: `D:\Sourch Code\TransComic\artifacts\first-local-build\build-0.1.0-devtest-final\source\dist\TransComic.exe`; helper: `D:\Sourch Code\TransComic\artifacts\first-local-build\build-0.1.0-devtest-final\source\dist\TransComic-UpdateHelper.exe`.
12. Installer: `D:\Sourch Code\TransComic\artifacts\first-local-build\build-0.1.0-devtest-final\installer\TransComic-Setup-0.1.0-devtest-windows-x64.exe` (chưa thực thi).
13. SHA-256, bytes và PE architecture được ghi trong bảng artifact bên dưới và acceptance.json; rehash audit khớp.
14. Win32 đọc icon bằng DATAFILE|IMAGE_RESOURCE, không thực thi PE. Icon app/helper/installer khớp ảnh ICO nguồn, version 0.1.0.0. App/helper x64; bootstrapper Inno x86 nhưng payload/target x64 theo ISS.
15. Final app EXE chạy bằng profile tạm ở ba DPR; parent launcher quan sát exit code 0 thật, Safe Exit 900ms đạt.
16. Không lỗi DLL/Qt plugin trong các frozen smoke. Archive có qwindows.dll/qsvg.dll/qsvgicon.dll và SVG SRT. Optional-import warnings PyInstaller được giữ trong log, chưa chứng minh mọi dependency trên máy sạch.
17. Allowlist không chứa user SQLite/DOCX/TXT, DPAPI blobs, backups, keys, journal, test/cache/log. Archive audit không thấy dữ liệu cấm hoặc tests package. docx/templates/default.docx và certifi/cacert.pem là dữ liệu dependency công khai được cho phép; credential regex kiểm tra input source không phát hiện token literal, không phải chứng minh tuyệt đối toàn bộ dependency.
18. Smoke yêu cầu LOCALAPPDATA nằm dưới temp và marker hợp lệ trước Store. Database thực của dev không mở; HTTP guard chỉ cho MockTransport, không dùng API key/DPAPI thật.
19. Final prebuild full regression: **791 passed, 1 skipped**, 199.337s. Giữ nguyên test deadline/skip cũ, không giảm assertion. Lượt trước build đầu cũng đạt 790 passed, 1 skipped.
20. Sau build đầu: 790 passed, 1 skipped (216.84s), là kết quả sơ bộ vì câu cache được chỉnh trong khi suite chạy. Test mới HTTP304 + 14 test UI/build đạt 15 passed. Sau sửa text đã chạy full final trước rebuild; sau rebuild chạy frozen smoke/audit. Không thay runtime sau final build.
21. Windows native 100/125/150%, Light/Dark: popup/SRT/updater/queue clear/Search/Replace/Safe Exit đạt. Frozen small/maximized dùng sidebar collapsed theo responsive; ảnh source native-expanded kiểm tra width200, SVG, footer riêng. Tooltip/active/selection kiểm tra unit. Ảnh hover/focus riêng không tạo, dùng behavior nút hiện có.
22. Không sửa backend Kira/Gemini/concurrency/batch/retry/scheduler/prompt/locale/validator/export/schema/DPAPI trong lượt này; app.py chỉ thêm nhánh smoke opt-in có guard.
23. Không gọi API Kira/Gemini thật. Update GUI sử dụng GitHub mock và .testdata không thực thi; không tạo release để test.
24. Không chạy installer hoặc helper thực thi; chỉ compile installer và đọc PE resources. Cài đặt/uninstall/cài đè chưa kiểm thử.
25. Không tạo tag/draft/upload/publish; không git add/commit/push/reset. Dirty tree các lượt trước được giữ lại.
26. Trước cài thật cần kiểm thử VM Windows sạch (install/uninstall, shortcuts, keep-data, app/helper, update handoff). Safe Exit có lỗi timing gián đoạn: regression-before-final một lỗi; regression-final hai lỗi 900ms, worker ở asyncio teardown. 19 test stability/lifecycle chạy riêng đạt; gate cuối và frozen đạt, chưa kết luận sửa root cause. Artifact unsigned/devtest, không đủ bằng chứng production/public release.
27. Cần quyền riêng INSTALL_LOCAL/VM; REAL_UPDATE_INSTALL; RELEASE_REMOTE (tag/draft/upload/publish) và commit/push nếu muốn. BUILD_LOCAL không bật các quyền này.

## Artifact cuối

| File | Bytes | SHA-256 | PE/version |
|---|---:|---|---|
| TransComic.exe | 77286971 | `56bbbb87c91d24adc0f5cb18ab041efdbb719d368faa96d2b81ca92387d3abd8` | x64 / 0.1.0.0 |
| TransComic-UpdateHelper.exe | 33766021 | `c2bd8e171a7450541ebf6978a01c4a893bae701df1f2d561545ec39c0895edfc` | x64 / 0.1.0.0 |
| TransComic-Setup-0.1.0-devtest-windows-x64.exe | 112838882 | `81b3265687afdd643bdd255add951e20e4dabd7d4ec165538dd60027e6fd0201` | x86 / 0.1.0.0 |

## Lệnh và bằng chứng

Full final: `python -m pytest -q --junitxml=artifacts/first-local-build/regression-final-gate.xml`. `regression-final-gate.log/xml` là gate nguồn cuối. Lượt trước có plugin safe_exit_probe chỉ ghi stack/flags khi fail, không đổi timing/logic/skip; giữ kết quả fail trong regression-final.log/xml.

Build: `python scripts/build_local.py --output artifacts/first-local-build/build-0.1.0-devtest-final`. Đây là entry point build devtest riêng có scope, không thay workflow phát hành duy nhất release_transcomic.bat.

Smoke: `python scripts/local_exe_smoke.py --exe artifacts/first-local-build/build-0.1.0-devtest-final/source/dist/TransComic.exe --scale <0.8|1|1.2>`. Windows base display125% nên scale này tạo DPR1/1.25/1.5. `windows/<scale>/report.json`, screenshots/process.log là bằng chứng binary cuối; `native-expanded/<scale>` là bằng chứng source mở rộng.

Audit: `python artifacts/first-local-build/audit_final.py`; kết quả archive-audit-final.json/icon-audit-final.json. `acceptance.json` đối chiếu hash source hiện tại/staged/artifact và các gate.

Lịch sử lỗi giữ nguyên: regression-before (nav index cũ6, sửa expectation7 và giữ assertion index cũ); regression-before-final (Safe Exit iteration2 trượt900ms); safe-exit-isolated (2 passed), regression-gate (790 passed1skipped). Source smoke trước đó thất bại vì harness so revision cũ sau Replace/Undo, đã sửa baseline harness. Build đầu và windows-initial giữ lại, không là artifact bàn giao cuối.

Không tạo log kết quả giả hoặc bỏ test để đạt PASS. Native GUI không crash ở các lượt cuối. Cài đặt và update production cần đợt phê duyệt và kiểm chứng riêng.
