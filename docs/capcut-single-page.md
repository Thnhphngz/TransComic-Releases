# CapCut — một trang, thẻ nhóm mở rộng

> Cập nhật mới nhất: [thẻ ba hàng, focus theo hàng và Xóa toàn bộ](capcut-compact-clear.md). Báo cáo dưới đây ghi nhận lần chuyển sang một trang; engine xuất giữ nguyên.

Source v1.1.0 · 18/10/2026 · **READY FOR USER ACCEPTANCE**.

Người dùng xác nhận đã mở project xuất trong CapCut thật và hoạt động tốt. Đây là nghiệm thu engine do người dùng cung cấp; nhiệm vụ này không khởi chạy lại CapCut/GPU.

## A. Thiết kế một trang

Đã bỏ hoàn toàn hai tab Danh sách nhóm/Chi tiết. Trang gồm thanh công cụ và tổng thống kê, danh sách nhóm cuộn riêng, cài đặt xuất cố định bên dưới. Thêm nhóm vẫn dùng dialog nhập nhiều cặp hiện có. Các nút Kiểm tra tất cả, Mở tất cả và Thu gọn tất cả ở đầu trang.

Cài đặt riêng/gộp, tên tổng, thư mục đầu ra, nút Xuất/Hủy/Mở thư mục xuất và tiến độ nằm ngoài vùng cuộn nhóm. Không phải cuộn qua hết các bảng để xuất.

## B. Thẻ nhóm

- Tên kèm thứ tự; cả đường dẫn ảnh và voice luôn hiện khi thu gọn. Đường dẫn dài rút gọn giữa, tooltip đầy đủ; có thể chọn chữ hoặc nhấn chuột phải để copy toàn bộ đường dẫn.
- Thống kê tổng file ảnh/voice, cặp hợp lệ, số file lỗi, tổng mục cần kiểm tra. Màu trạng thái dùng palette Light/Dark hiện có.
- Khi lệch số lượng, ghi rõ thiếu ảnh/voice và **chưa xác định vị trí**; không thay validation hoặc đoán file bị thiếu.
- Combobox sắp ảnh, Xem file/Thu gọn, Sửa, ↑, ↓, Xóa đặt gọn, tự xuống dòng khi hẹp. Chỉ nhóm thực sự cần kiểm tra có nút Xem lỗi.
- Xóa chỉ bỏ nhóm khỏi workspace, giải phóng preview/cache liên quan; không xóa media hay project đã xuất.

## C. Chi tiết mở rộng

Mũi tên hoặc Xem file mở bảng ngay dưới thẻ, không chuyển tab hay mở cửa sổ khác. Mặc định mọi nhóm đóng; mở một nhóm đóng nhóm trước. Mở tất cả bật chế độ nhiều nhóm mở, sau đó vẫn đóng/mở riêng từng nhóm. Thu gọn tất cả trở về chế độ mở một nhóm.

Trạng thái gắn với ID ổn định, giữ qua đổi thứ tự, sắp ảnh, sửa nhóm và chuyển trang trong phiên. Đổi thứ tự không quét lại và không sửa thứ tự file trong scan. Mở/đóng không quét lại thư mục.

Bảng ảo giữ đủ bảy cột: STT/nhóm, thumbnail thật, tên ảnh, voice, ngày tạo, duration và trạng thái. Bảng cao 250 logical pixels, cuộn nội bộ; không cắt số hàng. Mỗi nhóm có tìm tên/STT, lọc lỗi và preview ảnh. Xem lỗi mở đúng nhóm, xóa truy vấn cũ và bật bộ lọc lỗi.

Nghe voice chỉ xảy ra khi nhấn nút. Toàn trang dùng một player; chọn hàng/nhóm khác, đóng chi tiết, chuyển trang, xóa nhóm hoặc đóng ứng dụng sẽ dừng và giải phóng nguồn phát. Player được đưa về page trước khi thẻ bị xóa.

## D. Hiệu năng và kiểm thử

- Hai worker thumbnail dùng chung toàn trang, không tạo worker/cache theo nhóm. LRU ảnh nhỏ tối đa 128; preview lớn tối đa 2; tối đa 32 request đang chờ mỗi dịch vụ.
- Chỉ yêu cầu thumbnail khi hàng giao với cả viewport bảng **và viewport danh sách ngoài**. Mở tất cả không nạp thumbnail nhóm nằm ngoài màn hình.
- Bảng/model tạo khi mở lần đầu và tái sử dụng. Không tạo widget theo từng file, không preload ảnh full-resolution, không có timer mới theo nhóm.
- Thử 10 × 184, 20 × 184 và 20 × 1.000 hàng bằng model fixtures tổng hợp; mỗi nhóm dùng file mẫu nhỏ. Đây là kiểm thử ảo hóa tới **20.000 hàng**, không phải benchmark quét 20.000 file vật lý. Test 3.000 hàng tìm kiếm/cuộn cũ cũng giữ nguyên.
- Kiểm tra mở/đóng lặp lại, cuộn tới nhóm cuối và hàng cuối, search/filter, worker không tăng, cache giới hạn, shutdown kết thúc worker.
- Regression liên quan: **161 PASS**, 129,10 giây, gồm UI chung, theme/layout, vòng đời cửa sổ và toàn bộ bộ CapCut hiện có.
- GUI cuối sau điều chỉnh icon và kiểm tra đóng cửa sổ thật: **28 PASS ở 100%**, 22,62 giây; **28 PASS ở 150%**, 24,76 giây.

