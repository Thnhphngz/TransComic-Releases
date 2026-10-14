# Production Ed25519 và cleanup an toàn

## Trạng thái

**PROVISIONING BLOCKED — USER ACTION REQUIRED**: phiên công cụ Codex không có kênh để người dùng nhập trực tiếp xác nhận và mật khẩu bí mật. Theo mục 5.2 của yêu cầu, dừng trước tạo khóa và cung cấp lệnh chạy trong terminal VS Code. Không tạo mật khẩu mặc định, không xin mật khẩu qua chat, không pin khóa giả.

Cleanup đã hoàn tất trong phạm vi cache được xác minh. Signing/release, build, installer và GitHub writes vẫn khóa. Không dùng trạng thái `PRODUCTION KEY + CLEANUP READY` vì khóa production/backup/drill thật chưa có.

## Công cụ và kiểm chứng

- `WindowsKeyACL(native=True)` chỉ mở thao tác ACL cục bộ phục vụ provisioning và test. Mặc định vẫn khóa; không mở ProductionCommands, signing pipeline hay installer.
- Đã chạy Win32 DACL thật: protected DACL, owner SID so với token hiện tại, ACE/mask owner-only, nhận biết quyền thừa kế, phát hiện thêm Everyone read, deny read làm đọc file thất bại, deny write làm tạo thư mục con thất bại, existing directory và junction/reparse bị từ chối.
- Đã provision **khóa test** trong thư mục tạm ngoài source, PKCS8 mã hóa, sign/verify, backup AES-GCM/Scrypt, restore có ACL native và giữ key ID. Không dùng fixture làm production.
- ACL không ngăn administrator có đặc quyền hoặc mã chạy dưới cùng tài khoản chiếm quyền. Không tuyên bố bảo vệ tuyệt đối.
- Ceremonial CLI kiểm tra native test drill, path/reparse/Git/cloud, dung lượng D, storage parent và backup parent ACL, existing key/backup/drill, xác nhận terminal, mật khẩu bí mật và sự khác nhau giữa recovery/storage trước khi sinh khóa. Ghi độc quyền, fsync, kiểm tra pair; lỗi giữ mọi kết quả dở dang, không tự sinh lại/xóa/overwrite.

## Lệnh người dùng chạy trực tiếp

Mở terminal PowerShell tích hợp VS Code tại workspace, **không chạy qua pipe hoặc redirect**:

```powershell
python scripts/provision_release_key.py --interactive
```

CLI hiển thị các đường dẫn rồi yêu cầu gõ `CREATE PRODUCTION KEY`. Sau đó nhập và xác nhận ba mật khẩu bằng prompt bí mật: storage, recovery khác storage, và storage của recovery drill. Mỗi mật khẩu tối thiểu 16 byte UTF-8; nên tạo mật khẩu mạnh trong password manager. Không gửi mật khẩu cho Codex, không đặt trong argv/environment/file.

Đường dẫn cố định theo policy, không có tên tài khoản hardcode:

- `%LOCALAPPDATA%\TransComicSigning\production`
- `D:\TransComic-SecureBackup\release-key.tc-keybackup`
- `%LOCALAPPDATA%\TransComicSigning\recovery-drill`

CLI tạo khóa, xác minh dữ liệu lưu, tạo backup mã hóa, restore với mật khẩu storage mới, đối chiếu purpose/key ID/public key và sign/verify fixture. Chỉ xuất public key/ID và public receipt. Không sửa updater pin. Nếu có directory/file tồn tại hoặc kết quả chưa rõ, dừng để điều tra; không chạy lại với khóa mới để thay thế.

Sau thành công: **Bạn cần tự sao chép `release-key.tc-keybackup` sang USB**, kiểm chứng bản sao/khả năng phục hồi và lưu recovery password riêng. Ổ D cùng máy không phải backup độc lập. Trạng thái vẫn là `OFFLINE_BACKUP_PENDING` cho tới khi bước USB được xác nhận. Public pin chỉ được sửa sau khi người dùng duyệt public key/ID thật đã xác minh.

## Inventory và cleanup

[Inventory](../artifacts/cleanup-review/inventory.json) ghi file paths, bytes, tracked/ignored/untracked, reparse, nhóm dữ liệu, references, hash candidate và process gate. [Danh sách cần rà soát](../artifacts/cleanup-review/pending-review.json) giữ các `.pytest_*` có DB, DOCX/TXT, ảnh hoặc bằng chứng không thể tự kết luận là bỏ được; giữ `artifacts`, `build`, `dist`, `docs`, `installer`, `ddd` và dữ liệu gốc. Không delete/move nhóm chưa rõ.

