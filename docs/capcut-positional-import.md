# CapCut — nhập nhiều cặp, matching theo vị trí và giao diện gọn

> Bố cục hai tab trong báo cáo này đã được thay bằng [một trang với thẻ nhóm mở rộng](capcut-single-page.md). Matching/export bên dưới giữ nguyên; người dùng đã xác nhận project hoạt động trong CapCut thật.

Ngày 18/10/2026 · source v1.1.0 · chưa phát hành.

## A. Nguyên nhân lỗi cũ

Matcher cũ chỉ chấp nhận tên có đúng một cụm số và yêu cầu ảnh/audio cùng ID. Ảnh thực tế có tên `chapter01_020000__78e9fc48d52947d5a6ec10ac021e59b7.png`, audio có tên `0001.wav`; các cụm số của ảnh/hậu tố hash không phải ID audio. Vì vậy dù hai bên cùng 184 file, bộ cũ báo 0 cặp. Nó còn đưa audio phụ trong thư mục ảnh vào danh sách ảnh lỗi.

Yêu cầu mới chủ đích thay nguyên tắc này. Matcher hiện không dùng ID trong tên để quyết định ghép; không yêu cầu đổi tên file. Số STT trong bảng là vị trí xuất, không phải số trích từ tên.

## B. Matching mới

- **Audio:** chỉ WAV/MP3 trực tiếp trong thư mục audio người dùng chọn; luôn natural sorting trên toàn bộ tên. `1`, `2`, `10` đúng thứ tự; nhiều cụm số được chấp nhận. Không dùng created/modified để sắp audio.
- **Ảnh:** chỉ PNG/JPG/JPEG/WEBP trực tiếp trong thư mục ảnh người dùng chọn. Mặc định natural filename; mỗi nhóm có thể chọn **Theo ngày tạo**.
- **Date created:** dùng `st_birthtime_ns` từ metadata khi có; Windows cũ dùng `st_ctime` vốn mang creation time, không dùng `st_mtime`. Thiếu created đáng tin cậy thì nhóm có lỗi và chặn xuất ở chế độ này. Created tăng dần; tie dùng natural filename, normalized absolute path và path đầy đủ để thứ tự luôn xác định.
- **Ghép:** ảnh thứ n ↔ audio thứ n. Tên không có số, nhiều cụm số, leading zeros không tạo lỗi ID. Dãy tên có số thiếu không được dùng để suy luận thiếu nội dung.
- **Validation:** kiểm tra thư mục/file tồn tại, đường dẫn bị liệt kê trùng, rỗng/hỏng, decoder ảnh, duration audio. Không quét đệ quy. Audio chính nằm dưới thư mục ảnh là hợp lệ; audio phụ ở cha không tham gia danh sách ảnh hoặc voice.
- **Lệch số lượng:** hiển thị tất cả hàng bằng số lượng lớn hơn, phần dư thiếu counterpart; **mọi hàng** đều đánh dấu chưa xác nhận vì không biết thiếu ở giữa hay cuối. Số cặp xác nhận = 0, không cho xuất. Không lấy `min(count)`.
- **Bằng số lượng:** khi mọi file đọc được thì mapping hợp lệ về cấu trúc; không chứng minh nội dung ảnh/giọng đúng ngữ nghĩa. Người dùng cần xem tab Chi tiết trước khi xuất.

Thời gian ở cột **Ngày tạo ảnh** dùng `datetime.fromtimestamp(...).astimezone()` để hiển thị theo timezone Windows hiện tại, kèm offset. Capture/test không thay timezone máy.

## C. Nhập nhiều cặp trong một cửa sổ

**Thêm các cặp thư mục ảnh và audio** có danh sách cuộn. Mỗi cặp có tên, đường dẫn ảnh/audio, hai nút Chọn riêng, mode sắp ảnh và Xóa cặp. **+ Thêm cặp thư mục** thêm ngay trong dialog; đã kiểm tra 1/2/10/20 cặp.

Chọn ảnh chỉ gợi ý tên và vị trí bắt đầu hộp thoại audio; **không điền/chọn audio tự động**. Các entry khác giữ nguyên khi mở/đóng folder picker. **Xác nhận tất cả** kiểm tra đầy đủ tất cả entry trước khi trả về; thiếu cặp nào báo đúng số. Cặp trùng đường dẫn với entry khác/nhóm đã lưu yêu cầu người dùng xác nhận, mặc định không thêm. Hủy dialog không ghi settings hay đổi danh sách đã lưu. Việc đọc decoder/kiểm tra media chạy nền sau khi thêm.

Đổi tên/sửa một nhóm dùng cùng form ở chế độ một entry, giữ ID nội bộ. Settings dùng khóa `capcut_workspace_v1` cũ, thêm `image_sort`, default `name` cho nhóm chưa có trường này. Không xóa nhóm cũ hoặc đổi đường dẫn. Không migration schema dịch/TTS.

## D. Giao diện

