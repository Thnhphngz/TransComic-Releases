# Internal Update và Xóa toàn bộ lượt dịch

## 1. Files và phạm vi

Sửa `storage.py`, `ui/main.py`, thêm `ui/queue_clear.py`; thêm `update/internal.py`, mở rộng hooks của `update/service.py`, `ui/update_panel.py`, `update/windows_helper.py`, `release_adapters.py`, `release_pipeline.py`, `scripts/release_transcomic.py`, `scripts/update_helper.py`. Thêm `tests/test_internal_queue_clear.py` và `scripts/internal_update_gui_smoke.py`.

Không thay Kira/Gemini, scheduler, retry/batch/concurrency/prompt/locale/validator/DOCX/TXT/export engine, DPAPI, deadline Safe Exit 900ms, version carry, spec/ISS hoặc cấu trúc Liquid Glass. Những thay đổi chưa commit từ các đợt trước được giữ nguyên.

## 2. Nút Xóa toàn bộ

Trang **Hàng đợi & lịch sử → LƯỢT DỊCH**, nút ở bên phải “Xóa các mục đã chọn”. Các thao tác xóa đặt cùng một hàng riêng bên dưới resume/diagnostics để vừa cửa sổ nhỏ. Dùng GlassButton hiện có, Light/Dark/hover/pressed/disabled. Nút disabled khi danh sách rỗng hoặc đang xác nhận/xóa.

Dialog Glass `Xóa toàn bộ lượt dịch?` hiển thị số mục thực tế, cảnh báo không hoàn tác và dữ liệu được giữ. `Hủy` là default/focus. Cancel không ghi DB. Busy flag chặn double-click và các entry bắt đầu/resume/retry trong lúc xóa.

## 3. Chính xác dữ liệu bị xóa

Danh sách cũ chứa cả job và các mục `import:<document-id>` chưa có job. Snapshot tập entry được xác nhận; trong transaction kiểm tra tập thực tế không đổi. Xóa jobs mục tiêu, batches của jobs đó, request_attempts của batches đó, api_text_versions gắn với attempts đó, và translation_runs thuộc các job mục tiêu khi không còn jobs liên kết. Run không liên quan được giữ. Retry/diagnostic metadata trong graph này được xóa cùng records.

Các import/history entries được ẩn bền vững bằng marker `queue_hidden_<document-id>` trong settings; **không xóa document hoặc lines**. Khi tạo một job mới cho tài liệu đã giữ, job mới lại xuất hiện bình thường. Không đưa history đã xóa trở lại bằng fallback “imported” khi mở lại app. Các thao tác xóa hiện tại/chọn cũ giữ ngữ nghĩa cũ, không bị thay thế bằng xóa-all.

## 4. Dữ liệu được giữ

Document source snapshot, lines/source/translation, document_units, line_edits, quality warnings, workspace, file DOCX/TXT gốc và export trên disk. API secrets DPAPI/Kira/Gemini, gemini_keys, settings/theme/languages/export paths được giữ (chỉ thêm queue visibility markers). Không DROP TABLE, không xóa DB, không đổi schema. Updater cache/download/manifest và release journal ở ngoài queue graph được giữ nguyên.

## 5. Worker safety

Chặn khi scheduler thread alive, active/active_http request, background worker/import/export, window đang exit/closed. Pause có request vẫn bị chặn. Kiểm tra khi click, sau confirmation, ngay trước transaction và bên trong transaction; DB jobs running/pausing/stopping, batches inflight và attempts chưa finished cũng chặn. SQLite lock/transaction đang dùng không bị force: acquire nonblocking và abort an toàn.

GUI không start/resume/retry job khi clear busy; worker không kill/cancel HTTP, không reset retry. Worker thread được giữ trong `background_threads` để shutdown/Safe Exit hiện có chờ lifecycle. Completion đi qua queued Qt signal, refresh/reset current selection sau commit; error không báo success. Không sửa Scheduler.

## 6. SQLite transaction

Store lock giữ toàn bộ việc xác minh và transaction BEGIN IMMEDIATE. Xóa children trước parents; foreign_key_check trước commit. Exception rollback toàn graph, giữ dữ liệu. Empty queue trả 0 và không DELETE. Document và bản dịch không bị sửa; transaction rollback test dùng trigger SQLite abort thật. Deletion chạy background để SQL không block event loop lâu.

## 7. Tests xóa