Đã dọn đúng:

1. `.pytest_cache`
2. `scripts/__pycache__`
3. `tests/__pycache__`
4. `transcomic/__pycache__`
5. `transcomic/ui/__pycache__`
6. `transcomic/update/__pycache__`

Tổng 3.142.400 byte. Bản sao hash-verified và receipt được giữ ngoài workspace tại thư mục riêng dưới `%LOCALAPPDATA%\TransComicMaintenance`; xem [cleanup-result.json](../artifacts/cleanup-review/cleanup-result.json) để biết đúng đường dẫn đã tạo. Không xóa quarantine này trong lượt làm việc.

Không dùng wildcard deletion hay `git clean`. Trước mỗi candidate: kiểm tra root containment, reparse ancestors, Git tracked, references, hash, process và release journal; sao lưu/đối chiếu byte rồi mới unlink/rmdir từng node đã xác minh. Receipt ghi trạng thái trước và sau dọn. File mới/đổi hash/không rõ/in-use/error phải dừng, không force. Các unit test kiểm tra traversal, tracked source, reparse, DOCX/SQLite/artifact, pytest đang chạy, journal dở dang, changed data và chạy lại lần hai. Native CLI dưới một pytest process thật cũng bị chặn.

Maintenance độc lập mặc định dry-run:

```powershell
python scripts/cleanup_project.py
python scripts/cleanup_project.py --apply
```

BAT tích hợp theo thứ tự preflight rồi maintenance, không kích hoạt release:

```powershell
.\release_transcomic.bat --maintenance dry-run
.\release_transcomic.bat --maintenance cache
```

Không chạy cleanup trong pytest, app/live/API/build/helper đang chạy; không dọn khi journal không xác minh được hoặc chưa PUBLISHED. Các cache sẽ được test/import tạo lại bình thường; đây không phải lỗi cleanup và không phải lý do xóa dữ liệu khác. Không xóa build/dist/installer/log đang dùng hoặc artifact nghiệm thu.

## Báo cáo 25 mục

| # | Nội dung | Kết quả |
|---|---|---|
| 1 | ACL Windows native | Đạt; DACL/owner/inheritance/tamper/deny/reparse được kiểm tra thực |
| 2 | Production key | Chưa tạo; cần tương tác terminal trực tiếp |
| 3 | Key ID | Chưa có production ID; không thay bằng test ID |
| 4 | Public pair | Test pair/native recovery đạt; production pair chưa có |
| 5 | Private storage | Thư mục dự kiến `%LOCALAPPDATA%\TransComicSigning\production`; chưa tồn tại |
| 6 | Backup D | Thư mục đã tạo với ACL owner-only; file backup chưa có; D còn khoảng 38 GB lúc kiểm tra |
| 7 | Restore drill | Test key/native ACL đạt; production drill chưa thực hiện |
| 8 | USB | Chưa có backup để sao chép; sau ceremony vẫn OFFLINE_BACKUP_PENDING tới khi xác nhận USB |
| 9 | Production pin | Chưa duyệt/chưa thêm; production maps vẫn rỗng |
| 10 | Secret trong Git/installer | Không tạo/ghi secret vào source; không build/upload; mật khẩu test chỉ trong bộ nhớ |
| 11 | Inventory ban đầu | 109 root items, 33.560 file, 23.240 directory ngoài `.git`; apply inventory ghi 33.570 file sau baseline/evidence mới |
| 12 | Cache an toàn | Sáu candidate nêu trên; data/evidence không rõ bị giữ |
| 13 | Đã dọn | Sáu candidate, 3.142.400 byte, bản giữ hash-verified ngoài workspace |
| 14 | Không được xóa | 97 pending entries; source/config/docs/tests/fixtures, user data, ledger, journal, secrets, artifact và `ddd` được giữ |
| 15 | Root sau dọn | 108 ngay sau cleanup; pytest có thể tái tạo `.pytest_cache` |
| 16 | Bằng chứng test | Giữ nguyên artifacts trước, API ledgers, baseline/native/focused/GUI/regression logs mới |
| 17 | Startup | Native `run_transcomic.py` smoke dùng dữ liệu tạm/HTTP guard; kết quả cuối ghi dưới đây |
| 18 | Regression 1 sau cleanup | Kết quả cuối ghi dưới đây |
| 19 | Regression 2 sau cleanup | Kết quả cuối ghi dưới đây |
| 20 | GUI DPI | Đo thực DPR 1/1.25/1.5, Light/Dark, Tìm/Thay + undo và updater; kết quả dưới đây |
| 21 | Safe Exit | Giữ deadline/assertion 900ms, nằm trong full regression; không sửa backend |
| 22 | Production updater | Signing/build/publisher/helper/install vẫn khóa; chỉ ACL/provisioning ceremony được tách riêng |
| 23 | Git/source | HEAD `6fd3f061c3c78fcae3ec4ebd467858346441ff56`, main; dirty từ các sửa đổi được yêu cầu, không commit/reset/push |
| 24 | Authenticode | SignTool chưa phát hiện; cert/publisher/timestamp chưa cấu hình; Stable requirement giữ nguyên |
| 25 | Trước EXE đầu tiên | Hoàn tất ceremony/USB/public pin được duyệt, source commit sạch/provenance, toolchain/lock/Authenticode/native VM evidence và quyền build/release riêng |