- Thẻ thu gọn **hai dòng**, khoảng 76 logical pixels trong ảnh nghiệm thu: dòng 1 tên/thống kê; dòng 2 sort mode, Chi tiết, Sửa, ↑/↓, Xóa và **…** mở rộng. Không hiển thị hai đường dẫn dài khi thu gọn; tooltip và panel mở rộng giữ toàn bộ đường dẫn/lỗi.
- Chọn mode riêng từng nhóm bắt đầu quét nền; mapping cũ bị loại, bảng Chi tiết được cập nhật khi scan hoàn tất. Hủy scan không cho dùng lại kết quả cũ. Không phải thêm lại nhóm.
- Chi tiết có bảy cột: STT/nhóm, thumbnail, tên ảnh, tên audio, ngày tạo ảnh, duration, trạng thái; có cuộn ngang. STT toàn cục và số trong nhóm rõ ràng, group order giữ đúng khi xem toàn bộ. Preview/player cũ giữ nguyên, không tự phát.
- Giữ phần cài đặt xuất phía dưới; danh sách cuộn riêng. Không thiết kế lại sidebar hoặc trang khác trong nhiệm vụ này.

Ảnh nghiệm thu với 10 nhóm và dialog 20 entry, không dùng media riêng:

| Theme / DPI | Nhóm | Chi tiết | Dialog |
|---|---|---|---|
| Light 100% | [Ảnh](../artifacts/capcut-positional/light-100-groups.png) | [Ảnh](../artifacts/capcut-positional/light-100-details.png) | [Ảnh](../artifacts/capcut-positional/light-100-import-dialog.png) |
| Dark 100% | [Ảnh](../artifacts/capcut-positional/dark-100-groups.png) | [Ảnh](../artifacts/capcut-positional/dark-100-details.png) | [Ảnh](../artifacts/capcut-positional/dark-100-import-dialog.png) |
| Light 150% | [Ảnh](../artifacts/capcut-positional/light-150-groups.png) | [Ảnh](../artifacts/capcut-positional/light-150-details.png) | [Ảnh](../artifacts/capcut-positional/light-150-import-dialog.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-positional/dark-150-groups.png) | [Ảnh](../artifacts/capcut-positional/dark-150-details.png) | [Ảnh](../artifacts/capcut-positional/dark-150-import-dialog.png) |

## E. Dữ liệu thực tế — chỉ đọc

Hai thư mục được yêu cầu đều tồn tại:

- Ảnh: `[thư mục ảnh kiểm thử riêng — đã ẩn đường dẫn]`
- Audio: `[thư mục audio kiểm thử riêng — đã ẩn đường dẫn]`

| Mode ảnh | Ảnh hợp lệ | Audio hợp lệ | Cặp | Lỗi | Thời gian scan |
|---|---:|---:|---:|---:|---:|
| Tên tự nhiên | 184 | 184 | 184 | 0 | 2,133 giây |
| Date created | 184 | 184 | 184 | 0 | 1,746 giây |

Đây là một lần đo trên nguồn hiện có, không phải benchmark tốc độ hoặc xác minh ngữ nghĩa. Ba cặp đầu/cuối mỗi mode lưu ở [user-readonly.json](../artifacts/capcut-positional/user-readonly.json); bảng đầy đủ tên file cần báo cáo ở phần dưới. Chỉ đọc/probe, không copy/đổi tên/sửa/di chuyển/xóa media; không xuất project từ thư mục riêng này và không dùng database sản xuất.

## F. Bảo toàn export MAU

**Không sửa `transcomic/capcut/exporter.py`, asset MAU hoặc template gốc trong nhiệm vụ này.** Engine nhận thứ tự từ snapshot của matcher như trước. Hai video track, keyframe/value curve, animation resource, mapping materials, audio segment riêng/gap 0, duration integer, source fingerprint, cancel/atomic publish và collision-safe naming vẫn giữ nguyên.

Regression kiểm tra một nhóm 184 cặp, hai nhóm mode sắp khác nhau xuất riêng và gộp; đối chiếu `transcomic_mapping.json` với thứ tự `GroupScan.rows`. Tests cũ 384 cặp, không copy media, hash nguồn, sai path/gap, nguồn đổi giữa lúc ghi, đích bị tạo cùng lúc, cancel và timeline validation vẫn chạy. Đổi mode trên UI xóa scan cũ trước khi worker chạy; export chỉ nhận scan mới đã hoàn tất.

## G. Tests

Kết quả và XML/log nằm trong `artifacts/capcut-positional/`. `verification.json` ghi số cuối cùng và các gate source. Lượt focused sau chuyển matching: **40 PASS, 18,51 giây** (`focused-second.xml`). Hai assert cũ về bắt buộc ID được cập nhật đúng yêu cầu mới, không bỏ test kiểm tra lỗi nguồn/mismatch.

- **Regression rộng: 849 PASS, 10 deselected, 370,98 giây**, 47 file tests, gồm Kira/Gemini/editor/GUI và CapCut (`regression.xml/.log`).
- **Nghiệm thu cuối: 44 PASS, 18,10 giây** (`acceptance-final.xml`), bổ sung duplicate listing, không dùng modified, nút nhập thực tế, combobox sort thực tế và geometry/click controls ở cửa sổ thấp.
- AST 9 file mới/sửa hợp lệ; `git diff --check` trả 0. SHA-256 `exporter.py` trước/sau bằng nhau, template MAU không đổi (`engine-unchanged.json`). Không thay source sidebar, translation, TTS, updater hoặc version trong nhiệm vụ này.

