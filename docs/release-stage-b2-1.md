# TransComic — Release Stage B2.1

Ngày thực hiện: 14/10/2026. **B2.1 CODE READY — ENVIRONMENT/SECURITY BLOCKERS REMAIN**. Hai full regression cuối cùng mã/hook đạt **674 passed,1 skipped** mỗi lượt; GUI Windows ba DPR đạt. Version source giữ **0.1.0**, PATCH đề xuất **0.1.1**. Chưa PRODUCTION READY; B2.1 không cấp quyền cài công cụ, tạo production key, build, cài, tag hoặc phát hành. Lỗi timing Safe Exit ở lượt trước được giữ trong báo cáo, nguyên nhân chưa xác định.

## 1. Toolchain Windows

[Environment mới](../artifacts/release-stage-b2-1/environment.json), [BAT preflight](../artifacts/release-stage-b2-1/preflight.json), [package ID winget](../artifacts/release-stage-b2-1/winget-package-ids.json).

| Tool | Trạng thái / phiên bản / executable | Hành động trước B2.2 |
|---|---|---|
| Python | 3.13.14, x64; `C:\Users\Admin\AppData\Local\Programs\Python\Python313\python.exe`; chưa venv | Venv + kiểm tra dependency lock trên máy sạch |
| PySide6 | 6.11.1, Windows GUI đã thử | Giữ pin; thử plugins trong build thật |
| PyInstaller | 6.22.0, package đã cài; không chạy builder | Kiểm thử EXE thật chỉ khi được phép |
| Git | chưa phát hiện PATH/common paths/registry | Xác định portable custom path hoặc xin quyền cài |
| gh | 2.102.0, x64, `C:\Program Files\GitHub CLI\gh.exe`; auth được xác nhận | Không cài lại; giữ Keyring, không log token |
| Inno Setup 6 | chưa phát hiện PATH/common paths/registry | Xác định custom path hoặc xin quyền cài 6.x |
| SignTool | chưa phát hiện PATH/Windows Kits x64 | SDK signing tools chính thức, signer policy |
| Windows / PowerShell | Windows AMD64/x64; PowerShell 5.1.26100.9444; system powershell.exe | BAT thực đã chạy trong test từ cwd có dấu cách |
| Build deps/lock | Exact pins `requirements-release.lock` khớp môi trường; cryptography50.0.2/pytest9.1.1 | Chưa wheel hashes/clean install; còn blocker reproducibility |

Discovery dùng PE machine header để phân biệt x64/x86/ARM64, lấy file version qua Windows version API, không chạy ISCC/SignTool/PyInstaller. Inno compiler x86 có thể build target x64 nên không coi x86 ISCC là lỗi kiến trúc app. Version Inno khác6.x bị đánh dấu incompatible. “Chưa phát hiện” không có nghĩa đã chứng minh không tồn tại bản portable ở mọi thư mục.

Package IDs đã kiểm tra bằng `winget show`, không cài. Lệnh dành cho người dùng sau khi cho phép:

```powershell
winget install --id Git.Git -e --source winget
winget install --id JRSoftware.InnoSetup -e --source winget --version 6.7.3
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-release.lock
```

Git available2.55.0.5, Inno6.7.3 tại thời điểm kiểm tra. Không thay PATH toàn máy. SignTool lấy từ [Windows SDK chính thức](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool), chọn Windows10/11 SDK và thành phần **Windows SDK Signing Tools for Desktop Apps**, dùng executable x64. Không tải signer/certificate từ site bên thứ ba. Việc cài cần quyền riêng; lệnh trên chưa chạy và chưa được kiểm chứng bằng cài sạch.

## 2. Source provenance và distribution

**SOURCE_PROVENANCE_NOT_READY**: chưa có Git executable được xác minh, không thấy `.git` marker tại workspace/ancestors. HEAD/branch/Git root/dirty/untracked/source remote/private status chưa xác minh; không giả gọi workspace clean. Không init/add/commit/reset/tag/push.

`ReadOnlyInspector` có code kiểm tra Git root, exact HEAD, branch, porcelain status và untracked build files khi có Git. Raw remote có thể chứa credentials nên không trả ra report/public manifest. Source remote privacy vẫn unknown cho tới khi được xác minh riêng; không tự công khai source repository.