## Kiểm thử và scope

Baseline **trước cleanup**: 724 passed, 1 skipped, 183.94s. Sau đó bổ sung guard cho parent storage và kiểm thử xác nhận/mật khẩu/process native; không sửa backend. Kết quả final pair sẽ được ghi sau khi hoàn tất.

Native/focused logs nằm trong `artifacts/cleanup-review/`. Hai lỗi setup lúc đầu (deny-write chưa được áp dụng đúng và traversal nhắm candidate không được chọn) đã sửa setup, giữ yêu cầu/assertion. GUI Search/Replace lần đầu thiếu navigation để chọn match; sửa helper artifact, không sửa GUI/backend hay nới assertion. Các log lỗi được giữ. Ngay sau cleanup, đối chiếu SHA source và dữ liệu bảo vệ đều không đổi (`after-cleanup-scope.json`). Các API ledger không reset; không gọi Kira/Gemini thật.

VERSION vẫn 0.1.0. Carry 0–9 và chống double bump giữ nguyên. Không tạo Git tag, không build EXE/installer, không chạy installer, không upload/publish; không đổi SQLite schema hoặc DPAPI người dùng.

## Kết quả cuối

| Kiểm tra | Kết quả |
|---|---|
| Focused native/provisioning/cleanup cuối | 15 passed, 2.91s |
| Full sau cleanup lần 1 | **728 passed, 1 skipped**, 185.69s |
| Full sau cleanup lần 2 | **728 passed, 1 skipped**, 184.81s |
| GUI Windows DPR 1 / 1.25 / 1.5 | Đạt Light/Dark, Tìm/Thay + undo, startup và updater download/cancel/hash/offline/helper/logger mocks |
| Source giữa final pair | Hash không đổi; `source-final.json` ghi cả helper GUI artifact |
| Dữ liệu/ledger bảo vệ | Hash không đổi; không xóa/di chuyển/reset |
| Safe Exit / Search / scheduler 429 | Các assertion gốc đạt trong cả hai full suites; giữ nguyên deadline 900ms |
| Root cuối | 109 mục: `.pytest_cache` được pytest tạo lại sau khi dọn; root ngay sau cleanup là 108 |
| Production | Directory/key, backup file, drill và public pin chưa có; backup parent ACL native đã đạt |
| SignTool | Chưa phát hiện; Authenticode Stable và mọi release/install guards giữ nguyên |

Logs/XML và [acceptance.json](../artifacts/cleanup-review/acceptance.json) lưu bằng chứng. Không dùng baseline thay cho kết quả sau cleanup. Không mở rộng xóa những `.pytest_*` chứa dữ liệu/evidence chỉ để giảm số thư mục gốc; 97 mục pending vẫn cần rà soát/quyền riêng. Cache bytecode tạo lại trong quá trình import/test là bình thường. Quarantine vẫn được giữ để khôi phục cache nếu cần, không lấy nội dung giả định để thay dữ liệu.

**PROVISIONING BLOCKED — USER ACTION REQUIRED** là kết luận bàn giao đúng ở lượt này. Người dùng chạy lệnh `python scripts/provision_release_key.py --interactive` trong terminal trực tiếp theo mục phía trên để thực hiện xác nhận/mật khẩu thật. Sau ceremony cần sao chép/kiểm chứng USB và duyệt public pin riêng; không có quyền build hoặc phát hành từ thao tác đó.
