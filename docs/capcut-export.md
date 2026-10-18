# Xuất Project CapCut — báo cáo triển khai source

> Giao diện hiện tại: [một trang với thẻ nhóm mở rộng](capcut-single-page.md). Người dùng đã nghiệm thu project trong CapCut thật; nhiệm vụ UI mới giữ nguyên engine.

> Báo cáo dưới đây ghi nhận lần triển khai đầu. Yêu cầu mới đã thay matching ID bằng matching theo vị trí, thêm Date created và nhập nhiều cặp trong một dialog. Xem [hướng dẫn/trạng thái hiện tại](capcut-positional-import.md); các mô tả bắt buộc ID và báo lỗi file phụ bên dưới là lịch sử, không còn áp dụng.

Ngày: 18/10/2026. Version vẫn **1.1.0**. Không commit/push/build/publish; release public không thay đổi.

## Cách dùng

1. Chạy TransComic từ source với môi trường có dependency trong `pyproject.toml`, chọn **Xuất Project CapCut** ở sidebar.
2. **Thêm cặp thư mục**: chọn một thư mục ảnh, một thư mục audio và đặt tên nhóm. Lặp lại để thêm nhiều nhóm; có thể sửa đường dẫn/tên, xóa khỏi danh sách hoặc dùng ↑/↓ để đổi thứ tự. Xóa nhóm không xóa media.
3. **Kiểm tra tất cả** chạy nền. Bấm **Chi tiết** của nhóm để xem đúng nhóm, hoặc chọn **Toàn bộ nhóm**, lọc **Có lỗi**, tìm ID/tên file. Chọn hàng để xem ảnh, nhấn **Nghe audio** khi muốn nghe; không tự phát khi chọn hàng.
4. Chọn **Xuất từng project** hoặc **Gộp thành một project**, nhập tên tổng nếu gộp và chọn thư mục đầu ra. Nhấn **Xuất Project CapCut**. Trong lúc chạy các thao tác đổi nhóm/cấu hình bị khóa, **Hủy** dừng an toàn.
5. **Mở thư mục xuất** mở Explorer. Đây không phải nút khởi chạy CapCut hoặc tự đăng ký project vào thư viện cá nhân của CapCut.

Chỉ quét file trực tiếp trong hai thư mục đã chọn, không tự tìm thư mục con. Định dạng hiện hỗ trợ: **PNG/JPG/JPEG/WEBP**, **WAV/MP3**. File ngoài các định dạng này, kể cả file phụ trong thư mục, được hiển thị như mục cần kiểm tra, không âm thầm bỏ qua.

Tên an toàn có đúng một cụm chữ số: `001.png` ↔ `001.wav`, `image 10.jpg` ↔ `audio 10.mp3`. `001` và `1` là cùng ID. Tên không có ID hoặc có nhiều cụm số như `chapter01_020000_hash.png` được báo cần kiểm tra, không đoán ghép theo vị trí. Không tự đổi tên/chuyển đổi file. Dãy số có thể bắt đầu ở số khác 1, nhưng khoảng thiếu ở giữa bị chặn xuất.

## A. Hoàn thành theo ba mốc

### Mốc 1 — giao diện và matching

- Trang riêng ở sidebar; hai tab **Danh sách nhóm / Chi tiết**. Danh sách ở trên, cấu hình xuất ở dưới, không chia hai cột cố định.
- Nhiều cặp thư mục, ID nhóm ổn định; đổi tên/đường dẫn, xóa, đổi thứ tự. Persistence bằng khóa settings riêng `capcut_workspace_v1`, không migration schema dịch.
- Matching nghiêm ngặt, kiểm tra định dạng/file trống/ảnh lỗi/audio thiếu duration/thư mục không còn tồn tại. Không lấy `min(count)` hoặc đoán bằng vị trí.
- Probe và quét ở worker; bảng ảo, thumbnail lazy loading chỉ trong RAM, LRU tối đa 128 mục, queue tối đa 32. Preview ảnh lớn chỉ cache hai mục.
- Tái sử dụng audio player hiện có qua một subclass riêng cho đường dẫn dài, không đổi code Kokoro/player TTS, không gọi inference/API.
- Nhóm có nguồn mất vẫn được giữ và cảnh báo khi mở lại. Group data lỗi không tự bị ghi đè thành danh sách trống.

Mốc 1 đã PASS 12 test trước khi triển khai engine (`milestone-1.xml`).