Repo phân phối cố định `Thnhphngz/TransComic-Releases`, public. Metadata khai báo default `main`, nhưng branches trả `[]` và GET commits trả **409 Git Repository is empty**. **DISTRIBUTION_REPO_NEEDS_INITIAL_COMMIT**. [Proof commits](../artifacts/release-stage-b2-1/distribution-commits.json). B2.2 cần người dùng quyết định initial commit/default branch/tag commit của repo này; không đưa private source commit sang distribution.

Internal build metadata có source_commit/source_tree_state/source_repository/private flag/build_id/build_timestamp/version/platform/architecture/toolchain_versions/artifact hash. `public_provenance` mặc định chỉ cho build/version/platform/tool versions/artifact identity; **không source URL/name/HEAD/branch/root**. Disclosure source fields cần policy được phê duyệt riêng; public values được validate, không credential/path/token. Source SHA và distribution SHA luôn có vai trò riêng. GitHub có thể cung cấp source archives của distribution repo; giữ repo đó tối giản, không chứa source riêng tư.

## 3. Version, source staging và journal

Nguồn duy nhất vẫn `transcomic/version.py`. BAT giữ banner khóa B1 và thêm B2.1 environment/security preflight; cùng một BAT/script, không CLI production switch. DefaultPATCH0.1.1; MINOR/MAJOR/explicit có tests, dry-run không sửa source.

BuildAdapter chỉ nhận clean verified source identity. Future build export explicit code/resource allowlist sang stage riêng, sinh VERSION đã chọn và ISS include từ một version source trong stage. Không sửa working tree original, không build source dirty âm thầm. Metadata ghi rõ **clean base source + declared generated version overlay**, có SHA của version overlay; build_id tính lại trên identity gồm overlay. Không tuyên bố mọi byte artifact nguyên trạng HEAD khi có generated overlay.

ReleaseJournal: PRECHECK, VERSION_SELECTED, TESTED, BUILT, PACKAGED, SIGNED, DRAFT_CREATED, ASSETS_UPLOADED, REMOTE_VERIFIED, PUBLISHED, FAILED, UNKNOWN_REMOTE_OUTCOME. Exclusive `.lock` mở O_EXCL, atomic `.part`/flush/fsync/replace; stale lock không tự xóa, cần recovery. Không double bump; mọi failed/unknown giữ reservation. Direct checkpoint PUBLISHED bị chặn: chỉ reconcile với remote tag/build_id/assets verified/published evidence. Journal corrupt dừng.

ReleaseCoordinator.run luôn khóa trước reserve/side effect. simulate chỉ concrete FakeReleaseOperations. Checkpoint từng bước, ghi UNKNOWN_REMOTE_OUTCOME **trước publish**, tránh crash giữa write và local save tạo blind retry. Unknown/local final save failure đọc remote rồi reconcile. Draft partial upload đọc lại inventory, skip asset giống digest, asset khác dừng; không overwrite/delete. Pending source origin đổi bị chặn. Sau prior publish đã verified, new build intent có thể reserve PATCH kế từ version vừa published, không lệ thuộc source dev0.1.0 chưa thay.

ProductionReleaseOperations có code nối test→build→package→Authenticode→hash→Ed25519→draft→upload→remote verify→publish/recheck. Restore stage paths/artifact inventory/provenance bị ràng buộc workspace/hash; unknown remote không retry publish mù. Partial signing outputs/stale locks giữ lại để review, không tự xóa toàn bộ output tree/rollback. Native pipeline chưa thực thi; cần thử interruptions trong VM/approved Draft tại B2.2.

## 4. Build, installer và command execution

BuildAdapter/PackageAdapter nhận absolute tool/work/output paths, version validated, argv lists/shell=False, timeout và exit code. Command capture có byte limit, structured audit events không argv/body/password/token/raw stdout/stderr. Deadline/overflow chỉ dừng **tool child do runner sở hữu**, không app/installer; remote outcome vẫn unknown. ProductionCommands có unconditional lock trước Popen, không env bật được. FakeCommands kiểm tra chính argv/response paths mà không subprocess.

