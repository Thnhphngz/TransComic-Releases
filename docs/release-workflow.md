# Phát hành TransComic — Automatic Release V2

## Muốn phát hành bản cập nhật mới

1. Sửa TransComic.
2. Lưu source.
3. Chạy `release_transcomic.bat` (double-click hoặc từ terminal, kể cả thư mục có dấu cách).
4. Chờ dòng **RELEASE PUBLISHED AND VERIFIED**.
5. Người dùng mở TransComic → Kiểm tra cập nhật.

Chạy BAT mặc định là quyền bắt đầu phát hành thật vào `Thnhphngz/TransComic-Releases`, kênh Internal. Không có lịch chạy nền. BAT in repository, version hiện tại/dự kiến, source commit và remote operations trước khi thay đổi.

## Các chế độ

| Lệnh | Hành vi |
|---|---|
| `release_transcomic.bat` | Commit các file đã phân loại, test/build/package, publish và verify |
| `release_transcomic.bat --check` | Chỉ đọc source, journal, môi trường và GitHub; không commit/bump/reserve/build/publish |
| `release_transcomic.bat --build-only` | Cùng test/build/package/verify; giữ version reservation để lần sau publish đúng bản, không GitHub writes |
| `release_transcomic.bat --recover-published` | Đối chiếu release đã public và hoàn tất hậu kiểm bằng GET; không build/bump/tag/upload/publish lại |
| `release_transcomic.bat --help` | Hướng dẫn, không gọi GitHub |

Không nhận version/repository override hay flags viết tắt. Máy dev cần Python/dependency đã cài, Git có author identity, GitHub CLI đăng nhập đúng tài khoản có quyền repo và Inno Setup. Không tự cài tool hay yêu cầu chạy từng tool riêng lẻ.

## Version và commit

Đối chiếu journal đã publish với GitHub và hash tải về trước khi chọn version. Giữ policy 0–9: 1.0.9 → 1.1.0, 1.9.9 → 2.0.0. Fingerprint code/scripts/tests/config/resources chuẩn hóa line endings, bỏ qua giá trị VERSION sinh tự động. README/docs đơn thuần không tạo release. Không có thay đổi cần phát hành: **NO RELEASEABLE CHANGES**, exit0, không commit/version/release mới.

Source/tests/scripts/docs và cấu hình allowlist được scan secrets/UTF-8/binary/reparse rồi stage bằng danh sách tên cụ thể; không `git add .`. File lạ, conflict, detached HEAD, Git operation dở dang hay secrets khiến pipeline dừng. File ignored cá nhân có sẵn không được commit/package. Không push source hoặc đổi origin.

## Test và package

Full pytest dùng isolated runtime ngoài project và HTTP MockTransport; không tự gọi Kira/Gemini thật. Build app/helper bằng PyInstaller và Installer bằng ISCC, version từ source đã commit sạch. Giữ AppId, mutex, data path và per-user default install directory.

Kiểm tra PE/hash/size, allowlist archive, manifest/checksums, frozen GUI Light/Dark ở DPR100/125/150% (scale tính từ DPR Windows thực), SafeExit900ms. SRT chỉ placeholder. Baseline là EXE thật của Latest đã xác minh hash. Thực thi module updater từ PYZ với candidate bytes mới: check/download/confirm/prepare/helper.validate; không chạy Installer/native handoff trên máy dev.

`releases/<version>/` có app, helper, Installer, manifest, checksums, release notes và build-manifest. Chỉ upload Installer canonical, manifest, SHA256SUMS. HTTPS/SHA256 kiểm tra consistency, không phải chữ ký publisher. EXE chạy trực tiếp không có portable updater.

## Journal, timeout và chạy lại

Một process giữ kernel lock. Journal không reset; bản published trước được giữ ở `.release-state/history/`. Version được reserve trước commit/build; lỗi không bump lần hai. Build-only giữ reservation. Lỗi test/build cục bộ có thể sửa rồi chạy BAT lại: cùng version, commit mới, giữ attempt cũ; candidate chưa từng ghi remote được lưu lại nếu cần thay.

Trước mỗi GitHub write lưu intent bền vững. Timeout/UNKNOWN phải đọc remote theo build-id/notes/tag/asset name/size/hash. Chỉ tiếp tục khi xác minh thao tác đã hoàn thành; asset/tag/release vắng mặt sau UNKNOWN không phải lý do tự gửi lại. Chưa xác định được: **REMOTE_INTENT_UNRESOLVED_OUTCOME_UNKNOWN**. Không xóa journal/intent/tag, không clobber/force push. Kiểm tra log và GitHub trước khi xử lý thủ công; giữ nguyên source/package của lượt remote còn dở.

Sau authenticated publish phải verify anonymous Latest/tag/metadata/checksums và baseline tải Installer thật. Lỗi bước này: không in success, không bắt đầu version kế tiếp. Chạy lại cùng version và đối chiếu remote. Không ghi đè release đã publish.

Hậu kiểm dùng staging tạm riêng ngoài source/program directory. Không đặt thư mục Updates trong `artifacts/` và không nới guard của updater. Nếu GitHub đã publish nhưng hậu kiểm lỗi, BAT trả exit2 và báo **PUBLISHED — POST-VERIFICATION INCOMPLETE**, journal giữ `state=PUBLISHED`, `post_publication_verified=false`; không được hiểu là release chưa tồn tại.

`--recover-published` xác minh source commit/gates/build snapshot cũ, hash/version payload, GUI/SafeExit/baseline và bytes trên GitHub trước khi đánh dấu verified. Có thể sửa verifier trước recovery; bằng chứng cũ vẫn gắn với commit cũ. Evidence recovery nằm ở `artifacts/automatic-release/<version>/postverify-*/`, không ghi đè logs lượt build/publish. BAT mặc định gặp release pending đã public cũng chọn recovery và dừng sau khi hoàn tất, không tự bắt đầu version tiếp trong cùng lượt.

Đợt được cấp quyền riêng cho một version có thể dùng `--expected-version 1.0.2`: BAT dừng trước mọi mutation nếu version tính ra khác; đây là giới hạn an toàn, không ép chọn hoặc bỏ qua quy tắc tăng version.

## Khi dừng hoặc cần xem log

Chạy `release_transcomic.bat --check` để xem blocker. Logs/XML/GUI/provenance/command-events: `artifacts/automatic-release/<version>/attempt-*/`; journal: `.release-state/journal.json`; network intent: `artifacts/automatic-release/<version>/remote-intent.json`. Không chia sẻ API keys hay user database. Không xóa reservation để vượt gate.

Thiếu baseline package Latest → dừng; giữ `releases/<Latest>/`. Kiểm thử giao thức không xác minh native upgrade mới hoặc mọi biến thể DOCX.

## Nghiệm thu native

USER CONFIRMED: laptop 2 cài0.1.0, nâng0.1.0→0.1.1→1.0.0, history giữ sau cả hai lần. Đây không phải automated E2E. Với mỗi bản mới: cập nhật trong installed app, kiểm tra version/history/settings/tài liệu; không gỡ cũ/chạy Installer tay thay updater test.

Người dùng tiếp tục xác nhận native1.0.0→1.0.1 thành công và lịch sử/bản dịch còn nguyên. Đây cũng là nghiệm thu do người dùng báo, không phải automated E2E; native1.0.1→1.0.2 còn chờ kiểm tra riêng.

Không tự xóa releases cũ, two-laptop artifacts, TestArchive, SecureBackup hoặc dữ liệu người dùng. Công cụ không có cleanup step mặc định.
