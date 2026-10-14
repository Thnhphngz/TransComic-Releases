# TransComic — Sửa Auto Release V2 và phát hành v1.0.2

## A. Nguyên nhân v1.0.1

Đã tái hiện trước sửa bằng code thật và anonymous GitHub GET. `scripts/automatic_release.py`, `Runtime.verify_public()` tạo `UpdateService(directory=work/'anonymous')` **sau authenticated publish**. Đường dẫn thật bị từ chối:

`D:\Sourch Code\TransComic\artifacts\automatic-release\1.0.1\attempt-5e321460\anonymous`

Call stack: `Runtime.verify_public` (dòng249 trước sửa) → `UpdateService.__init__`, `transcomic/update/service.py:45`. Directory nằm trong source root nên guard từ chối đúng. Stack và đường dẫn ghi ở `artifacts/release-fix-1.0.2/root-cause.json/log`.

GitHub đã publish v1.0.1 (ID413231710) và kiểm tra authenticated assets thành công trước khi lỗi xảy ra. BAT báo lỗi do hậu kiểm chưa xong; không có bằng chứng upload thất bại. Journal ban đầu `state=PUBLISHED`, `post_publication_verified=false`, giữ failure_code. Lỗi không thuộc baseline-offline/build hay API dịch.

## B. Những thay đổi

- `scripts/automatic_release.py`: `verification_staging()` cấp owned temporary directory ngoài source, updater module root và Python/app image directory. Anonymous verifier dùng staging này. Giữ nguyên guard trong `transcomic/update/service.py`, HTTPS, repo pinning, schema/size/hash và helper validation.
- Recovery chính thức `--recover-published`: chỉ GitHub GET, kiểm tra commit/gates/test XML/build snapshot/PE/AppId/archive/GUI/SafeExit/baseline cũ, tải lại bytes remote, rồi chạy anonymous Latest/tag/metadata/checksum và baseline download. Dùng journal API reconcile; không sửa JSON thủ công, reset/bump/build/tag/upload/publish lại. Giữ source commit/build-id/inventory cũ và lưu evidence/history riêng. Có thể sửa verifier trước recovery mà không gán commit mới cho payload cũ.
- Trạng thái rõ: **PUBLISHED — POST-VERIFICATION INCOMPLETE**, exit2 khi đã public nhưng hậu kiểm lỗi; **PUBLISHED AND VERIFIED**, exit0 chỉ sau toàn bộ hậu kiểm. Resume thấy remote đã public sẽ recovery rồi dừng cùng version; không tự phát hành bản tiếp theo.
- `--expected-version` là safety bound, dừng trước mutation nếu plan khác quyền được cấp; không override version hoặc gates. Lượt thật dùng đúng1.0.2.
- `scripts/release_package.py`: notes mô tả staging/recovery. `tests/test_release_post_verification.py` và fake fixtures kiểm tra real-path staging trong source, source/program vẫn bị từ chối, lỗi sau publish và exitcode, recovery khi verifier đổi, journal interrupted/remote published, hash mismatch, không duplicate, expected-version. `docs/release-workflow.md` cập nhật cách vận hành.

## C. Kết quả kiểm thử và recovery

- Focused staging/recovery/pipeline: **47 passed** (`recovery-tests.xml`).
- Full regression offline trên source release commit `3ad268f1115fcc57c50361eb4812bda9ab48a5c7`: **946 PASS / 0 FAIL / 0 SKIP**, 277.67s. Không gọi Kira/Gemini thật; test DOCX dùng fixture tổng hợp và HTTP mock. Không hạ assert/deadline.
- Real BAT build-only v1.0.2: **exit0**, PyInstaller app/helper và Inno Installer PASS; canonical inventory7files, PE1.0.2.0, x64 payload, same AppId/install/data paths; SHA/manifest/archive privacy PASS.
- Frozen Windows GUI Light/Dark DPR100/125/150% PASS, TXT/DOCX, search/undo, queue/workspace, popup, SRT placeholder; SafeExit900ms và exit0 PASS. Helper self-check0 và untrusted plan2 PASS. Không chạy Installer/native handoff trên máy dev.
- Baseline offline lấy updater từ PYZ của EXE1.0.1 thực tế: nhận candidate1.0.2, kiểm tra mapping/manifest/hash/size/repo, download/confirm/prepare/helper.validate PASS. Sau publish baseline cũng tải Installer thật ẩn danh và PASS. Không coi protocol test là native install.
- Recovery1.0.1 qua BAT **exit0**, journal thành `PUBLISHED AND VERIFIED`, source commit cũ `cfc99dd3e3956b0c701f7b3d9cf78fadec588d0e` giữ nguyên. Anonymous staging thực tế `D:\TransComic-TestRuntime\gui\TransComic-release-verify-o2h7rlwp` nằm ngoài source/program. Recovery evidence: `artifacts\automatic-release\1.0.1\postverify-1b2c613c`. Không upload/publish lại1.0.1; old package và logs/hash ban đầu không đổi.
- USER CONFIRMED: laptop2 native1.0.0→1.0.1 thành công, history/bản dịch còn nguyên. Đây là xác nhận người dùng, không giả automated E2E.