Staging chỉ run entry, pyproject/lock/spec, runtime Python, SVG/icon, ISS và hai build/helper scripts cần thiết. Không user documents/DB/DPAPI/log/cache/keyring/.env/private keys. Kiểm tra symlink/junction/reparse ancestors, escape workspace, credentials trong source, missing resources/deps, pin mismatch. Cleanup chỉ own temporary `.part`; không recursive delete user paths. Version labels/EXE/ISS/tag/filename theo cùng version.

Spec vẫn RuntimeError lock đầu file; chuẩn bị **app EXE + TransComic-UpdateHelper.exe** trong cùng spec. Helper có icon/version/OriginalFilename riêng, không Qt UI. ISS vẫn #error lock, per-user/Win10-11x64/stable AppId/UsePreviousAppDir, install helper cạnh app, giữ user LOCALAPPDATA data. Desktop optional, không UninstallDelete/close/kill/restart app tự động. Chưa compiler/build/test installer thật. Cần kiểm tra dependency closure, helper packaging, old AppId/location/admin install compatibility tại B2.2.

## 5. Ed25519 provisioning và trust chain

`keytools.py` có provisioning/sign implementation; `scripts/provision_release_key.py` production luôn khóa **trước password prompt/RNG/mkdir/file access**. Không tạo production key. `--test` chỉ temp directory, password random, purpose=test/ID=test-..., directory bị dọn sau demo, không pin vào production.

