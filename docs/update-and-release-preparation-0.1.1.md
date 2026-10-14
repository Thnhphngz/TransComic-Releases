# Update và release preparation 0.1.1

**PARTIAL — BLOCKERS REMAIN**

**LOCAL RELEASE CANDIDATE — NOT PUBLISHED**. LOCAL_ARTIFACT_READY đạt; code readiness đầy đủ còn rủi ro popup gián đoạn, native install/update và GitHub release readiness vẫn bị chặn.

## 30 mục bàn giao

1. Các nhánh verifier/downloader/popup/helper được kiểm thử; chuẩn bị plan dùng chung và receipt installer không rõ đã nối vào GUI helper simulation. Native Handoff.launch/WindowsRuntime/helper entry vẫn khóa, chưa có adapter kích hoạt cài thật. Chưa đóng gate CODE_READY đầy đủ do rủi ro popup gián đoạn; không coi mock là native end-to-end.
2. Popup manual verified-only, auto no-popup, plain notes, Later/X/Escape/cached304/duplicate behavior giữ nguyên; binary GUI xác minh.
3. Internal repo/tag/asset/platform/name/size/hash/time binding đạt với fixtures. Signed Stable giữ riêng, không downgrade sang Internal. Checksum cùng Release chỉ kiểm tra consistency, không thay publisher signature.
4. Downloader timeout/cancel/offline/redirect/rate limit/hash/size/partial cleanup có test; thêm safe_path trước ghi/cache/rename chống thay directory bằng junction. Negative native junction test bảo toàn external sentinel. Không resume .part tự động; request/download lock giữ nguyên.
5. Safe Exit đã tái hiện trong hai raw full: regression-preliminary-failed có2 lỗi900ms và lỗi nhãnBAT; regression-pre-yield-failed có1 lỗi900ms. Method-observer full814pass1skip (227.28s) không tái hiện; durations trong shutdown-summary-full.json. GUI _finish_safe_exit đổi sleep(0) thành bounded sleep1ms để nhường scheduling Windows; không join/kill hoặc nới deadline. 19 original stability/lifecycle sau đổi đạt17.99s. Hai full cuối và GUI ghi dưới. Đây là mitigation với giả thuyết scheduling, không khẳng định exhaustive root cause/nativeproof. Profiler tổng quát đầu không tiến triển đã dừng Ctrl-C, log giữ; không force-kill app/worker.
6. Helper vẫn khóa native before handles/copy/exec; fixed registered Inno path/trusted Internal policy, PID+creation time+image, reverify hash, newer-version floor và journal outcome guard. Plan JSON không điều khiển executable/directory/keys/policy. Launch app→helper native chưa kích hoạt và chưa chứng minh readiness.
7. Không native update thật; FakeWindowsRuntime không được coi là native proof.
8. Không tìm thấy guest khả dụng ở environment probe trước; không tự bật features/Hyper-V/reboot. Guest install/update BLOCKED.
9. Đã build candidate overlay0.1.1 staging riêng, dirty devtest snapshot, source VERSION0.1.0 giữ nguyên; không reserve journal.
10. D:\Sourch Code\TransComic\artifacts\release-preparation\0.1.1-local-candidate\source\dist\TransComic.exe
11. D:\Sourch Code\TransComic\artifacts\release-preparation\0.1.1-local-candidate\installer\TransComic-Setup-0.1.1-devtest-windows-x64.exe
12. D:\Sourch Code\TransComic\artifacts\release-preparation\0.1.1-local-candidate\proposed-assets chứa installer tên canonical, Internal transcomic-update.json và SHA256SUMS.txt; canonical installer là alias bản devtest cùng bytes. Metadata verification chỉ offline synthetic fixture, không giả assetID/remote production verified.
13. Python/PyInstaller/PySide6/cryptography/Git/gh trong build-report.json; Inno6.7.3 header iscc.log. Icon Win32 DATAFILE resource hashes khớp nguồn; Qt DLL/SVG/helper package present.
14. Source0.1.0, proposal/tag0.1.1/v0.1.1. Carry0..9/no-double-bump có existing test, overlay không sửa main source.
15. Dirty/untracked source được ghi git-state.json/build-inputs.json; HEAD baseline, không clean commit; cần review/commit source/provenance riêng trước public release. Không source origin đã xác minh, không đổi remote sang distribution.
16. GitHub read-only repo public main có commit; releases=[]/tags=[]; latest404. Chưa conflict v0.1.1. Read API không chứng minh future mutations được phép.
17. Journal production absent/unchanged theo journal-state.json; tests resume/interruption/conflict/reconcile trên journal/mock riêng, không reserve production.
18. BAT dry-run exit0 và preflight.json, phases native/remote khóa. Sửa build stage marker và ISCC flag để adapter staged version dùng cùng spec; mọi ProductionCommands/ReleaseCoordinator.run vẫn locked. Chưa bật thực thi one-click publish.
19. {'tests': '817', 'failures': '0', 'errors': '0', 'skipped': '1', 'time': '223.578', 'passed': 816}
20. {'tests': '817', 'failures': '0', 'errors': '0', 'skipped': '1', 'time': '225.404', 'passed': 816}
21. Candidate EXE frozen0.1.1 Light/Dark DPR1/1.25/1.5 mở/dịch văn bản fixture/SRT/popup/mock downloader/queue clear/SearchReplaceUndo/SafeExit/realprocess exit0. Dữ liệu tạm ngoài workspace, HTTP guard.
22. Không native Qt crash trong hai full cuối và ba binary smoke.
23. Root0 .pytest_*; runtime/cache riêng ngoài project, không cleanup để che sai config.
24. Không dùng/chỉnh DOCX/TXT/SQLite/DPAPI/key thật; package archive allowlist không user DB/keys/tests/artifacts. Template Word dependency và CA PEM công khai được phân biệt. Old build toàn tree hash không đổi.
25. Không Kira/Gemini thật, không reset API ledger.
26. Không backend dịch/scheduler/SQLite/DPAPI changes. Chỉ GUI shutdown bounded yield1ms; app smoke fixture dùng bumped VERSION để candidate không nhầm phiên bản bằng nhau.
27. Không installer host hoặc guest; chỉ ISCC compiler và resource read-only.
28. Không tạo/push tag/commit/GitHub Draft/Release.
29. Không upload/publish. Release notes Việt mô tả đúng Internal/popup/clear/SRTplaceholder; không quảng cáo native upgrade/Windowsclean/backend improvements.
30. Native installer not tested in verified Windows guest; Native upgrade 0.1.0 → 0.1.1 not tested; host execution stays locked; Dirty source with untracked files; clean exact reviewed source commit and repository identity required; Remote tag/draft/upload/publish approvals and journal reconciliation required; no mutation authorization; Safe Exit 900ms failure reproduced; bounded GUI scheduling mitigation tested, exhaustive root cause/native safety not proven; Release BAT is read-only preflight; execution adapter remains locked pending reviewed scoped activation; Immutable 0.1.0 devtest app/helper also has native install locks; a separately reviewed guest baseline/activation is needed for an actual 0.1.0 → 0.1.1 upgrade trial; Two popup tests intermittently failed after CRLF with no dialog observed; isolated retest passed and subsequent failure-only telemetry did not reproduce it. Root cause not proven fixed; retain as readiness risk.
31. Bước tiếp: guest Windows được xác minh và quyền install/uninstall/reinstall/native upgrade riêng; source review+commit/privacy/repo identity; quyền cụ thể tag/draft/upload/verify/publish và scoped activation. Không coi quyền BUILD_LOCAL là remote write/install.