### Mốc 2 — engine và xuất

- Module độc lập UI nhận các `GroupScan` bất biến; xuất một nhóm, nhiều project hoặc một project gộp.
- Dùng template MAU thực từ RAR được cung cấp. Không import app cũ, không nhánh Legacy, không dùng `capcut_effects.py` để tạo hiệu ứng ngẫu nhiên thay template.
- Snapshot chốt ID/order/path/size/mtime/duration của từng cặp trước khi xuất. Recheck media trước và sau khi ghi cấu trúc; nguồn thay đổi/bị xóa thì không publish project đang tạo.
- Chỉ ghi cấu trúc vào thư mục staging riêng dưới output rồi rename sang đích khi kiểm tra thành công. Không copy ảnh/audio/cover vào staging/project/temp/cache đĩa.
- Tránh trùng tên bằng hậu tố `_2`, `_3`…; không ghi đè project hiện có. Có kiểm tra đối tượng khác tạo đích trong lúc worker chạy; chỉ dọn đúng thư mục staging của lượt hiện tại.
- Hủy không xóa project đã hoàn tất trước đó hoặc bất kỳ media nguồn nào. Không đặt output bên trong thư mục media nguồn.

Mốc 2 đã PASS 6 test trước khi tiếp tục nghiệm thu (`milestone-2.xml`).

### Mốc 3 — nghiệm thu

- Hai đường xuất qua nút UI thật, worker nền, progress/Hủy; không dùng thao tác giả.
- Đối soát project gộp **384 cặp = 128 + 121 + 135**, kiểm tra cả hai ranh giới nhóm và tổng duration.
- Tests nguồn thay đổi trong lúc ghi, đích bị tạo đồng thời, không overwrite, không sót staging, giữ hash media.
- Thử UI với 3.000 hàng, Light/Dark, resize cửa sổ thấp; chụp giao diện 100%/150%.
- Regression dịch/editor/Kira/Gemini/UI liên quan chạy offline; không gọi API hoặc chạy Sandbox/GPU/CUDA.

Kết quả test cuối được ghi ở `artifacts/capcut/verification.json`; XML/log giữ tại cùng thư mục.

## B. Source đã sửa/thêm

| File | Vai trò |
|---|---|
| `transcomic/capcut/media.py` | Model immutable, natural order, numeric IDs, probe, matching, source fence, Windows long paths |
| `transcomic/capcut/state.py` | Quản lý nhóm/thứ tự và settings riêng |
| `transcomic/capcut/exporter.py` | MAU, clone material/segment, timeline integer, metadata, validation, publish/cancel |
| `transcomic/capcut/mau-structure.zip`, `mau-origin.json` | Cấu trúc thật từ RAR và hash provenance |
| `transcomic/ui/capcut_page.py` | Hai tab, CRUD nhóm, worker, progress, preview, hai chế độ xuất |
| `transcomic/ui/capcut_media.py` | Model/proxy virtual và thumbnail worker/cache giới hạn |
| `transcomic/ui/capcut_preview.py` | Player hiện có, chuẩn hóa URL đường dẫn dài riêng cho CapCut |
| `transcomic/ui/main.py`, `workspace_v2.py` | Sidebar/lazy page, safe exit/cancel; vùng nav có cuộn khi cửa sổ thấp |
| `transcomic/ui/theme.py`, `assets/nav-capcut.svg` | Tabs dùng palette chung, icon CapCut |
| `pyproject.toml`, `TransComic.spec` | Mutagen nhẹ cho MP3 và khai báo đóng gói resource MAU; không thực hiện build |
| `tests/test_capcut_media.py`, `test_capcut_export.py`, `test_capcut_ui.py` | Matching, engine và GUI regression |
| `tests/test_workspace_v2.py` | Cập nhật danh sách navigation dự kiến có mục mới, giữ index cũ |
| `scripts/check_capcut_source.py` | Fixture tổng hợp, project mẫu, ảnh UI, không động vào database sản xuất |

Không thay logic Kira/Gemini, retry/quota, DOCX/TXT, export dịch, Kokoro/CUDA hay updater. Các thay đổi Kira từ phiên trước vẫn được giữ trong working tree, không rollback.

## C. Matching và thứ tự

Natural order dùng số nguyên trong tên file, không dùng timestamp. ID được chuẩn hóa theo số; duplicate ID được báo kể cả khác đuôi/leading zero. Bảng hiển thị cả thiếu ảnh và thiếu audio; `004.png` không thể bị ghép với `003.wav`. File không xác định ID hoặc không đọc được được giữ trong báo cáo lỗi.

