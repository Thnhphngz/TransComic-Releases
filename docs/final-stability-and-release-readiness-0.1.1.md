# TransComic 0.1.1 — Final stability & release readiness

**PARTIAL — SPECIFIC BLOCKERS REMAIN**

## Trạng thái

| Gate | Kết quả |
|---|---|
| POPUP_STABLE | PASS — bounded source stress and frozen Windows GUI; reproduced harness starvation corrected |
| SAFE_EXIT_STABLE | PASS IN TESTED CASES — 900ms assertions retained; historical runtime root cause not fully proven |
| LOCAL_BUILD_READY | PASS — unchanged local devtest candidate; package inputs reverified |
| NATIVE_INSTALL_VERIFIED | BLOCKED — no verified Windows guest |
| NATIVE_UPDATE_VERIFIED | BLOCKED — no guest; native execution remains locked |
| SOURCE_REVIEW_READY | PARTIAL — diff/privacy/commit inventory ready; dirty source and missing origin provenance |
| GITHUB_RELEASE_READY | BLOCKED — native proof, clean source provenance and reviewed execution/publication remain outstanding |

PASS ở trên chỉ áp dụng cho các lượt kiểm thử ghi nhận, không phải cam kết tuyệt đối về mọi máy Windows. Native install/update chưa được xác minh.

## 27 câu trả lời nghiệm thu