Private key PKCS8 encrypted/BestAvailableEncryption, passphrase không argv/BAT/log. Windows owner-only protected DACL implementation restrict/verify; B2.1 chỉ FakeACL tests, **native ACL chưa chạy/xác minh thực tế**. Ngoài Git/app/EXE, không overwrite existing directory/key; incomplete provisioning giữ để review. Export public key/derived ID, kiểm tra key pair, warning encrypted offline backup chưa xác minh. [Cryptography serialization](https://cryptography.io/en/50.0.2/hazmat/primitives/asymmetric/serialization/).

Password-protected encrypted backup tách riêng khỏi máy dev, secret được quản lý riêng, kiểm tra restore trong môi trường cô lập trước ký production. DPAPI user scope gắn profile/máy, không phải backup đầy đủ; [Microsoft DPAPI](https://learn.microsoft.com/en-us/windows/win32/SecCrypto/example-c-program-using-cryptprotectdata). B2.1 không đổi DPAPI blob/API key người dùng, không thêm fallback plaintext. PKCS8 encrypted là phương án code hiện có; DPAPI wrapping không được giả tuyên bố đã triển khai.

**PRODUCTION_SIGNING_NOT_READY**: PRODUCTION_KEYS và PRODUCTION_KEY_STATUS đều rỗng. Status active/retiring/revoked được chuẩn bị; verify từ chối unknown/test namespace/revoked. Không lấy pubkey từ release/install JSON. Rotation: phát hành client pin old+new trước chuyển signer; revoke phải qua trust anchor còn hợp lệ/reviewed client update. Không thể revoke key trong app offline cũ chỉ bằng xóa asset GitHub; nếu mất toàn bộ anchor cần recovery ngoài updater. Tests ephemeral keys kiểm tra sign/wrong ID/signature/tamper/rotation/revoke/no overwrite/no logs; test namespace không trở thành production anchor.

## 6. Authenticode policy

**AUTHENTICODE_NOT_CONFIGURED**: chưa chọn certificate/thumbprint/subject/publisher hoặc xác minh chain. B2.1 không mua/tạo/import cert. Production public pipeline yêu cầu configured Authenticode; internal unsigned EXE test cần đợt phê duyệt riêng, không automatic fallback unsigned trong updater.

AuthenticodeAdapter chuẩn bị SignTool SHA256 + HTTPS timestamp, verify `/pa /all`, đối chiếu valid status/expected thumbprint/subject/timestamp từ Windows signature API qua PowerShell. Mọi command locked/fake. Hash và manifest phải tính sau Authenticode. Ed25519 là metadata trust, Authenticode là Windows publisher policy; không cam kết Windows/SmartScreen tin app hoặc hết cảnh báo. [SignTool chính thức](https://learn.microsoft.com/en-us/windows/win32/seccrypto/signtool).

## 7. GitHub production adapter

GitHubPublisher cố định repo, code read/release/tag/draft/upload/verify/publish/recheck nhưng execution default khóa. Explicit HTTP404 khác403/timeout; tag phải trỏ distribution commit đã duyệt, không tự tạo/move tag. Policy hiện chấp nhận lightweight commit refs; annotated/unknown refs dừng để review. Public release body validate disclosure policy/build_id; không source zip/private DB/token.

Inventory bắt buộc installer/transcomic-update.json/SHA256SUMS.txt, version match, hash/size rechecked, valid Ed25519 envelope và checksum before publish. Download lại remote bytes so hash/size/digest; assets chưa uploaded/missing/extra/conflict bị chặn. Bound release URL/tag/platform/manifest và build_id khi public provenance được khai báo. Published remote thiếu timestamp bị từ chối; already published verify/read-only return, không publish lại. [GitHub Releases API](https://docs.github.com/en/rest/releases/releases?from=20421). Không REST write/gh create/upload/edit/git push trong đợt này.

## 8. External helper implementation và giới hạn

`windows_helper.py` giữ original process handle, PID+creation FILETIME+expected image, wait real exit có cancel/deadline, không kill. JSON không cung cấp executable/install path/public key. Plan fields allowlist/size/strict JSON/signature/version/hash/size/pid/restart/safe exit. Script entry `scripts/update_helper.py` khóa trước đọc plan/OS handles. Helper được cài cạnh app nhưng handoff chuẩn bị **bản sao đã xác minh Authenticode/hash trong Updates**, chạy bản sao để installer thay helper/app đã cài. Install location lấy từ registry HKCU AppId cố định, không JSON; hiện policy chỉ per-user dưới user home, custom/admin locations cần review/manual flow. App/helper EXEs được chuẩn bị ký trước package, installer ký sau package. Dist path trong stage đồng bộ với Source trong ISS.

Handoff/registry/native process chưa chạy thật. B2.2 cần kiểm chứng process-handle ready acknowledgment trước parent exit, cancellation và startup-health handshake; không cam kết mọi timing chỉ từ việc Popen helper thành công. Nếu chưa mở được original process handle thì helper dừng, không chạy installer hoặc báo thành công.

Revalidate signature/path sau process wait, reject traversal/junction/symlink/reparse, CreateFile no-write/delete handle giữ qua hash+launch+installer wait, final handle path đối chiếu fixed expected path. [Microsoft CreateFile](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilea?redirectedfrom=MSDN). Fake runtime tests tamper sau download; **native TOCTOU/locking semantics chưa chứng minh trên installer thật**.

Per-user installer invocation không UAC bypass, không suppress Windows trust policy, failure/quarantine/UAC cancel/timeout không success. Kiểm tra installed PE version trước restart; startup immediate failure được bắt, 1s alive check chưa chứng minh full app initialization/health. VM tests/health handshake cần trước production. Installer timeout không kill app/installer hoặc tự rollback chưa được kiểm chứng. App busy/pause/inflight/SQLite transaction/logger flush/stop/unknown/Safe Exit cancel/process mismatch chặn. Results tests simulated/actual_install=false.

UpdatePanel chỉ thêm test-only nối **cùng download/cache/verifier** tới helper algorithm; no activation button/modal/tab/sidebar/layout change. Client vẫn không cần Git/gh/PyInstaller. Missing production key UI chưa hỗ trợ cài thật, không hash-only/unsigned fallback. Stage A service/latest/cache24h/downloader/progress/cancel và original Safe Exit giữ nguyên.

## 9. SQLite, DPAPI và dữ liệu

Không schema/migration/user DB/API key changes. Reuse SQLite Backup API/integrity/WAL tests và outcome_unknown reopen/no replay/900ms Safe Exit tests gốc. Helper không tự backup/restore/migrate data thật; installer chỉ app files. Mock logger/transaction/inflight/unknown/stop/cancel blocking chạy mới. [Scope hash](../artifacts/release-stage-b2-1/scope.json) phải xác nhận translation/storage/providers/validators/export/main lifecycle/skin unchanged.

## 10. Kiểm thử và bằng chứng

[Acceptance](../artifacts/release-stage-b2-1/acceptance.json), [snapshot cuối](../artifacts/release-stage-b2-1/regression-source.json).

- [Focused](../artifacts/release-stage-b2-1/focused-final-2.log): 78 passed; [helper config focused](../artifacts/release-stage-b2-1/config-final.log):73 passed.
- [Full1](../artifacts/release-stage-b2-1/regression-1.log)/[XML1](../artifacts/release-stage-b2-1/regression-1.xml): **674 passed,1 skipped,196.49s**; [Full2](../artifacts/release-stage-b2-1/regression-2.log)/[XML2](../artifacts/release-stage-b2-1/regression-2.xml): **674 passed,1 skipped,179.09s**, cùng snapshot/hook, không Qt crash trong hai lượt này. [Focused complete](../artifacts/release-stage-b2-1/focused-complete.log):74 passed. Không tăng deadline900ms/đổi assertion/skip để đạt.
- [GUI100%](../artifacts/release-stage-b2-1/windows/0.8/report.json), [125%](../artifacts/release-stage-b2-1/windows/1/report.json), [150%](../artifacts/release-stage-b2-1/windows/1.2/report.json): DPR thực1/1.25/1.5, Light/Dark/sizes/maximized, no release/update available/progress/cancel/signature/hash failure/busy/logger/helper blocked/mock success/offline. Windows entry point thật, HTTP guard và LOCALAPPDATA tạm, no installer/helper native execution. Screenshots cạnh report.
- Một lượt full sơ bộ **1 failed,671 passed,1 skipped**, cấu hình helper còn literal empty datas bị test spec cũ bắt; nguồn/config được bổ sung trong lượt này nên không tính vào pair nghiệm thu. Giữ [log](../artifacts/release-stage-b2-1/regression-preliminary.log)/[XML](../artifacts/release-stage-b2-1/regression-preliminary.xml). Bỏ parameter helper data không cần thiết, app vẫn explicit SVG allowlist; không đổi assertion. Pair cuối chạy lại cùng snapshot.
- Chẩn đoán focused đầu: fixture đã published nhưng thiếu timestamp từng được chấp nhận; đã thêm fail-closed validation. GUI driver có local Path import shadow global, sửa driver. Mock junction stat thiếu st_mode đã sửa fixture đầy đủ, giữ assertion và [log lỗi](../artifacts/release-stage-b2-1/focused-final.log). Không che lịch sử lỗi.
- Skip ledger API cũ giữ nguyên, không reset/skip mới để làm xanh. Không dùng số600 củaB1 làm proof B2.1.
- Hai lượt trước khi bổ sung handoff-copy/registry có672 pass1skip,177.10s/176.91s; giữ [lượt1](../artifacts/release-stage-b2-1/regression-pre-handoff-1.log)/[lượt2](../artifacts/release-stage-b2-1/regression-pre-handoff-2.log), không tính làm pair final source.
- Lượt đầu sau handoff-copy có **2 failed,672 passed,1 skipped**,178.77s ở Safe Exit900ms; [log](../artifacts/release-stage-b2-1/regression-safe-exit-failure.log)/[XML](../artifacts/release-stage-b2-1/regression-safe-exit-failure.xml). Source main/translation/logger không đổi. Chạy riêng hai cases, gồm10 lần original test: **2 passed,8.98s**, [log](../artifacts/release-stage-b2-1/safe-exit-isolated.log). Chưa xác định nguyên nhân; không gọi isolated pass là bằng chứng full stability. Final full dùng hook chỉ ghi redacted status/thread frames nếu fail, không thay assert/deadline/Safe Exit.

## 11. Blockers và quyền B2.2

1. Git/Inno6/SDK nếu cần/venv/hash-locked wheel environment; người dùng cho phép cài riêng.
2. Người dùng chọn source Git management/remote private và xử lý clean tracked source; chưa init/add/commit thay.
3. Distribution initial commit/default branch/tag commit policy với quyền riêng; không push private source.
4. Production key owner/storage/passphrase/ACL/backup/rotation/disclosure policy và public pin cần duyệt; không tạo key thật trong B2.1.
5. Authenticode cert/subject/thumbprint/chain/timestamp và test signing native cần duyệt.
6. Review source activation, native process/file/ACL tests, installer/upgrade/uninstall/restart-health/interruptions trên VM, cache/protocol actual approved GitHub Draft. Không chỉ bỏ khóa bằng một flag/env.
7. Build/PyInstaller/ISCC/installer/helper/Git tag/Draft/upload/publish/update real mỗi nhóm cần quyền B2.2 cụ thể. Hiện chưa có quyền đó.

Code/mock đủ chuẩn bị B2.2 có điều kiện; không PRODUCTION READY hoặc quyền chạy thật. Một BAT/một nút là pipeline được chuẩn bị và mô phỏng, không bảo đảm mọi Windows/SmartScreen/UAC/Defender/policy/admin install cũ/file lock, không bypass.

## 12. Báo cáo 25 mục

1. Thêm release_adapters/release_provenance/release_journal/release_pipeline, keytools/authenticode/windows_helper, environment/provision/helper scripts, B2 tests/report. Sửa metadata trust statuses, UpdatePanel test connection, BAT/preflight/spec/ISS/helper metadata/staging; không backend/skin.
2. Git chưa phát hiện, không tự cài.
3. Inno6 chưa phát hiện, winget ID và6.7.3 đã xác minh, không cài.
4. SignTool chưa phát hiện, SDK/cert còn cần chuẩn bị.
5. SOURCE_PROVENANCE_NOT_READY; HEAD/branch/dirty/private remote chưa xác minh, không init/commit.
6. Repo public khai báo main nhưng no branches và commits409empty; initial commit chưa có.
7. Source0.1.0 → PATCH proposal0.1.1, không sửa version thật.
8. Reserve/checkpoints/exclusive journal/remote reconcile chống double bump; new intent sau confirmed publish có PATCH tiếp.
9. Production key chưa có/pin/status maps rỗng, không tạo ngầm.
10. Private-key implementation encrypted/outside Git+EXE, owner ACL/backup warnings; tests temp keys không production.
11. Policy public pipeline cần Authenticode; cert/publisher chưa chọn, không self-signed trust claim.
12. Build/package command+allowlist/staging/version/adapters đã viết, default locked, no actual build.
13. Publisher fixed repo/draft-upload-verify-publish/recovery đã viết, default locked/fake tests.
14. Native helper implementation/entry/spec/ISS đã chuẩn bị, OS execution chưa chạy; cần VM/health/locking proof.
15. Path/reparse/hash/signature+held handle chuẩn bị; tamper mock bị chặn, native TOCTOU chưa kiểm chứng.
16. SQLite/DPAPI tests temporary, code/schema/data thật không đổi; không rollback/migrate thật.
17. Safe Exit900ms/unknown no-replay giữ code/assertions; pair cuối đạt nhưng timing failures trước đó vẫn cần theo dõi, chưa kết luận nguyên nhân.
18. GUI Windows ba DPR Light/Dark/mocks/offline/logger đạt, không redesign.
19. Hai full cuối **674 passed,1 skipped** mỗi lượt,196.49s/179.09s, cùng source/hook; không lấy lượt sơ bộ/B1 làm bằng chứng.
20. Không Kira/Gemini thật.
21. Không PyInstaller/EXE build.
22. Không ISCC/installer/helper production execution.
23. Không init/add/commit/tag/push/Draft/upload/publish; chỉ GitHub/winget read-only.
24. Blockers: toolchain/source/distribution commit/trust anchor/cert/ACL+VM evidence/hash lock/activation quyền B2.2.
25. **B2.1 CODE READY — ENVIRONMENT/SECURITY BLOCKERS REMAIN**: final mock/source/config/GUI/pair tests đã kiểm chứng; cần giải quyết blockers, native handoff/ACL/installer/health proof và quyền riêng trước B2.2 thực hiện build/install/release. Không PRODUCTION READY hoặc tự động cho phép chạy thật.