Danh sách nhóm được lưu theo thứ tự người dùng chọn. Snapshot export gồm group ID, pair ID, thứ tự toàn cục, đường dẫn gốc, duration microsecond và fingerprint nguồn. Worker hoàn thành nhanh/chậm không thay đổi mapping. Khi gộp, template pattern chạy xuyên suốt các nhóm, không reset timeline ở ranh giới chương.

Audio WAV đo bằng frame/rate và kiểm tra frame cuối; MP3 đọc stream metadata qua [Mutagen MP3](https://mutagen.readthedocs.io/en/latest/api/mp3.html), không fallback duration giả. Dependency Mutagen là Python thuần, không thêm FFmpeg/GPU/TTS provider. Ảnh được đọc có giới hạn kích thước bằng [QImageReader](https://doc.qt.io/qtforpython-6/PySide6/QtGui/QImageReader.html); thumbnail/preview không ghi file mới.

## D. Bằng chứng MAU và không copy media

RAR đầu vào tồn tại và đã được giải nén/đọc. SHA-256:

`099525748df23c0cdcfecacc5d57702a1432a0337e92aa93d2087b743b8e1327`

Template thực có **2 video track × 4 segment**, **1 audio track × 1 segment**, canvas, common keyframes và 8 material animation. 30 file cấu trúc JSON/config từ template được giữ trong asset ZIP có hash kiểm tra. Không lấy cover/media/backup/crypto store cũ vào asset cấu trúc. Các content variants được tạo lại đồng nhất, không giữ nội dung backup cũ.

Engine clone cấu trúc của từng pattern, giữ `clip`, các giá trị keyframe và animation resource ID; chỉ đổi ID nội bộ, media/path/kích thước và thời gian. Video layers/overlap của MAU được map theo các mốc template sang slot đầu ra. Không biến thành một track slideshow. Hai track vẫn tồn tại cả khi số slide ít.

Audio là các segment riêng, start bằng tổng duration các clip trước, source start = 0, source duration = target duration = duration thực. Không source headroom vượt nguồn, không nối MP3, không thêm gap/padding. Timeline và keyframe offset dùng microsecond integer.

Root và `Timelines/<timeline-id>/draft_content.json`, `template.tmp`, `template-2.tmp` có cùng content. Timeline index/layout, project ID, material index, segment ID mapping và metadata được cập nhật. Material/segment IDs được tạo mới; validator chặn missing refs, duplicate IDs, sai media/thứ tự, gap/overlap/cắt audio, duration/keyframe ngoài phạm vi.

Audit project mẫu: **0 ID local cũ**, **0 reference media cũ**, không file ảnh/audio/MP4 và không thư mục `local_media` trong output. Mọi đường dẫn ảnh/audio trỏ tuyệt đối tới fixture gốc còn tồn tại; hash media trước/sau không đổi. Bằng chứng `template-integrity-audit.json`, `acceptance-light-100.json` và `transcomic_mapping.json` trong từng project.

## E. Hai chế độ xuất

Project mẫu mới nhất được liệt kê trong `artifacts/capcut/acceptance-light-100.json`:

- Ba nhóm 2/3/4 cặp → **ba project riêng**, mỗi project chỉ chứa một nhóm.
- Ba nhóm đó → **một project gộp 9 cặp**, 9 audio segment, 2 video track, đúng thứ tự nhóm và tổng duration.
- Test riêng 128/121/135 → **một project 384 cặp**. Không lặp hoặc mất slide tại ranh giới 128 và 249.

Fixture được tạo mới trong `artifacts/capcut/demo-media-readable`, không lấy tài liệu/media riêng của người dùng. Những lần tạo mẫu trước được giữ lại, không ghi đè hoặc xóa.

## F. GUI

Ảnh chụp toàn cửa sổ bằng source, offscreen/software để không gây tải GPU:

| DPI | Light | Dark |
|---|---|---|
| 100% | [Nhóm](../artifacts/capcut/light-100-groups.png) · [Chi tiết](../artifacts/capcut/light-100-details.png) | [Nhóm](../artifacts/capcut/dark-100-groups.png) · [Chi tiết](../artifacts/capcut/dark-100-details.png) |
| 150% | [Nhóm](../artifacts/capcut/light-150-groups.png) · [Chi tiết](../artifacts/capcut/light-150-details.png) | [Nhóm](../artifacts/capcut/dark-150-groups.png) · [Chi tiết](../artifacts/capcut/dark-150-details.png) |

Offscreen Windows cần đăng ký font Segoe UI có sẵn để ảnh chụp hiển thị đúng; script capture làm việc này riêng, không đổi font/runtime ứng dụng. Preview không tự phát audio. Nghe thử dùng output device hiện tại và cơ chế dừng an toàn của player sẵn có. Không xác nhận chất lượng nghe bằng tai qua screenshot/mock.

## G. Tests

Các XML trong `artifacts/capcut/` ghi rõ PASS/FAIL và thời gian:

- Mốc 1: 12 PASS trước engine.
- Mốc 2: 6 PASS trước nghiệm thu.
- CapCut acceptance cuối: 26 PASS, gồm WAV/MP3 thật tổng hợp, Unicode/path có khoảng trắng/Windows long path, thiếu giữa, trùng ID, source bị xóa/thay đổi, destination race, 384 cặp, metadata/curves/resource IDs, GUI/hủy/preview và 3.000 hàng.
- GUI regression Liquid Glass + các sửa UI trước: 49 PASS sau khi sửa scope import `QScrollArea`; log lỗi trung gian được giữ.
- Regression rộng trong phạm vi dịch/editor/Kira/Gemini/UI và CapCut: **835 PASS, 10 deselected, 355,42 giây** (`offline-regression.xml/.log`). Các ca stress load lớn không chạy. Kiểm tra CapCut trên source chốt cuối: **26 PASS**, 7,87 giây (`acceptance-final.xml`). Không cộng số test trùng lặp giữa các lượt.

Không chạy stress load lớn, Windows Sandbox, CUDA, inference TTS hoặc test update thực tế. Không gọi API Kira/Gemini trong nhiệm vụ này.

## H. CapCut thực tế

Máy có thư mục CapCut và **8/8 thư mục cache animation** được template tham chiếu tồn tại. Chỉ kiểm tra chỉ đọc. **Chưa mở project trong CapCut thực tế**: giữ giới hạn an toàn sau BSOD `VIDEO_MEMORY_MANAGEMENT_INTERNAL` và lần treo trước đó, không khởi chạy ứng dụng dựng hình/GPU để nghiệm thu.

Vì vậy chưa chứng minh decoder/render của phiên bản CapCut đang cài hiển thị/đọc audio/chuyển động đúng. Không khẳng định project xuất hiện tự động trong library CapCut, không sửa project registry hoặc project cá nhân để ép nhập. Việc mở và xem project mẫu nhỏ trong CapCut còn cần nghiệm thu ở điều kiện máy ổn định.

## I. Hạn chế còn lại

- Schema CapCut riêng theo template đã cung cấp; không cam kết mọi phiên bản CapCut. File crypto/cache/backup lịch sử của project gốc không được mang theo; tương thích native vẫn phải kiểm chứng.
- Cache hiệu ứng hiện có trên máy này; máy khác có thể cần CapCut tự tải resource ID tương ứng. TransComic không tải hoặc copy cache hiệu ứng.
- Tên nhiều cụm số/không có số bị chặn, chưa có mapping tay cho kiểu tên mơ hồ. Không đoán thứ tự để đủ số lượng.
- Di chuyển/đổi tên/xóa media gốc sau export sẽ làm project mất liên kết; không có media backup hoặc cơ chế chuyển đổi format.
- Khi nguồn ở ổ/network không phản hồi, không thể hủy cưỡng bức một lệnh đọc hệ điều hành đang chờ; hủy được kiểm tra giữa các file/các bước. Worker không truy cập database dịch; safe exit yêu cầu dừng lượt đang chạy.
- Mutagen có giấy phép riêng đi cùng dependency; phần đóng gói/notice cho một release tương lai cần đi qua quy trình release hiện có. Nhiệm vụ này không build phát hành.

## J. Kết luận

**PARTIAL — NEEDS VERIFICATION.** Đã triển khai source từ UI đến engine và hai chế độ xuất; ba mốc kiểm thử source hoàn thành. Project MAU có mapping/timeline/material references được kiểm tra tự động và không nhân bản media. Còn nghiệm thu mở/nghe/render trong CapCut thật; không tuyên bố hoàn tất 100% hoặc tự phát hành.
