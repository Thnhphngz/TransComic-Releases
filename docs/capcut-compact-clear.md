# CapCut — thẻ ba hàng, focus theo hàng và xóa toàn bộ

> Bổ sung hiện tại: [ba chế độ xuất, chia đều nhiều project và bìa riêng](capcut-split-projects.md). Báo cáo bên dưới ghi nhận đợt UI/clear trước đó.

18/10/2026 · source v1.1.0 · chưa phát hành.

## A. Bố cục mới

Thẻ thu gọn trên cửa sổ rộng còn ba hàng: tên/thống kê, hai đường dẫn, thanh thao tác. Với cùng chiều rộng 1.150 logical pixels, theme/font và nhóm mẫu 165 cặp, chiều cao giảm từ **156 xuống 114 logical pixels**, tiết kiệm **42 pixels (26,9%)**. Số đo lấy từ class trước sửa được lưu trong ZIP baseline, đối chiếu class mới; không ước lượng từ ảnh.

Mở rộng vẫn hiện bảng ngay trong thẻ, giữ nguyên accordion, Mở/Thu gọn tất cả, trạng thái theo ID, đổi thứ tự, sort và preview.

## B. Đường dẫn và thống kê

- Tên nhóm bên trái; thống kê căn phải cùng hàng khi đủ chỗ. Tên dài elide, không đẩy thống kê ra khỏi khung.
- Nhóm lỗi dùng trạng thái/màu cần kiểm tra, giữ đủ số cặp/file lỗi và thông tin lệch số lượng. Khi không đủ chiều ngang, thống kê xuống hàng và wrap thay vì bị cắt. Không suy đoán vị trí file thiếu.
- Ảnh/voice nằm cùng hàng theo tỷ lệ 40/60. Dưới ngưỡng 900 logical pixels của vùng đường dẫn, hai nhãn xếp dọc. Tooltip và copy đường dẫn đầy đủ được giữ nguyên; elide giữa khi dài.
- Thanh sort/Xem file/Sửa/↑/↓/Xóa vẫn dùng nút vừa nội dung, tự wrap khi hẹp. Không sửa sidebar hoặc bố cục trang khác.

## C. Viền chọn bảng

Nguyên nhân là Qt native item style vẽ focus frame quanh **ô hiện tại** khi delegate nhận `State_HasFocus`. CapCut vốn đã chọn cả hàng, nhưng ô ngày/duration vẫn có khung focus riêng.

Delegate riêng `RowDelegate` loại cờ focus khỏi phần vẽ từng ô, giữ nguyên selection. `CapcutTable` vẫn nhận focus và phím bình thường; khi dùng Tab/phím, nó vẽ một nét accent mảnh quanh **cả hàng**. Click chuột giữ highlight nền hàng, không có khung trắng quanh ô. Không sửa delegate/QSS chung của bảng dịch.

Ngày tạo hiển thị `18/10/2026 21:39:42`. Duration thống nhất `mm:ss.mmm`, ví dụ `00:08.875`. Chỉ làm tròn chuỗi DisplayRole; duration integer microseconds trong scan/snapshot và export không thay đổi.

## D. Xóa toàn bộ

Nút **Xóa toàn bộ** ngay cạnh **Thu gọn tất cả**, cảnh báo nhẹ, vô hiệu hóa khi trống hoặc đang export. Xóa từng thẻ vẫn giữ nguyên.

Hộp xác nhận nêu đúng số nhóm và phạm vi workspace. **Hủy** là nút mặc định, Enter chọn Hủy, Esc đóng an toàn. Chỉ nút **Xóa toàn bộ nhóm** trong dialog mới xác nhận.

Sau xác nhận:

1. Lưu danh sách nhóm rỗng bằng `GroupManager.clear()`, giữ mode, tên project và output. Save lỗi thì khôi phục danh sách trong RAM và giữ nguyên UI/scan hiện tại.
2. Dừng audio, đưa shared player về page, xóa selection/preview/filter/model của các thẻ; thu hồi cache và bỏ qua thumbnail đang tải của dữ liệu cũ.
3. Đóng/xóa các card khỏi workspace, thống kê về 0; có thể thêm nhóm mới ngay. Không gọi thao tác xóa media/project trên filesystem.
4. Trong lúc scan, đặt cancellation và tăng generation ID. Worker cũ có thể kết thúc an toàn ở nền, nhưng cả completion **và scan progress** cũ bị loại. Worker vẫn được theo dõi bởi cơ chế thoát ứng dụng hiện có; kết quả muộn không hồi sinh nhóm hoặc ghi đè trạng thái lượt mới.
5. Trong lúc export, nút và handler đều chặn xóa; chỉ mở lại khi worker xuất đã hoàn tất hoặc dừng. Không thay snapshot hoặc logic worker export.

Kiểm tra đóng/mở lại MainWindow với Store đã mở lại từ đĩa: nhóm đã xóa không phục hồi. Hash ảnh, voice và project được xuất thật từ fixtures trước khi clear giữ nguyên sau clear.

## E. Test và regression