Temporary DB: empty/import-only/one/many/shared-document jobs completed/error/paused/stopped, batches và retry attempts/API diagnostics, cancel/confirm/double-click, worker/inflight/confirmation race, transaction/DB error, FK, reopen và preservation của source/export/settings/opaque encrypted key fixture. GUI native test dùng DB/LOCALAPPDATA tạm, không DB thật của người dùng.

## 8. Internal architecture

Ứng dụng hiện khởi tạo **InternalUpdateService**. **UpdateService mặc định trong API code vẫn là Signed Stable**, giữ tests/crypto semantics cũ. Hai client dùng cache riêng (`internal-check-cache.json` và `check-cache.json`), không tự chọn policy từ manifest. Internal không nhận signed envelope hoặc public-key override; Signed Stable không chấp nhận Internal unsigned envelope.

Internal manifest có đúng envelope `{payload: {...}}`, `distribution_policy=internal`, `channel=internal`, metadata_format=2, generated_at UTC, app/platform/arch/version/tag/release URL/installer name/size/hash/minimum updater/Windows. Signed Stable envelope/signature và channel stable giữ nguyên. Phần validation release identity dùng chung checks có sẵn, nhưng Internal chỉ gán trạng thái riêng `VERIFIED_INTERNAL_HTTPS_SHA256`; không gán VERIFIED_ED25519 cho unsigned data.

## 9. Giới hạn tin cậy

SHA-256/checksum từ cùng GitHub Release chứng minh tính nhất quán file tải, **không xác minh danh tính publisher khi repository/tài khoản GitHub bị xâm phạm**. Internal không bảo mật ngang chữ ký số. Không bypass SmartScreen, Defender, UAC hoặc policy của Windows. Phải bảo vệ tài khoản/repository GitHub và giữ release notes rõ ràng.

## 10. Repository và GitHub Releases

Repo cố định `Thnhphngz/TransComic-Releases`; máy người dùng dùng HTTPS API công khai, không cần gh hoặc tài khoản. Latest API chỉ nhận release đã published, `draft=false`, `prerelease=false`, SemVer stable canonical. `internal` là policy của app/manifest, **độc lập** với cờ GitHub prerelease; Internal release hiện vẫn xuất bản non-prerelease để Latest chọn đúng. Không nhận Draft/Prerelease để thử cài.

Distribution main commit được người dùng cung cấp `6dc2d5378d27eb90a455b473b306fdd5d988da66`; preflight đọc state. Private application source và SHA không upload sang repo Releases; public provenance dùng schema allowlist/redaction cũ.

## 11. Version

VERSION vẫn **0.1.0**, proposal chưa reserve là **0.1.1**. Carry 0–9 giữ nguyên: 1.0.8→1.0.9→1.1.0, 1.9.9→2.0.0, 9.9.9→10.0.0. Generic updater SemVer không bị giới hạn patch ở 9. Staged version overlay/EXE resource/ISS/manifest/tag/title/filename dùng chung reserved version; không sửa source VERSION trong đợt chưa phát hành.

## 12. Journal

Reserve trước effects, failed/upload/publish unknown giữ version; reconcile remote trước resend. Confirmed published mới cho new intent bump. Journal bổ sung distribution_policy, từ chối thay policy khi resume. Không xóa tag/draft hoặc replace published assets để giải quyết lỗi. Mock response-loss test tại carry boundary giữ 1.0.9, không publish lần hai. Existing B1/B2 journal tests retained.

## 13. Build/Installer/release pipeline

Prepared ProductionReleaseOperations có policy explicit. Internal không prompt signing passwords hoặc yêu cầu Ed25519/cert; tạo unsigned Internal manifest và SHA256SUMS. Signed Stable giữ ký app/helper/installer + Ed25519. Phase tên SIGNED cũ được giữ để tương thích journal; trong Internal nó có nghĩa artifact/manifest/checksum sẵn sàng, không tuyên bố crypto signing.

Publisher explicit internal verify đầy đủ local/remote inventory, filename/tag/platform/size/hash/checksum/digest và bytes download, trước/sau publish. Internal tag preparation giữ tag đúng distribution commit hoặc tạo tag mới qua adapter sau activation; không move/delete tag. FakeCommands kiểm tra flow này, production commands vẫn fail trước effect. Draft incomplete/hash mismatch/upload timeout/publish unknown chặn publication như cũ.