1. **Popup:** tái hiện lỗi test 304 ở vòng thứ 16 (index 15). Timeline cho thấy `UpdateService.check` trả lúc 187.511s, assertion fail lúc 187.602s, chưa có `receive` cho kết quả cuối; 63 callback trước đó đều ở MainThread. Không quan sát được callback chạy sai thread; callback cuối chưa được xử lý trước assertion. Probe và đối chiếu cùng mock xác định scheduling của harness dùng qWait liên tiếp là nguyên nhân của lỗi tái hiện này.
2. **Sửa:** thêm `tests/qt_wait.py` dùng QEventLoop.exec + QTimer precise và sửa hai helper chờ trong tests. Giữ nguyên 3.000ms popup, 900ms Safe Exit và toàn bộ assertion dữ liệu/request. Không thêm sleep vào helper chờ hoặc runtime; không sửa UI/runtime/backend hoặc timeout sản phẩm. Mock check trước sửa max4.748s, sau sửa max24.111ms; callback GUI max10.229ms. Giới hạn: bằng chứng này xác định lỗi harness tái hiện được, không chứng minh mọi lỗi popup ngoài thực tế đã hết.
3. **Stress popup:** 20 vòng × 2 tình huống = 40 tình huống, 80 lần check, 0 fail. Trong mỗi vòng có modal ưu tiên, manual check lại và HTTP304. Focused mới kiểm tra 30 click chỉ tạo một worker, signal ở GUI thread, parent giữ dialog, close trong khi check còn chờ không mở popup muộn. Existing tests vẫn bao phủ background/no release/same/invalid/offline/cache/rate limit/Later/Escape/X/download.
4. **Safe Exit root cause:** probe 5/5 lần qWait không cho worker giả 40×10ms hoàn tất sau vòng 30×30ms (wall time thực khoảng0.96–1.03s); QEventLoop hoàn tất 5/5 khoảng0.42–0.45s. Đây là bằng chứng scheduling của harness, không phải chứng minh đầy đủ nguyên nhân mọi lần Safe Exit lịch sử. Không sửa scheduler/asyncio/storage/log semantics; mitigation runtime1ms từ trước giữ nguyên.
5. **900ms:** 20/20 vòng active mock Safe Exit đạt nguyên assertion900ms; focused36 và cả hai full đạt. Timeline mới: Runner.close max1.954ms, DiagnosticLog.close max0.607ms, finish_safe_exit callback max10.074ms. Scheduler._run_thread max49.834ms bao gồm workload, không gọi nó là shutdown latency. Store/commit timeline cũ được giữ ở release-preparation; không suy ra latency OS từ assertion cửa sổ. Frozen parent launcher quan sát process exit0 riêng.
6. **Guest:** Windows11 Pro build26100, HypervisorPresent=true; không có WindowsSandbox.exe, Get-VM/VBoxManage/vmrun, vmcompute/vmms. Không có guest được xác minh độc lập. Các cờ processor do hypervisor trả về không đủ kết luận BIOS tắt virtualization. Đĩa C/D còn khoảng47.6/32.1GB lúc probe.
7. **Installer trong guest:** chưa chạy; không dùng host thay thế.
8. **Install/uninstall/reinstall:** NOT TESTED; registry/shortcut/AppId/keep-data chưa có native proof.
9. **Native0.1.0→0.1.1:** NATIVE UPDATE BLOCKED. Không gọi reinstall cùng version là upgrade.
10. **Native helper:** vẫn khóa tại entry/handoff/WindowsRuntime/registry. Không thêm guest-only env/boolean bypass hoặc activation vào package. Baseline0.1.0 được giữ nguyên cũng đang khóa; guest thử upgrade cần baseline riêng được review.
11. **SQLite/DPAPI guest:** NOT TESTED. Các mock opaque blob/SQLite preservation không được tính là DPAPI/installer proof. Không copy DB/key host sang guest.
12. **Git:** main, HEAD `6fd3f061c3c78fcae3ec4ebd467858346441ff56`, dirty và có untracked; origin chưa cấu hình. git diff --check exit0. Không stage/commit/push/reset.
13. **Secrets:** không thấy token/private-key literal trong tracked+untracked dự kiến commit; 573 file bằng chứng text <=10MiB ngoài source/work staging cũng không có mẫu khớp. Không phải chứng minh tuyệt đối; binary/oversized files nằm ngoài scan này. 7 file dữ liệu cá nhân ở root được giữ và đang ignore. Không in secret hoặc xóa dữ liệu.
14. **Commit plan:** danh sách file theo nhóm nằm ở cuối báo cáo và source-review.json. Chỉ là đề xuất; không chạy git add. artifacts/runtime/archive/build/dist/user DOCX/TXT/SQLite/keys/DPAPI/journal không được commit. Source repository phải được chọn/review riêng, không đổi origin sang public Releases repo.
15. **Version:** source0.1.0; proposal/candidate0.1.1, chưa reserve. Carry0–9/no-double-bump/reconcile/unknown-outcome gates giữ nguyên và tests chạy trong full.
16. **Candidate:** không build lại vì không đổi runtime/build input. Audit so root input SHA với staged source (overlay version riêng), package modules/Qt/SVG/icon và rehash EXE/helper/installer đều khớp. Cả hai artifact cũ được giữ nguyên; toàn tree0.1.0 khớp protected snapshot.
17. **Hash cuối:** xem bảng bên dưới. Installer Inno bootstrap x86 nhưng payload/target x64, resource0.1.1.0; app/helper x64. Không đánh đồng bootstrap architecture với target.
18. **BAT:** CRLF đúng, preflight exit0, dry-run/locked, proposal0.1.1, journal absent/unchanged. GitHub tag list và releases độc lập đều rỗng tại lần đọc này. Preflight release-list riêng không là bằng chứng mọi orphan tag; đã lưu riêng tags API. Trước publication phải đọc lại exact tag/inventory/reconcile. Internal không yêu cầu Ed25519/SignTool; Signed Stable vẫn riêng.
19. **Full regression:** lượt1 820 passed, 1 skipped (204.198s); lượt2 820 passed, 1 skipped (212.332s). Cùng source/test/config hashes, không sửa code giữa cặp, không plugin timing trong hai full. Skip có sẵn không thay. JUnit/log trong artifacts/final-release-readiness.
20. **GUI:** frozen EXE0.1.1 trên Windows DPR1/1.25/1.5, Light/Dark, manual/background popup, plaintext notes, Later/download .testdata, SRT placeholder, Queue Clear All, Search/Replace/Undo, idle Safe Exit900ms và OS exit0 đều đạt; không native Qt crash. Source GUI bổ sung tạo TXT/DOCX hai đơn vị, import/edit/Search/Replace/Undo/render DOCX ở ba DPI, hash nguồn không đổi. Source fixture proof được ghi riêng, không giả là frozen DOCX E2E.
21. **Workspace:** root0 `.pytest_*`; temp/cache ở D:/TransComic-TestRuntime. Không xóa TestArchive/TestRuntime để đạt gate. Script DOCX đầu dùng sai rows thiếu locator và cleanup DB còn mở đã fail; sửa harness sang Store.units và giữ log lỗi; profile giả còn lại không dùng làm dữ liệu thật.
22. **Backend dịch:** không thay trong đợt này. Các diff backend/storage từ các đợt trước được giữ; không nhận là thay đổi mới.
23. **API thật:**0 Kira/Gemini; không reset ledger. GitHub chỉ đọc metadata/preflight, GUI dùng mocks.
24. **Installer host:**0; không installer/helper native trên host, không nâng admin, bật feature/Hyper-V hoặc reboot.
25. **Remote writes:**0 tag/draft/upload/publish/settings; không commit/push/source upload.
26. **Blockers:** thiếu guest/native install/upgrade/keep-data proof, source dirty chưa có origin/provenance, helper và BAT execution còn khóa; root cause Safe Exit lịch sử chưa hoàn toàn được chứng minh. Hai full xanh không thay các gate native.
27. **Tiếp theo:** quyền test guest đã được cấp, không cần hỏi lại ngân sách hoặc quyền đó. Cần một guest Windows truy cập được và xác minh; nếu phải bật tính năng/cài VM/reboot, người dùng tự thiết lập hoặc cấp quyền ở đợt riêng. Sau đó review activation/baseline guest riêng; chỉ khi đủ proof mới xin quyền commit/provenance và GitHub publication cụ thể.