## Artifact và SHA-256

| File | Bytes | SHA-256 | PE/version |
|---|---:|---|---|
| TransComic.exe | 77289085 | `86898ef3d587c40710ca2932acd0c2f28fc90d8d4622f37f00de62e591de2901` | x64 / 0.1.1.0 |
| TransComic-UpdateHelper.exe | 33768336 | `cd50ef89c87b072e71fa91c4eb947c1d0e07112aabde043b579d4c67d975f0ed` | x64 / 0.1.1.0 |
| TransComic-Setup-0.1.1-devtest-windows-x64.exe | 112844107 | `c41e81c23d48f31cb96652f92dc7008f441e05502f5d9542b6c2dcd4701cef1b` | x86 / 0.1.1.0 |

## Ma trận luồng update

| Bước | Code / kiểm chứng | Native |
|---|---|
| 1–4 check/metadata/version | update/service.py + internal.py; existing/new mocks | GitHub đọc preflight thật, GUI dùng mocks |
| 5–7 status/popup/choice | ui/update_panel.py + update_dialog.py; manual/auto/cached tests | Windows GUI source/binary |
| 8–9 download/reverify | service.download/verify_file | fake .testdata only |
| 10–12 Safe Exit/plan/app quit | main._finish_safe_exit; prepare_install_plan; GUI simulate_production_helper | app quit proved; helper launch locked |
| 13–14 identity/wait/reverify | ProductionUpdateHelper.run, WindowsRuntime | concrete mocks; native methods locked |
| 15–19 install/result/version/restart/status | runtime.install/installed_version/restart; durable install receipt | not executed; no REAL UPDATE PASS |

