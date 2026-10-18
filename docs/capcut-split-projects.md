# CapCut — chia đều nhiều project và bìa riêng

> Cập nhật mới: [tên từng part, thống kê header và typography nhóm](capcut-names-header.md). Các nguyên tắc chia/timeline/cover bên dưới giữ nguyên.

19/10/2026 · Source **v1.1.0** · Không build/commit/push/publish.

## 1. Ba chế độ xuất

Đã triển khai trong cùng đợt:

1. **Xuất từng nhóm thành project riêng**: giữ tên và thứ tự nhóm.
2. **Gộp tất cả thành một project**: dùng tên chung.
3. **Chia đều thành nhiều project**: dùng tên chung và số part.

Chế độ chia hiện ô **Số project muốn chia**, chỉ nhận số nguyên 2…tổng nhóm. Dưới hai nhóm thì ô bị khóa, có giải thích và không thể xuất. Thêm/xóa nhóm cập nhật giới hạn; số part vượt giới hạn được điều chỉnh và lưu lại. Mode, tên, output và part count được lưu trong workspace hiện có, không migration schema.

Giữ bố cục thẻ ba hàng, hai đường dẫn responsive, accordion, Xóa toàn bộ, preview ảnh/audio và focus theo hàng của đợt UI trước. Chỉ thêm vùng kế hoạch xuất trong cấu hình cố định dưới danh sách.

## 2. Thuật toán và preview

Với G nhóm, N part: `q, r = divmod(G, N)`. Part đầu tiên đến part r có q+1 nhóm; các part sau có q nhóm. Cắt các đoạn liên tiếp theo thứ tự hiện tại. Nhóm không bị chia nhỏ, kể cả nhóm chứa nhiều ảnh/voice hơn các nhóm khác.

| Nhóm / part | Số nhóm mỗi part |
|---|---|
| 10 / 2 | 5 + 5 |
| 10 / 3 | 4 + 3 + 3 |
| 10 / 4 | 3 + 3 + 2 + 2 |
| 20 / 3 | 7 + 7 + 6 |
| 100 / 4 | 25 + 25 + 25 + 25 |
| 103 / 4 | 26 + 26 + 26 + 25 |
| 200 / 3 | 67 + 67 + 66 |
| 200 / 4 | 50 + 50 + 50 + 50 |
| 200 / 5 | 40 + 40 + 40 + 40 + 40 |

Preview và exporter dùng chung planner. Bảng có Project/Các nhóm/Số nhóm; tooltip liệt kê tên nhóm thực tế. Cập nhật ngay khi đổi số part, tên hoặc thứ tự nhóm. Bảng ảo giới hạn cao 136 logical pixels, cuộn khi nhiều part; không tạo widget theo từng dòng.

Tên `vote` sinh `vote_part1`, `vote_part2`… Tên có khoảng trắng như `1 - 20 vote` giữ khoảng trắng hợp lệ. Dùng quy tắc sanitize hiện có; tên quá dài được rút ở phần tên chung để giữ nguyên hậu tố part và không gây trùng tên giữa các part. Tên project đã có vẫn dùng hậu tố collision `_2`, `_3`…; preview chưa dự đoán các va chạm có thể xảy ra lúc xuất.

## 3. Tích hợp engine, tiến độ và hủy

Tất cả scan/snapshot và fingerprint nguồn được xác minh trước part đầu. Kế hoạch dùng các GroupScan bất biến theo thứ tự đã chốt. UI chốt cả mode/name/count/output trước khi gửi worker; thay đổi cấu hình bị khóa trong lúc xuất.

Mỗi part gọi lại `write_project` MAU hiện có. Các hàm build timeline, validation, clone segment, xử lý tên và kiểm tra nguồn có AST khớp baseline; matcher, template/provenance và version giữ nguyên hash.

- Timeline mỗi part bắt đầu từ 0.
- Giữ hai video track, keyframe/value curve, animation, duration microseconds, audio gap = 0 và direct media references.
- Không gộp MP3, không copy ảnh/voice gốc.
- Tiến độ gộp theo số part, tăng đơn điệu đến 100% sau thành công.
- Mỗi part dùng staging và atomic publish cũ. Hủy/lỗi ở part sau giữ part đã publish, dọn staging chưa hoàn tất. Thông báo nêu số project đã giữ; output hiện tại vẫn mở được.
- Không thay đổi collision/race gate hoặc ghi đè project có sẵn.

## 4. Bìa riêng: bằng chứng và giới hạn

Đã đọc mẫu CapCut MAU thật được cung cấp trong `references/capcut/extracted/capcut_template_mau`:

- Metadata có `draft_cover: "draft_cover.jpg"`, `cloud_draft_cover: false`.
- Có bìa tại root và `Timelines/<timeline-id>/draft_cover.jpg`.
- Bìa mẫu gốc là JPEG 1920×1080. Code tham chiếu cũng ghi metadata/file theo tên này.

Exporter tạo **thumbnail JPEG 640×360 từ ảnh đầu tiên của từng part**, giữ aspect ratio và đặt nền tối khi cần. Ghi tại hai vị trí theo mẫu bên trong staging trước khi kiểm tra nguồn/publish. Không tái sử dụng ảnh đầu của toàn bộ job cho mọi part. Hai JPEG này là thumbnail được tạo mới, không phải bản copy media nguồn; các tham chiếu timeline tiếp tục trỏ tới file gốc.