## Artifact giữ nguyên

| File | Bytes | SHA-256 |
|---|---:|---|
| TransComic.exe | 77289085 | `86898ef3d587c40710ca2932acd0c2f28fc90d8d4622f37f00de62e591de2901` |
| TransComic-UpdateHelper.exe | 33768336 | `cd50ef89c87b072e71fa91c4eb947c1d0e07112aabde043b579d4c67d975f0ed` |
| TransComic-Setup-0.1.1-devtest-windows-x64.exe | 112844107 | `c41e81c23d48f31cb96652f92dc7008f441e05502f5d9542b6c2dcd4701cef1b` |

Manifest/checksum/notes nằm trong candidate cũ. Metadata verification dùng fixture offline; chưa có release/asset thật để remote-verify. Canonical installer alias có cùng bytes với devtest, không phải installer production đã nghiệm thu.

## Thiết lập guest tối thiểu (chưa thực hiện)

Người dùng chuẩn bị Windows Sandbox khả dụng hoặc một VM Windows hiện có, snapshot sạch, tài khoản guest và cơ chế điều khiển độc lập. Với Sandbox, chỉ map thư mục chứa bản sao artifact đã kiểm hash ở chế độ read-only; không map profile, DB, key hay source host. DB/TXT/DOCX/DPAPI giả phải tạo trong guest. Không chạy helper đang khóa hoặc dùng env/mock flag để mở khóa; cần review guest-only build/activation riêng, không đưa activation đó vào production. Khi chưa xác minh guest, dừng ở NATIVE UPDATE BLOCKED.

## Đề xuất nhóm commit (chưa stage)

### scripts/config