BuildAdapter/PackageAdapter, staged source allowlist, stable per-user Inno AppId, keep-user-data và helper packaging được giữ. Không chạy PyInstaller/ISCC trong lượt này. Wheel lock/isolated tool environment/source provenance sạch/native installer tests vẫn cần trước first build/release, nhưng Ed25519 và SignTool không còn là prerequisites của Internal.

## 14. Downloader

Inherited bounded HTTPS streaming, fixed repo/tag asset URLs, redirect whitelist, size/hash, .part cleanup/cancel, progress/worker thread, rate-limit/cache/timeout. Internal check tải thêm SHA256SUMS và đối chiếu cả manifest raw hash + installer hash. Download rechecks frozen verified payload và release/asset binding; file reparse/path escape bị reject. Không URL lấy từ changelog; không tải tự động.

## 15. External helper

Giữ helper hiện có, thêm policy constructor/config explicit (không JSON policy tự khai). Internal validate/load_install_plan dùng Internal candidate; Signed Stable mặc định giữ verifier. Plan không có arbitrary exe/path/key/policy fields. Fixed per-user installed app, exact PID+creation time+image, wait exit, revalidate/hash+held file handle, installer code/new version/restart được giữ. Internal handoff bỏ yêu cầu Authenticode riêng theo explicit policy; hash-verified copied helper vẫn cần, không ghi đè helper đang chạy.

**Native helper entry/run/handoff vẫn locked**; trong đợt này chỉ FakeWindowsRuntime. Native process/file locking, readiness acknowledgement, installer VM/version/restart health cần chứng minh khi người dùng cấp quyền sau. Không coi simulated success là install thật.

## 16. Safe Exit

Không đổi deadline 900ms hoặc scheduler cleanup. Busy/inflight/transaction/editor/safe-exit-unverified/logger flushing/unknown/cancel barriers vẫn chặn install. Không kill app đang dịch, không tự restart sau install failure, không báo success trước new-version verification.

## 17. SQLite/DPAPI và upgrade

Queue deletion giữ manuscript/key/settings; không xóa filesystem updater/release data. Installer per-user chỉ program installation; SQLite/DPAPI dưới LOCALAPPDATA/TransComic giữ nguyên. Existing WAL backup/opaque blob/schema compatibility/rollback tests vẫn chạy. Native real upgrade chưa chạy; không tuyên bố migration/upgrade thực đã được xác minh.

## 18. GUI Windows

`scripts/internal_update_gui_smoke.py` chạy qua `run_transcomic.py` trên Windows, isolated temp data, HTTP guard/mocks. Đo DPR thực 1/1.25/1.5 (QT factor .8/1/1.2 trên desktop 125%). Light/Dark, queue 900×580/1200×720, button/dialog/cancel/count/clear/reset, retained manuscript Search/Replace/undo; Internal update available/download/helper mock và suite Signed Stable download/cancel/hash/offline/logger mocks. Screenshots/report dưới `artifacts/internal-update-and-queue-clear/windows`.

## 19. Regression evidence

Focused existing suites: 202 passed/1 skipped. Expanded focused release/queue/updater suite: 352 passed/1 skipped before final empty-queue case. Final full results recorded below after completion. Không xóa/nới assertion, không reset API ledger, không thay skip để báo xanh. Lỗi fixture/setup ban đầu (shared job flag, page selection, fake process identity/install failure switch, remote release id) đã sửa setup; logs adverse retained.

## 20. Before first real build/release

Cần người dùng cấp quyền riêng cho build PyInstaller + ISCC, native installer/update tests trong VM, và tag/draft/upload/publish. Cần commit final reviewed source để có clean exact source provenance, verify tool/version/hash lock, distribution commit/release journal state. Execution guards cần reviewed source activation, không flag/env bypass. Internal không cần tạo signing key, passphrase, USB hoặc mua cert/SignTool. First build approval không tự cho phép GitHub publication/install.

## 21. One BAT

Hiện có thể chạy an toàn:

```powershell
.\release_transcomic.bat
.\release_transcomic.bat --policy internal
.\release_transcomic.bat --policy signed-stable
```

Mặc định Internal dry-run; preflight báo tools/source/repo/journal/proposal, bỏ signature/SignTool blockers của Internal, giữ tất cả action guards. Maintenance workflow vẫn có nhưng lượt này chỉ inventory/dry-run, không xóa thêm cache chưa xác minh. Sau reviewed activation và quyền riêng, cùng BAT sẽ nối coordinator: preflight→reserve/confirmation→pytest→build/package→manifest/checksum→tag/draft→upload→remote verify→publish→independent verify/report. Native actions hiện chưa được mở.