**Đã xác minh schema/file dựa trên mẫu native và kiểm tra nội dung thumbnail offline; chưa mở các project mới trong CapCut thật để nghiệm thu cách hiển thị bìa.** Không coi nghiệm thu engine trước đây của người dùng là nghiệm thu bìa mới. Không chạy CapCut/GPU/Sandbox/CUDA vì giới hạn an toàn máy.

## 5. Kết quả xuất mẫu

Xuất thành công 10 nhóm tổng hợp × 2 cặp, chia 4 part:

| Project | Nhóm | Cặp | Timeline bắt đầu |
|---|---|---:|---:|
| vote_part1 | 1–3 | 6 | 0 |
| vote_part2 | 4–6 | 6 | 0 |
| vote_part3 | 7–8 | 4 | 0 |
| vote_part4 | 9–10 | 4 | 0 |

Các project mẫu nằm ở [demo-projects/split](../artifacts/capcut-split/demo-projects/split). [Receipt](../artifacts/capcut-split/sample-receipt.json) lưu source ảnh đầu, thứ tự nhóm, số cặp và hash bìa. Bốn bìa có hash khác nhau; xem [ảnh đối chiếu bốn bìa](../artifacts/capcut-split/part-covers.png). Hash toàn bộ media mẫu trước/sau khớp.

## 6. Kiểm thử

- **114 PASS** trong regression toàn bộ CapCut, gồm hai mode cũ, split, cover, positional matching, timeline, staging/cancel/collision, UI/card/clear/player và model lớn; thời gian 62,22 giây.
- **56 PASS** GUI scale 150%, Light/Dark và cửa sổ rộng/hẹp; thời gian 50,52 giây.
- Mọi case chia ở bảng trên đã có **xuất thật bằng engine với media tổng hợp**, không chỉ kiểm tra danh sách số. Bao gồm nhóm nhiều ảnh hơn, đảo thứ tự trước xuất, đủ tất cả nhóm một lần, đúng ranh giới, không thay đổi nguồn và timeline từng part bắt đầu từ 0.
- Kiểm N bằng G, 0/âm/1/vượt G, số không nguyên; tên dài giữ suffix; preview live và persistence; 200 hàng preview giới hạn chiều cao; một nhóm không đủ điều kiện chia; clear/add/reorder cập nhật lại giới hạn.
- Hủy giữa part 2 giữ part 1, không còn staging. Lỗi part 2 giữ part 1. Lỗi ghi cover không publish project dở dang. Nguồn cuối job đổi thì không xuất part đầu. Collision không ghi đè.
- Hai assert cũ “không có bất kỳ file ảnh nào trong project” được cập nhật thành chỉ cho phép **đúng hai thumbnail cover**; vẫn cấm copy mọi media nguồn/audio và giữ các gate hash/direct paths.

Bằng chứng: [regression 100%](../artifacts/capcut-split/regression-100.xml), [GUI 150%](../artifacts/capcut-split/gui-150.xml), [verification](../artifacts/capcut-split/verification.json).

## 7. UI và screenshot

Capture MainWindow thật bằng Qt software/offscreen trên Windows, scale 1 và 1,5; không thay DPI/driver hệ thống. Cấu hình xuất vẫn ngoài vùng cuộn nhóm. Preview chỉ hiện ở mode chia và hiển thị gọn bốn part thường dùng; nhiều part có scrollbar.

| Theme / scale | Trang đầy đủ | Cửa sổ hẹp |
|---|---|---|
| Light 100% | [Ảnh](../artifacts/capcut-split/light-100-collapsed.png) | [Ảnh](../artifacts/capcut-split/light-100-narrow.png) |
| Dark 100% | [Ảnh](../artifacts/capcut-split/dark-100-collapsed.png) | [Ảnh](../artifacts/capcut-split/dark-100-narrow.png) |
| Light 150% | [Ảnh](../artifacts/capcut-split/light-150-collapsed.png) | [Ảnh](../artifacts/capcut-split/light-150-narrow.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-split/dark-150-collapsed.png) | [Ảnh](../artifacts/capcut-split/dark-150-narrow.png) |

## 8. Source và trạng thái

- `capcut/planning.py`: planner dùng chung, chia các nhóm liên tiếp.
- `capcut/cover.py`: thumbnail bìa CPU từ ảnh đầu của part.
- `capcut/exporter.py`: thêm targets split, thông báo lỗi part và ghi bìa trong staging; không viết lại engine timeline.
- `capcut/state.py`: lưu part count.
- `ui/capcut_plan.py`: model preview ảo.
- `ui/capcut_cards.py`, `ui/capcut_page.py`: mode thứ ba, count/preview live, khóa trạng thái và chốt count trước worker.
- `ui/theme.py`: nền trong suốt có phạm vi riêng cho controls chia.
- `tests/test_capcut_split.py`, `tests/test_capcut_split_ui.py`, `tests/test_capcut_export.py`: tests mới và regression hai mode cũ với thumbnail được cho phép.
- `scripts/check_capcut_source.py`: capture và xuất mẫu split cô lập bằng media tổng hợp.

**READY FOR USER ACCEPTANCE ở source. Bìa mới còn cần người dùng đối chiếu trong CapCut thật.** Không kiểm chuyển giữa hai màn hình khác DPI hoặc nghe loa thực tế trong lượt này. Không dùng media/DB sản xuất, API, inference, build, tăng version, commit/push hoặc publish.