## D. Kết quả phát hành thật v1.0.2

**RELEASE PUBLISHED AND VERIFIED**

- URL: https://github.com/Thnhphngz/TransComic-Releases/releases/tag/v1.0.2
- Release ID: **413247199**; tag **v1.0.2**; public/non-draft/non-prerelease; published_at `2026-10-14T22:43:49Z`.
- GitHub Latest authenticated và anonymous cùng ID/tag1.0.2. Tag commit đối chiếu publisher; fixed repo `Thnhphngz/TransComic-Releases`. Chỉ Installer/manifest/checksums được upload, không source/build logs/database/keys/history.
- BAT `--expected-version 1.0.2`: **exit0**. Journal `state=PUBLISHED`, `workflow_status=PUBLISHED AND VERIFIED`, `post_publication_verified=true`, `failure_code=null`.
- Sau phát hành, chạy BAT ở mode auto và giới hạn1.0.2: **NO RELEASEABLE CHANGES**, exit0; journal/version không đổi. Không tạo1.0.3. Kiểm tra default không tham số được ghi riêng nếu đã chạy; xem acceptance.json.
- Build từ source commit `3ad268f1115fcc57c50361eb4812bda9ab48a5c7`; report commit cuối chỉ cập nhật tài liệu. Runtime source1.0.2, PE1.0.2.0; Inno AppId `{CB58C770-47B7-42DC-A2CA-409DDF456487}`, app `TransComic.Desktop`, per-user `%LOCALAPPDATA%\Programs\TransComic`, data `%LOCALAPPDATA%\TransComic` giữ nguyên.

| Asset | ID | Bytes | SHA-256 |
|---|---:|---:|---|
| SHA256SUMS.txt | 641908032 | 194 | `e684123524dba3783173e1096ccd6beefb4b4162c175de0c7cc61dd560c0527a` |
| TransComic-Setup-1.0.2-windows-x64.exe | 641907641 | 112895909 | `d38ef5467b15a8cdd8d39bc973b9f1313a5cb23ef71e5093e3bb122164bfc8d0` |
| transcomic-update.json | 641907999 | 546 | `6db02564d61607e0b8f7504bcaa2d87d2641651f99baf70d713bbe70d92623e9` |

Remote authenticated download và anonymous baseline Installer download đã đối chiếu bytes/size/hash local. `SHA256SUMS.txt` có hai entry canonical Installer+manifest. Internal HTTPS/SHA256 là consistency, không thay chữ ký publisher; không tuyên bố Authenticode/Ed25519.

Gói local: `releases/1.0.2/`. Evidence build/publish: `artifacts\automatic-release\1.0.2\attempt-7449ba85`; report/acceptance và snapshots: `artifacts/release-fix-1.0.2/`. v0.1.1/v1.0.0/v1.0.1 giữ nguyên ID/body/published_at/assets; không push source, đổi origin, xóa build/backup/data, đọc key Kira/Gemini hay sửa history, không tắt Defender/SmartScreen, không install/uninstall/reboot máy dev.

Các log chẩn đoán/test fail trước fix và audit path separator Windows được giữ riêng, không tính PASS. Không còn blocker cho release1.0.2; native upgrade mới trên laptop2 vẫn chờ người dùng.

## E. Người dùng kiểm tra trên laptop 2

1. Mở bản **installed1.0.1** hiện có, ghi nhận số mục lịch sử và mở một vài bản dịch cũ; không reset database.
2. Chọn **Kiểm tra cập nhật** → phải thấy1.0.2 → tải và xác nhận cài, đợi SafeExit. Không gỡ bản cũ/chạy Installer tay thay updater.
3. Khi mở lại, xác minh version1.0.2; so toàn bộ danh sách lịch sử và mở lại các bản dịch đã kiểm tra; kiểm tra settings/API configuration còn nguyên mà không chia sẻ key.
4. Mở TXT/DOCX thử, sửa/lưu/khởi động lại; SRT vẫn **Chức năng đang được cập nhật**. Báo lỗi/ảnh nếu có, không xóa dữ liệu để thử lại.

**LAPTOP 2 UPDATE 1.0.1 → 1.0.2 PENDING USER TEST**
