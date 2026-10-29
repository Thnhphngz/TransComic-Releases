# Hồ sơ xác nhận quyền phân phối — TransComic

Ngày ghi nhận: 29/10/2026. Căn cứ: yêu cầu trực tiếp của người dùng
“FINAL FIX, VERIFY & RELEASE TRANSCOMIC v2.0.3”, mục 1.

## Căn cứ và phạm vi

Người dùng xác nhận có quyền sử dụng và phân phối các thành phần liên quan
đến B01; xác nhận project CapCut MAU do chính mình tạo/chỉnh sửa trong CapCut
và cung cấp làm mẫu, đồng thời có các quyền cần thiết đối với tài nguyên
liên quan. Yêu cầu này nêu rõ việc phân phối GUI kết hợp Mutagen và các
resource animation đi kèm; hồ sơ ghi nhận xác nhận trong chính phạm vi đó.

- B01: **CLOSED — USER-CONFIRMED DISTRIBUTION AUTHORITY**, cho GUI TransComic
  kết hợp Mutagen **1.48.1** hiện có. Không chỉ ghi nhận quyền chạy Mutagen
  trên máy cá nhân; xác nhận bao gồm việc phân phối thành phần kết hợp.
- B02: **CLOSED — USER-CONFIRMED DISTRIBUTION AUTHORITY**, cho mẫu MAU và
  **32 file animation hiện có**, bao gồm các resource được đóng gói và
  materialize bởi exporter hiện tại.

Đây là xác nhận của bên cung cấp dự án/tài nguyên, không phải giấy phép mới,
chứng thư của chủ sở hữu bên thứ ba hay kết luận pháp lý độc lập do Codex cấp.
Không suy ra rằng mọi tài nguyên khác xuất từ CapCut đều được phép phân phối.
Việc người dùng tạo project và việc có quyền đối với tài nguyên được ghi
nhận riêng; căn cứ quyền đối với tài nguyên là xác nhận rõ ràng của người dùng.

## Thành phần đã đối chiếu

| Thành phần | Định danh giữ nguyên |
| --- | --- |
| Mutagen source 1.48.1 | SHA-256 `8f95637ab9f6f305cec6bd1294e197debe207998e3e068596563c74f86b0a173` |
| Mutagen COPYING | SHA-256 `8177f97513213526df2cf6184d8ff986c675afb514d4e68a404010521b880643` |
| `mau-animations.zip` | SHA-256 `8b502954565bcc73109d5799a91d229faf6c966615c9951b3cdf1828543972ad` |
| `mau-structure.zip` | SHA-256 `81dfac45e0006dc9cf2e248024fdb82d5259b60a239369ae679427685298ad25` |

Inventory và hash của từng file animation nằm trong `transcomic/capcut/mau-origin.json`.
Corresponding-source kit giữ source, copyright, COPYING, LICENSE, notices và
provenance hiện hành; khớp lock/worker/bootstrap. Không thay Mutagen, animation,
engine Kokoro, WAV/MP3 hay CapCut exporter để xử lý hai mục này.

Các điều kiện giấy phép hiện hành tiếp tục áp dụng. Xác nhận này không miễn
nghĩa vụ giữ source/notices và không thay đổi quyền của người nhận. Không có
grant bổ sung nào được tự soạn hoặc gán cho bên thứ ba.

## Tái sử dụng và giới hạn

Các release sau tái sử dụng hồ sơ này khi thành phần, resource và phạm vi
phân phối không thay đổi. Chỉ mở lại B01/B02 nếu đổi thư viện/resource, điều
kiện cấp phép hoặc xuất hiện bằng chứng mâu thuẫn có ý nghĩa; phải nêu đúng
phần thay đổi. Việc build một phiên bản mới không tự mở lại hai mục.

Đóng B01/B02 không đồng nghĩa nghiệm thu Installer hoặc updater. Các gate
kỹ thuật, bảo toàn dữ liệu, source kit và checksum vẫn phải kiểm tra riêng.