- **183 PASS**, 170,82 giây ở lượt regression tuần tự cuối: CapCut mới/cũ, engine export, UI chung, theme, toolbar, vòng đời cửa sổ và các regression liên quan.
- **50 PASS**, 39,01 giây ở lượt GUI cuối với scale 150%, gồm toàn bộ test CapCut UI/accordion/dialog nhập và 22 case compact/clear mới.
- Các case mới: nhóm 1/10/20; bố cục rộng/hẹp và đường dẫn/tên dài; trạng thái lỗi; chọn chuột/Tab/mũi tên; định dạng ngày/duration; Hủy/Enter/Esc; clear 1/20 nhóm với project đã xuất; player/filter/cache cleanup; lưu lỗi; scan cố tình bỏ qua cancellation và trả về muộn; export hoàn tất hoặc hủy; restart; thêm nhóm mới sau clear.
- Các test thumbnail, ảnh lớn, audio dispatch/stop, accordion, thứ tự và bảng 20.000 hàng mô phỏng trước đó vẫn chạy.
- Export regression giữ đủ cặp, đúng thứ tự nhóm/file, cấu trúc MAU/video tracks, audio gap = 0, direct paths, không copy/sửa media, snapshot validation, cancel/atomic publish và chống ghi đè.
- SHA-256 exporter, matcher, ZIP template, provenance và pyproject trước/sau khớp. AST hàm `start_export` khớp baseline.

Bằng chứng: [regression cuối 100%](../artifacts/capcut-compact-clear/regression-final-100.xml), [GUI cuối 150%](../artifacts/capcut-compact-clear/gui-final-150.xml), [số đo chiều cao](../artifacts/capcut-compact-clear/card-height-comparison.json), [tổng hợp kiểm chứng](../artifacts/capcut-compact-clear/verification.json).

Lượt regression đầu khi chạy song song có 181 PASS và một FAIL ở `test_period_manual_replace_undo_redo_reload`: nội dung đã lưu đúng nhưng assert count sau 120ms chưa cập nhật. Chạy riêng test đó PASS và lượt regression tuần tự cuối 183 PASS. Chưa xác lập nguyên nhân timing bằng profiling; không sửa logic editor/badge ngoài phạm vi nhiệm vụ. XML của lượt đầu và kiểm tra lại được giữ lại.

## F. Theme và screenshot

Qt software/offscreen trên Windows, scale 1 và 1,5; không thay DPI hệ thống. Đã kiểm Light/Dark, cửa sổ 950×620 và 1400×1000 logical pixels, long paths/names, 1/10/20 nhóm, vị trí/click/hover và xác nhận Hủy.

| Theme / scale | Thẻ gọn | Focus chuột | Focus bàn phím | Cửa sổ hẹp | Xác nhận |
|---|---|---|---|---|---|
| Light 100% | [Ảnh](../artifacts/capcut-compact-clear/light-100-collapsed.png) | [Ảnh](../artifacts/capcut-compact-clear/light-100-mouse-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/light-100-keyboard-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/light-100-narrow.png) | [Ảnh](../artifacts/capcut-compact-clear/light-100-clear-confirmation.png) |
| Dark 100% | [Ảnh](../artifacts/capcut-compact-clear/dark-100-collapsed.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-100-mouse-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-100-keyboard-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-100-narrow.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-100-clear-confirmation.png) |
| Light 150% | [Ảnh](../artifacts/capcut-compact-clear/light-150-collapsed.png) | [Ảnh](../artifacts/capcut-compact-clear/light-150-mouse-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/light-150-keyboard-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/light-150-narrow.png) | [Ảnh](../artifacts/capcut-compact-clear/light-150-clear-confirmation.png) |
| Dark 150% | [Ảnh](../artifacts/capcut-compact-clear/dark-150-collapsed.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-150-mouse-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-150-keyboard-focus.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-150-narrow.png) | [Ảnh](../artifacts/capcut-compact-clear/dark-150-clear-confirmation.png) |

## G. Source thay đổi

| File | Mục đích |
|---|---|
| `transcomic/ui/capcut_cards.py` | Thẻ ba hàng, responsive tên/thống kê và đường dẫn, nút clear trên toolbar |
| `transcomic/ui/capcut_media.py` | Delegate/focus riêng CapCut, định dạng DisplayRole ngày/duration |
| `transcomic/ui/capcut_page.py` | Xác nhận/cleanup clear, khóa khi export, fence scan progress/completion |
| `transcomic/capcut/state.py` | Clear danh sách có rollback khi save lỗi, giữ các tùy chọn |
| `transcomic/ui/theme.py` | Chỉ thêm nền trong suốt cho widget tiêu đề trong card CapCut |
| `tests/test_capcut_compact_clear.py` | Regression mới cho layout/focus/clear/race/persistence/an toàn nguồn |
| `scripts/check_capcut_source.py` | Capture focus chuột/phím, dialog xác nhận và số đo card bằng media tổng hợp |
| Tài liệu này và liên kết hướng dẫn một trang | Báo cáo/hướng dẫn cập nhật |

## H. Hạn chế

Scale được kiểm bằng Qt software/offscreen; chưa xác minh kéo cửa sổ giữa hai màn hình có DPI khác nhau. Player được kiểm dispatch/stop/lifetime với mock play, không kiểm nghe loa ở lượt này. Không đọc media riêng hoặc database sản xuất. Engine CapCut đã được người dùng nghiệm thu trước đó, không mở lại CapCut/GPU.

Không build/Installer, đổi driver, Sandbox/CUDA/GPU stress, API, inference, commit/push/publish hoặc tăng version. Giữ source v1.1.0 và các thay đổi có sẵn của nhiệm vụ trước.

## I. Trạng thái

**READY FOR USER ACCEPTANCE — chưa phát hành.**
