# TransComic — Automatic Release System V2

## Hành vi đã triển khai

BAT không tham số chọn AUTO RELEASE. Các mode `--check`, `--build-only`, `--help` dùng entry chung, argparse không cho viết tắt hay override repo/version. Không tạo lịch chạy nền. Trong lượt triển khai này không được publish GitHub; các bài có remote writes dùng GitHub giả lập.

Fingerprint code/scripts/tests/config/resources chuẩn hóa line endings và giá trị VERSION được sinh; docs/README riêng không tạo release. So với source commit/fingerprint của release đã xác minh. Version theo carry0–9, reserve trước khi sửa VERSION/commit; không bump lại khi recovery. Source/tests/docs allowlist được scan và stage tên cụ thể; file lạ/secrets/binary không đúng loại/reparse/conflict khiến dừng. Không push source/đổi origin.

Journal cũ được giữ, xác minh với v0.1.1/v1.0.0; lịch sử mỗi phiên bản được lưu trước transition. Kernel lock chặn hai process. Unknown write có durable intent trước subprocess, receipt sau response được kiểm tra hoặc read-only reconcile. Receipt chặn gửi lại thao tác đã hoàn thành khi remote bất thường. Không xóa/clobber/recreate release, không retry mù khi asset/release chưa thấy sau timeout.

Build-only và auto cùng test/build/package/compatibility implementation, cùng PyInstaller/ISCC builder. Dynamic scope dùng lại FirstReleaseCommands/Publisher, ReleaseCoordinator/Journal hiện có; generic signed-stable adapter không bị mở khóa. Tag/draft/upload/publish bị khóa vào đúng repo/version/build-id/notes/assets. Sau publish còn phải anonymous verify Latest, metadata, checksum và baseline tải Installer; chưa xong không báo success hoặc phát hành version tiếp.

Full pytest offline mặc định, không gọi API dịch thật; runtime/cache nằm ngoài workspace. Archive scan, PE/hash/version, AppId/install/data path, helper self-check/reject untrusted plan, frozen GUI Light/Dark100/125/150 và SafeExit900ms là gate. Candidate được kiểm tra bằng updater lấy từ PYZ của EXE Latest thực tế trước publish. Không chạy Installer hoặc native handoff trên máy dev.

## Nghiệm thu lịch sử do người dùng xác nhận

- Laptop2 cài0.1.0 thành công.
- NATIVE UPDATE 0.1.0 → 0.1.1 — USER CONFIRMED SUCCESS.
- NATIVE UPDATE 0.1.1 → 1.0.0 — USER CONFIRMED SUCCESS.
- Lịch sử được giữ sau cả hai lần nâng cấp.

Đây là xác nhận của người dùng, không phải log hệ thống/automated E2E. Mỗi phiên bản mới vẫn có compatibility gate và native acceptance riêng.

## Kiểm thử triển khai

Kết quả thực tế lưu tại `artifacts/automatic-release-system-v2/`:

- Full regression offline trên commit `7dabad22faf48faf50cb0eb54d7752e54742c017`: **937 passed, 0 skipped**, 266.49s. Không hạ assert/deadline. HTTP MockTransport được bắt buộc trong chế độ release; DOCX cá nhân được thay fixture tổng hợp với cùng assertion 125 units/context/export.
- BAT thật với GitHub giả lập: `--check` không đổi source/version/journal, `--build-only` không publish, mặc định đi qua release + verify; hai BAT đồng thời chỉ một được chạy.
- Scope publisher/coordinator thật qua fake gh REST: server nhận asset nhưng client timeout; recovery đọc asset đã có, không upload trùng, chỉ publish một lần. Receipt chặn gửi lại mutation đã xác nhận. Sai Latest, manifest sửa, asset khác repo, size sai đều bị từ chối trước baseline.
- No-change không commit/bump/release; rollover1.0.9→1.1.0 và1.9.9→2.0.0; build/test/baseline/hash/manifest/secrets/file lạ/foreign tag/unknown failure chặn publish. Sửa lỗi cục bộ dùng lại version và giữ candidate lỗi.
- Real BAT `--check` đối chiếu GitHub bằng GET, source1.0.0/journal PUBLISHED không đổi. GitHub vẫn chỉ có v0.1.1 và v1.0.0; không phát hành thử thật trong lượt này.
- Real BAT `--build-only` từ checkout cô lập `D:\TransComic-TestRuntime\release-v2-469a7958`: **exit0**, tự reserve/commit candidate1.0.1, **929 tests passed, 0 skipped**, PyInstaller tạo app/helper và ISCC tạo Installer canonical, PE1.0.1.0, manifest/checksum/package/archive privacy PASS. Helper exit0/2, GUI Light/Dark DPR1.0/1.25/1.5 và SafeExit900ms PASS; updater lấy từ EXE1.0.0 thực tế xác minh Installer candidate và helper plan PASS; không chạy Installer/native handoff. Candidate là LOCAL TEST ONLY — NOT PUBLISHED.
- Build-only dùng implementation commit `fa75b3dd4ac77bc6dc5f98080143e6e4b9510f89`, candidate source commit `139ff612e5828fc065558a0922e5f22152725ae4`. Các bổ sung cuối thuộc kiểm tra publisher/Latest, output/recovery và tests, được full regression commit cuối xác minh; không gán provenance build cũ sang commit mới.
- Artifact privacy text scan không có findings; build archive có allowlist riêng. Hash `releases/1.0.0/`, baseline và production journal không đổi. Không gọi API dịch thật, push source hoặc xóa build/data.

Gates lỗi/chẩn đoán và full run bị dừng khi bổ sung kiểm tra Latest được giữ riêng; không tính là PASS. Chi tiết raw evidence: `full-final.xml/log`, `scoped-publisher-final.xml`, `publisher-recovery.xml`, `anonymous-regression.xml`, `check-final.log`, `isolated-build-summary.json`, `isolated-evidence/`, `protected-and-remote-final.json`, `privacy-final.json`.

## Cách dùng

1. Sửa và lưu app.
2. Chạy `release_transcomic.bat`.
3. Chờ **RELEASE PUBLISHED AND VERIFIED**.
4. Người dùng mở TransComic → Kiểm tra cập nhật.

Không thay đổi cần phát hành: **NO RELEASEABLE CHANGES**, exit0. Fail/blocked: xem logs theo version/attempt, giữ journal/packages và chạy `--check`; không xóa reservation để vượt gate. Chi tiết: [release-workflow.md](release-workflow.md).

## Giới hạn

Windows x64 developer toolchain/gh account đúng/repo public với push permission/Git author và baseline Latest còn nguyên là điều kiện bắt buộc; không cài tool ngầm. Chưa có publisher signature cho Internal. Unknown không thể chứng minh thì dừng để đối chiếu; không tự suy ra thất bại để gửi lại. Native installer/update mới chưa thể coi là PASS chỉ từ protocol test. SRT giữ sidebar và “Chức năng đang được cập nhật”. Không portable updater/redesign/API live mặc định.

Không xóa bản chính thức cũ, two-laptop artifacts, TestArchive, SecureBackup hoặc dữ liệu người dùng. Không có cleanup step mặc định.

AUTOMATIC RELEASE SYSTEM READY

Đây là nghiệm thu triển khai bằng mock/integration và build-only thực tế; không tuyên bố đã phát hành GitHub thật bằng V2 trong lượt này.