Receipt INSTALL_OUTCOME_UNKNOWN được ghi/fsync trước executor. Crash/timeout hoặc mismatch không tự replay installer; INSTALLED_RESTART_PENDING chặn reinstall khi restart thất bại, cần manual reconciliation. COMPLETED chỉ sau installed-version match và restart preference thành công. Journal không mở native quyền.

## Pipeline và gates

release_transcomic.bat là entry point phát hành duy nhất; hiện preflight-only. Existing ReleaseCoordinator/RealReleaseOperations/BuildAdapter/PackageAdapter/GitHubPublisher có tests concrete fake phases từ precheck→tests→build→package→manifest→draft→upload→remoteverify→publish→reconcile. Không thay adapters bằng commands thật trong lượt này. scripts/build_local.py chỉ BUILD_LOCAL snapshot; không là workflow release thứ hai. Mọi GitHub writes vẫn unconditional locked.

Build lệnh: `python scripts/build_local.py --candidate-version 0.1.1 --output artifacts/release-preparation/0.1.1-local-candidate`. Source-final.json đối chiếu sau gates; staging hash overlay khai báo riêng. Two final tests giữ cùng source. Binary source snapshot không chứa test harness; artifact candidate không thể chạy installer/helper native vì locks giữ nguyên.

Bằng chứng: artifacts/release-preparation/acceptance.json, git-state/source-final/journal-state.json, repo/remote-tags/remote-releases.json/latest-response.txt, bat-preflight.log/json, focused*.log, shutdown-summary/timeline.json, regression1/2log/xml, candidate archive/icon audit, candidate-windows/<scale>. Old artifact0.1.0 không sửa.

## Giới hạn điều tra shutdown

Python Windows dùng Sleep(0) cho sleep(0); zero timeout có thể trở về ngay nếu không có thread khác sẵn sàng. Sleep thực tế có thể kéo dài do scheduling; 1ms là thời gian yêu cầu nhường CPU, không là bảo đảm wall-clock. Quan hệ với lỗi Qt/asyncio ở đây là giả thuyết từ raw/observer và các regression sau mitigation, chưa chứng minh root cause hoàn toàn. [Python time.sleep](https://docs.python.org/3.13/library/time.html#time.sleep), [Microsoft Sleep](https://learn.microsoft.com/en-us/windows/win32/api/synchapi/nf-synchapi-sleep).

Timeline full có cả active workload: Scheduler._run_thread max8.95s không phải shutdown latency. Observer full: Runner.close max44.166ms, DiagnosticLog.close30.128ms, Store.close30.99ms, finish_batch16.013ms. Không gộp các phase thành thời gian thoát tối đa. Deadline900ms và assertion dữ liệu/request cũ giữ nguyên.

## BAT Windows và gate cuối

Chạy BAT sau binary smoke phát hiện cmd.exe parse mất ký tự đầu lệnh khi file chỉ LF. Chuẩn hóa CRLF, không thay nội dung logic; test BAT được tăng assertion stderr phải rỗng. bat-preflight-crlf exit0 không parsing error, json vẫn dry-run/locked. Các log bat-preflight-final/confirm chứa kết quả trước sửa được giữ. Sau sửa chạy lại hai full trên cùng bytes cuối; không build lại candidate vì BAT/tests không thuộc package input allowlist và runtime/source hashes của binary vẫn khớp.

Lịch sử giữ nguyên: regression-preliminary-failed (nhãnBAT + 2 SafeExit), regression-pre-yield-failed (1 SafeExit), regression-diagnostic (observer814pass1skip), regression-pre-handoff-1/2 (814pass1skip), regression-pre-crlf-1/2 (816pass1skip), regression-1/2 là final pair sau CRLF. Không dùng các lượt trước thay cho gates cuối.

Sau CRLF có một full 814passed/2failed/1skipped: test_popup_notes_plain_text_and_other_modal_not_stolen và test_http_304_cache_popup_does_not_claim_no_network không quan sát được dialog trước deadline. Giữ regression-post-crlf-popup-failed.log/xml. Chạy riêng hai case đạt (12.83s), chưa sửa/nới test. Final pair sau đó: lượt1 thêm plugin popup_diagnostic chỉ đọc trạng thái khi fail, không thay Qt/worker/deadline; lượt2 không plugin. Không có failure snapshot khi không tái hiện. Chưa chứng minh root cause popup đã hết nên CODE_READY=false dù final regression xanh; cần thêm điều tra trước activation/native release.
