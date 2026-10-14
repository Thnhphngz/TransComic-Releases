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

Kết quả đang được hoàn tất trong `artifacts/automatic-release-system-v2/`: isolated Git + fake GitHub cho default/check/build-only/no-change/rollover/failure/secrets/UNKNOWN/receipt/idempotency/data preservation; BAT thật ở path có dấu cách và hai BAT đồng thời. Real `--check` chỉ GET GitHub, không thay version/journal/source. Kiểm tra build-only từ checkout cô lập sẽ chạy trước kết luận cuối.

## Cách dùng

1. Sửa và lưu app.
2. Chạy `release_transcomic.bat`.
3. Chờ **RELEASE PUBLISHED AND VERIFIED**.
4. Người dùng mở TransComic → Kiểm tra cập nhật.

Không thay đổi cần phát hành: **NO RELEASEABLE CHANGES**, exit0. Fail/blocked: xem logs theo version/attempt, giữ journal/packages và chạy `--check`; không xóa reservation để vượt gate. Chi tiết: [release-workflow.md](release-workflow.md).

## Giới hạn

Windows x64 developer toolchain/gh account đúng/repo public với push permission/Git author và baseline Latest còn nguyên là điều kiện bắt buộc; không cài tool ngầm. Chưa có publisher signature cho Internal. Unknown không thể chứng minh thì dừng để đối chiếu; không tự suy ra thất bại để gửi lại. Native installer/update mới chưa thể coi là PASS chỉ từ protocol test. SRT giữ sidebar và “Chức năng đang được cập nhật”. Không portable updater/redesign/API live mặc định.

Không xóa bản chính thức cũ, two-laptop artifacts, TestArchive, SecureBackup hoặc dữ liệu người dùng. Không có cleanup step mặc định.

AUTOMATIC RELEASE SYSTEM PARTIAL — BLOCKERS REMAIN

Kết luận tạm thời trước khi hoàn tất regression và build-only cô lập; sẽ cập nhật bằng kết quả thực tế.