- `.gitignore`
- `TransComic.spec`
- `installer/TransComic.iss`
- `pyproject.toml`
- `release_transcomic.bat`
- `scripts/archive_pytest_outputs.py`
- `scripts/build_local.py`
- `scripts/cleanup_project.py`
- `scripts/console_gui_smoke.py`
- `scripts/final_docx_gui_smoke.py`
- `scripts/gui_smoke.py`
- `scripts/inspect_performance_layout.py`
- `scripts/internal_update_gui_smoke.py`
- `scripts/liquid_glass_gui_smoke.py`
- `scripts/local_exe_smoke.py`
- `scripts/multilingual_gui_smoke.py`
- `scripts/native_reparse.py`
- `scripts/performance_benchmark.py`
- `scripts/performance_gui_smoke.py`
- `scripts/provision_release_key.py`
- `scripts/release_transcomic.py`
- `scripts/retry_management_gui_smoke.py`
- `scripts/retry_mock_comparison.py`
- `scripts/retry_speed_benchmark.py`
- `scripts/review_gui_smoke.py`
- `scripts/shutdown_comparison.py`
- `scripts/stability_windows_stress.py`
- `scripts/stage2_gui_smoke.py`
- `scripts/test_runtime.py`
- `scripts/ui_v2_gui_smoke.py`
- `scripts/update_helper.py`
- `scripts/updater_gui_smoke.py`
- `scripts/workspace_speed_gui_smoke.py`
- `scripts/wrong_language_gui_smoke.py`

### docs

- `README.md`
- `docs/final-pytest-workspace-cleanup.md`
- `docs/first-local-build.md`
- `docs/internal-update-and-queue-clear.md`
- `docs/production-key-and-cleanup.md`
- `docs/release-signing-and-version-policy.md`
- `docs/update-and-release-preparation-0.1.1.md`
- `docs/workspace-cleanup-and-isolated-install.md`

### tests

- `conftest.py`
- `tests/qt_wait.py`
- `tests/test_first_local_build.py`
- `tests/test_internal_queue_clear.py`
- `tests/test_production_acl_cleanup.py`
- `tests/test_pytest_archive.py`
- `tests/test_qt_worker_wait.py`
- `tests/test_release_signing_version_policy.py`
- `tests/test_update_completion_lifecycle.py`
- `tests/test_update_release_readiness.py`
- `tests/test_updater_stage_a.py`
- `tests/test_window_lifecycle.py`
- `tests/test_workspace_hygiene.py`
- `tests/test_workspace_v2.py`

### source

- `transcomic/app.py`
- `transcomic/local_build_smoke.py`
- `transcomic/maintenance.py`
- `transcomic/provisioning.py`
- `transcomic/release.py`
- `transcomic/release_adapters.py`
- `transcomic/release_journal.py`
- `transcomic/release_pipeline.py`
- `transcomic/release_version.py`
- `transcomic/storage.py`
- `transcomic/ui/assets/nav-subtitles.svg`
- `transcomic/ui/main.py`
- `transcomic/ui/queue_clear.py`
- `transcomic/ui/update_dialog.py`
- `transcomic/ui/update_panel.py`
- `transcomic/ui/workspace_v2.py`
- `transcomic/update/authenticode.py`
- `transcomic/update/internal.py`
- `transcomic/update/keytools.py`
- `transcomic/update/service.py`
- `transcomic/update/windows_helper.py`

Báo cáo này cũng thuộc nhóm docs cần review. Không dùng `git add .`; đối chiếu từng file, dữ liệu cá nhân và source provenance trước commit. Danh sách có cả thay đổi từ các đợt trước.

## Bằng chứng

`artifacts/final-release-readiness/acceptance.json`, `source-before-regression.json`, `source-review.json`, `privacy-scan.json`, `guest-environment.json`, `timing-summary.json`, `timeline-before/after.json`, `reproduce-2.log`, `stress-after.log`, `focused-wait.log`, `focused-security.log`, `regression-1/2.log/xml`, `preflight/preflight.json`, `remote-tags/releases.json`, `candidate-archive/icon-audit.json`, `windows/<scale>` và `document-windows/<scale>`.

Cặp regression dùng python -m pytest -q với --junitxml để lưu bằng chứng. Stress dùng observer chỉ thu monotonic timestamps, không thay wait/assertion/worker. Lượt đầu native stress bị ngắt lúc startup và không có kết quả, không tính là PASS. Các log fail trước sửa đều được giữ.
