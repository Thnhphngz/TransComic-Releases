# TransComic — Sửa hậu kiểm Automatic Release V2 và v1.0.2

## A. Nguyên nhân v1.0.1

Đã tái hiện bằng verifier hiện hành trước sửa, không chỉ suy đoán thông báo lỗi. `scripts/automatic_release.py`, hàm `Runtime.verify_public()`, khởi tạo `UpdateService(directory=work/'anonymous')` sau authenticated publish. Đường dẫn thực bị từ chối:

`D:\Sourch Code\TransComic\artifacts\automatic-release\1.0.1\attempt-5e321460\anonymous`

Call stack: `Runtime.verify_public` → `UpdateService.__init__`, `transcomic/update/service.py:45`. Guard phát hiện directory nằm dưới source root `D:\Sourch Code\TransComic` và phát sinh `Updates must be outside source/program directory` trước bước tải metadata ẩn danh. Pipeline đã publish và authenticated asset verification PASS; lỗi ở hậu kiểm làm `post_publication_verified=false`, BAT exit2 với lời báo cũ dễ gây hiểu nhầm.

GitHub v1.0.1 đã public, non-draft/non-prerelease, Latest, ID413231710. Kiểm tra lại bằng authenticated GET và tải ba assets cho hash/size khớp journal. Installer112891164 bytes, SHA256 `fa114389f6fe518817a600804cbacb5c18ab7302c033b5adc44ba11adb1814a3`. Không xóa/publish lại release này.

## B. Sửa đổi

- `scripts/automatic_release.py`: owned temporary staging ngoài source/program cho anonymous verifier; giữ nguyên guard updater. Recovery chính thức `--recover-published` dùng GET, đối chiếu source/gates/build snapshot lịch sử và remote trước hoàn tất; không yêu cầu payload cũ được build bằng mã verifier mới.
- Journal/API reconcile được dùng để hoàn tất, không sửa JSON thủ công. Giữ source commit/build-id/inventory cũ, lưu evidence/history recovery riêng; không reset journal. Tách `PUBLISHED — POST-VERIFICATION INCOMPLETE` (exit2) và `PUBLISHED AND VERIFIED` (exit0). Default pending public release cũng recovery rồi dừng, không bump lượt kế tiếp.
- `--expected-version`: giới hạn version của một đợt được cấp quyền, dừng trước mutation nếu plan khác; không override version/gates.
- `scripts/release_package.py`: notes mô tả sửa hậu kiểm/recovery. `tests/test_release_post_verification.py` và fixtures hiện hành kiểm tra staging thật, từ chối source/program, published failure, exitcode, recovery sau sửa verifier, interrupted journal, idempotency/no duplicate và version bound. Giữ GUI/SRT/data paths/updater protocol.

## C. Kiểm thử và recovery v1.0.1

Đang hoàn tất; bằng chứng ghi ở `artifacts/release-fix-1.0.2/`. Không gọi API dịch Kira/Gemini thật. Không chạy Installer hoặc native handoff trên máy dev.

Người dùng xác nhận laptop2 native1.0.0→1.0.1 thành công, giữ lịch sử/bản dịch; ghi là USER CONFIRMED, không giả automated E2E.

## D. Phát hành v1.0.2

Chưa phát hành trong lúc điều tra. Chỉ được phát hành đúng v1.0.2 bằng BAT sau regression/build/GUI/SafeExit/baseline PASS và recovery v1.0.1 có đủ bằng chứng. Kết quả cuối, ID/assets/hash/journal/BAT exitcode/no-change sẽ được cập nhật sau kiểm tra thực tế.

## E. Laptop 2

Sau khi bản1.0.2 đã publish và verify: mở bản installed1.0.1 hiện có → kiểm tra cập nhật → tải → xác nhận cài sau SafeExit. Không gỡ bản cũ hoặc dùng Installer thủ công thay bài thử updater. Kiểm tra version1.0.2, so danh sách lịch sử và một số bản dịch cũ, mở lại tài liệu/settings; không reset DB. Native1.0.1→1.0.2 PENDING USER TEST.