Bằng chứng: [regression 100%](../artifacts/capcut-single-page/regression-100.xml), [GUI cuối 100%](../artifacts/capcut-single-page/accordion-final-100.xml), [GUI cuối 150%](../artifacts/capcut-single-page/accordion-final-150.xml). Các XML `focused-100.xml` và `gui-150.xml` đầu tiên ghi một assert phát hiện nút mũi tên thấp hơn 28px; đã sửa thành 32px và các lượt cuối PASS. Test đóng cửa sổ bổ sung ban đầu đọc QObject sau khi Windows/Qt đã xóa; fixture cuối kiểm tra lifetime đúng, không bỏ kiểm tra đóng ứng dụng.

## E. Theme và ảnh

Chụp từ MainWindow thật bằng Qt offscreen/software, font Segoe UI có sẵn trên Windows. Scale Qt 1 và 1,5; không thay DPI hệ thống. Kiểm tra Light/Dark, cửa sổ 950×620 và 1400×1000 logical pixels, tên/đường dẫn rất dài, click/hover, thanh thao tác xuống dòng và dialog 20 cặp. Không sửa sidebar.

| Theme / scale | Thu gọn | Mở nhóm | Cửa sổ hẹp |
|---|---|---|---|
| Light 100% | [Ảnh](../artifacts/capcut-single-page/light-100-collapsed.png) | [Ảnh](../artifacts/capcut-single-page/light-100-expanded.png) | [Ảnh](../artifacts/capcut-single-page/light-100-narrow.png) |
| Dark 100% | [Ảnh](../artifacts/capcut-single-page/dark-100-collapsed.png) | [Ảnh](../artifacts/capcut-single-page/dark-100-expanded.png) | [Ảnh](../artifacts/capcut-single-page/dark-100-narrow.png) |
| Light 150% | [Ảnh](../artifacts/capcut-single-page/light-150-collapsed.png) | [Ảnh](../artifacts/capcut-single-page/light-150-expanded.png) | [Ảnh](../artifacts/capcut-single-page/light-150-narrow.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-single-page/dark-150-collapsed.png) | [Ảnh](../artifacts/capcut-single-page/dark-150-expanded.png) | [Ảnh](../artifacts/capcut-single-page/dark-150-narrow.png) |

Ảnh Mở tất cả và dialog nhập nhiều cặp nằm trong cùng thư mục bằng chứng.

## F. Regression xuất project

Các test fixture xuất một nhóm, nhiều project và gộp nhóm đều PASS: đúng thứ tự nhóm/file, giữ đủ cặp, hai video track/template MAU, timeline/duration, audio gap = 0, direct source paths, không copy media, fingerprint nguồn, snapshot validation, hủy/atomic publish và chống ghi đè.

SHA-256 trước/sau khớp toàn bộ exporter, matcher, state, ZIP template, provenance và pyproject. Không sửa các file này. Media dùng kiểm thử là tổng hợp trong thư mục cô lập; không mở database sản xuất hoặc dùng media riêng.

## G. Source thay đổi

| File | Mục đích |
|---|---|
| `transcomic/ui/capcut_page.py` | Điều phối một trang, giữ card theo ID, trạng thái mở, player dùng chung, quản lý vòng đời preview |
| `transcomic/ui/capcut_cards.py` | Thanh công cụ/cài đặt, card, đường dẫn elide/copy, action flow và bảng chi tiết inline |
| `transcomic/ui/capcut_media.py` | Cho model dùng dịch vụ thumbnail chung, gate vùng nhìn thấy, giới hạn pending và thu hồi cache khi xóa nhóm |
| `transcomic/ui/theme.py` | Bỏ selector tab CapCut cũ; selector có phạm vi cho chữ hàng chọn và màu trạng thái CapCut |
| `tests/test_capcut_ui.py`, `tests/test_capcut_import.py` | Chuyển regression từ hai tab sang thẻ inline, cleanup theo lifetime Qt |
| `tests/test_capcut_single_page.py` | Regression chức năng, click/geometry, dữ liệu lớn, cache/worker/player và đóng cửa sổ |
| `scripts/check_capcut_source.py` | Capture một trang, mở/đóng nhóm, cửa sổ hẹp và dialog bằng dữ liệu tổng hợp |
| Các tài liệu CapCut | Hướng dẫn mới và liên kết từ báo cáo lịch sử |

## H. Giới hạn còn lại

Không phát hiện lỗi còn mở trong các gate trên. Scale 100%/150% được kiểm bằng Qt software/offscreen; chưa kiểm thao tác kéo cửa sổ qua hai màn hình có DPI khác nhau. Audio được kiểm đường dispatch/stop và lifetime player với mock play, chưa nghiệm thu nghe bằng loa thực tế ở lượt này. Kiểm thử hiệu năng là model fixtures, không cam kết tốc độ quét thư mục thực trên mọi ổ đĩa.

Không chạy CapCut/GPU/Sandbox/CUDA, API, inference, build/Installer hoặc release. Không tăng version, commit hay push. Những thay đổi đang có của các nhiệm vụ trước được giữ nguyên.

## I. Trạng thái

**READY FOR USER ACCEPTANCE — source v1.1.0, chưa phát hành.** Engine CapCut đã được người dùng nghiệm thu trước đó; giao diện một trang mới đã qua kiểm thử offline và sẵn sàng để người dùng đối chiếu.