## 22. Máy người dùng

Vào Cài đặt → Cập nhật ứng dụng, xem phiên bản/notes/size, tự nhấn “Tải và cài đặt” hoặc “Để sau”. Internal không bị chặn download vì public pin trống; HTTPS/hash/checksum verification vẫn bắt buộc. Hiện download hoạt động, trạng thái cho biết chưa kích hoạt installer; bước safe-exit→wait process→install→version→restart chỉ mô phỏng. Không auto-install; account/gh không cần trên máy người dùng.

## 23. Signed Stable tương lai

Giữ signing/provisioning/TrustPolicy/Authenticode và tests cũ. Không tự tạo key hoặc pin. Khi sau này muốn Signed Stable, cần policy source configuration explicit, reviewed trust anchor/cert/backup/native proof và quyền riêng. Không tự downgrade sang unsigned sau signature failure.

## 24–25. Quyền và hành động thực tế

Không gọi Kira/Gemini thật; không xóa dữ liệu SQLite thật; không tạo production key, không build EXE/installer, không chạy installer, không tạo/push tag/Release, không upload/publish, không commit/push. Git working tree giữ các thay đổi chưa commit. Cleanup chỉ báo inventory; user data và API ledgers giữ nguyên.

## Nghiệm thu cuối

**INTERNAL UPDATE + QUEUE CLEAR READY FOR FIRST BUILD APPROVAL**

| Kiểm tra | Kết quả |
|---|---|
| Focused queue/Internal cuối | 48 passed, 11.17s |
| Full cuối 1 | **776 passed, 1 skipped**, 189.47s |
| Full cuối 2 | **776 passed, 1 skipped**, 190.63s |
| GUI cuối Light/Dark DPR 1 / 1.25 / 1.5 | Đạt queue/dialog/cancel/clear/reset/preservation/Search-Replace và cả Internal/Signed Stable updater mocks |
| Source giữa hai full và GUI cuối | SHA khớp `source-final.json`, không sửa mã trong cặp cuối |
| Native crash | Không có trong hai full cuối và ba GUI cuối |
| Dữ liệu gốc và API ledger | Hash không đổi; không reset quyền API hoặc dữ liệu |
| VERSION / proposal | 0.1.0 / 0.1.1; version nguồn chưa sửa |
| BAT / external helper | Vẫn khóa thực thi build/release/install |

Bằng chứng: [acceptance.json](../artifacts/internal-update-and-queue-clear/acceptance.json), [full 1](../artifacts/internal-update-and-queue-clear/regression-final-1.log), [full 2](../artifacts/internal-update-and-queue-clear/regression-final-2.log), JUnit XML cạnh logs, `source-final.json`, `scope.json`, `protected-data.json`, `preflight.json`. GUI cuối lưu dưới `artifacts/internal-update-and-queue-clear-final/windows/{0.8,1,1.2}`; mỗi folder có screenshots, `report.json` và `internal-queue-report.json`. GUI trước đó được giữ riêng.

Hai lượt full sơ bộ 775 passed/1 skipped (195.84s và 205.97s) được giữ, nhưng lượt thứ hai có thay đổi source khi đang chạy, nên không dùng làm bằng chứng cùng mã. Rà soát cuối thu hẹp xóa translation_runs chỉ cho run của job mục tiêu và thêm test giữ run không liên quan; sau đó chạy lại cặp nghiệm thu đầy đủ nêu trên, không nới assertion hoặc skip.

Preflight Internal thực tế vẫn dry-run/locked, repo/source/journal được đọc; không yêu cầu production key/backup/cert/SignTool. Cleanup chỉ dry-run: 6 candidate cache, 97 mục pending được giữ; không apply cleanup trong đợt này. Source HEAD vẫn `6fd3f061c3c78fcae3ec4ebd467858346441ff56`, main, working tree dirty như dự kiến và chưa commit.

Bước tiếp theo cần quyền riêng: reviewed activation và build PyInstaller/ISCC đầu tiên; sau đó native installer/update VM tests và quyền tag/draft/upload/publish cụ thể. Cần commit source đã review và xác minh provenance/toolchain/journal trước hành động thật. Chưa báo production released hoặc upgrade thật thành công.