Các trường hợp gồm natural toàn tên, ảnh không số/nhiều số, audio nhiều số, created tăng dần/tie/thiếu metadata, thiếu giữa/counterpart không bằng nhau, không recursion/voice con/audio phụ cha, 184 tên khác nhau, nhiều entry/cancel/thiếu/trùng, tên và sort persistence, expand/compact, preview, bảng 3.000 hàng, hai export mode và source không đổi. Toàn bộ là fixture tổng hợp, ngoài lần scan chỉ đọc được cấp quyền ở mục E.

Không mở CapCut, không chạy API/TTS/GPU/CUDA/Sandbox, không build. Phần regression rộng vẫn loại các test load/tracemalloc lớn như phiên trước để giữ tải nhẹ trên máy từng BSOD. Không cộng các số test trùng giữa các lượt.

## H. File sửa/thêm

- `transcomic/capcut/media.py`: positional matching, tách phần mở rộng ảnh/audio, Date created, fingerprint/immutable snapshots.
- `transcomic/capcut/state.py`: mặc định tương thích sort mode và thêm nhiều nhóm trong một lần lưu.
- `transcomic/ui/capcut_import.py` **mới**: dialog nhiều entry, manual folder pick, validation/cảnh báo trùng/cancel.
- `transcomic/ui/capcut_page.py`: form mới, compact/expand, per-group sort và invalidation/quét lại.
- `transcomic/ui/capcut_media.py`: cột created, STT vị trí, trạng thái và tìm theo tên file thay vì cả đường dẫn tạm.
- `scripts/check_capcut_source.py`: tùy chọn capture 10 nhóm/dialog20, artifact root riêng.
- `tests/test_capcut_media.py`: cập nhật các assert matching cũ theo yêu cầu positional.
- `tests/test_capcut_positional.py`, `tests/test_capcut_import.py` **mới**: regression cho yêu cầu lần này.
- README, báo cáo này và link cập nhật đầu báo cáo triển khai trước.

## I. Giới hạn

- Cùng số lượng không phát hiện được ảnh và audio bị mất ở hai vị trí khác nhau hoặc nội dung bị lệch: user chủ đích chọn positional; cần duyệt thứ tự/nghe nội dung.
- Nếu không đọc được creation time đáng tin cậy thì không xuất ở mode created. Không tự dùng modified.
- Các định dạng ngoài PNG/JPG/JPEG/WEBP và WAV/MP3 không tham gia scan. Không chuyển đổi hay quét thư mục con, không tìm voice tự động.
- **Chưa nghiệm thu mở/render/nghe trong CapCut thật**, giữ giới hạn an toàn GPU từ phiên trước. Các thay đổi matcher/UI không giải quyết tương thích native giữa các phiên bản CapCut. Không tuyên bố rằng đã xác minh bằng CapCut.
- Source chưa đóng gói vào EXE; cần chạy source mới để dùng. Release public v1.1.0 và dữ liệu riêng giữ nguyên.

## J. Trạng thái

Mức source: **READY FOR USER ACCEPTANCE** — các gate cuối ở `verification.json` PASS. Native CapCut: **CHƯA KIỂM CHỨNG**. Không phát hành tự động.

## Phụ lục: ba cặp đầu và cuối từ lần quét chỉ đọc

### Ảnh theo tên tự nhiên

| STT | Ảnh | Audio |
|---:|---|---|
| 1 | `chapter01_020000__78e9fc48d52947d5a6ec10ac021e59b7.png` | `0001.wav` |
| 2 | `chapter01_030000__be86bb000fd34441bec24328337d938c.png` | `0002.wav` |
| 3 | `chapter01_040000__9249a5c6486441278126f7b410eb49bd.png` | `0003.wav` |
| 182 | `chapter01_1830000__18ee29d970b7447aabcb8304af50dfc1.png` | `0182.wav` |
| 183 | `chapter01_1840000__6858e47de54645a3b743d06467a53df4.png` | `0183.wav` |
| 184 | `chapter01_1850000__81b8fc49632e44f5ab83b8b05d3bed76.png` | `0184.wav` |

### Ảnh theo Date created

| STT | Ảnh | Audio |
|---:|---|---|
| 1 | `chapter01_020000__78e9fc48d52947d5a6ec10ac021e59b7.png` | `0001.wav` |
| 2 | `chapter01_030000__be86bb000fd34441bec24328337d938c.png` | `0002.wav` |
| 3 | `chapter01_040000__9249a5c6486441278126f7b410eb49bd.png` | `0003.wav` |
| 182 | `chapter01_970000__934dbb4f06834b6b94004d9c4c2e91c8.png` | `0182.wav` |
| 183 | `chapter01_980000__fd19102d356c4a4b9580a6dd1a9c255b.png` | `0183.wav` |
| 184 | `chapter01_990000__d787b6440b884ca0a11532448eab5635.png` | `0184.wav` |
