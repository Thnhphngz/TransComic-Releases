# TransComic — Liquid Glass V3

Ngày hoàn tất kiểm tra: 14/10/2026; yêu cầu nhận ngày 13/10/2026. Phạm vi là giao diện PySide6 Windows theo yêu cầu V3 mới nhất. Những thay đổi API/504/đóng ứng dụng của phiên trước được giữ tại thời điểm nhận V3; không tiếp tục chỉnh các subsystem đó.

## Khảo sát và cách triển khai

Git không có trong môi trường này nên không thể báo trạng thái Git chính xác. Đã lưu bản mã UI trước V3 tại `artifacts/liquid-glass-v3/baseline-ui` và SHA-256 của 20 file Python backend tại `backend-before.json`. Đối chiếu bằng `python scripts/liquid_glass_verify_scope.py`; xem [kết quả phạm vi](../artifacts/liquid-glass-v3/scope-verification.json).

Tái sử dụng `ui/glass.py` và bộ token `ui/theme.py`. Các phần thay đổi gồm `main.py`, `workspace_v2.py`, `documents_panel.py`, `controls.py`, `glass.py`, `theme.py`, `stage2.py`; không tạo hệ thống style thứ hai.

Tham khảo bề mặt kính, phản sáng, dropdown và chuyển ngày/đêm từ [Lucian UX/UI #001](https://lucianlabs.dev/uxui-prompt/#001), [#021](https://lucianlabs.dev/uxui-prompt/#021), [Liquid Glass dropdown](https://liquidglassdesign.com/gallery/liquid-glass-saas-dropdown-component) và [thư viện UI](https://liquidglassdesign.com/ui). Các thành phần được vẽ bằng Qt/QPainter từ bộ màu của ứng dụng, không sao chép asset/code web.

Đây là kính giả lập bằng gradient, highlight, rim và bóng inset nhẹ; không phải blur nội dung thật sau cửa sổ. Không có WebEngine, shader, animation lặp vô hạn, animation từng hàng hoặc nền kính riêng từng ô bảng. Hover chạy hữu hạn 130ms, chuyển sky 210ms; đọc cấu hình giảm chuyển động của Windows để bỏ animation khi cần.

## Báo cáo 23 mục

### Giao diện

1. **Nút đã chuyển:** điều hướng/sidebar, thu gọn, panel tài liệu, nhập file/thư mục, xuất đơn/hàng loạt, bắt đầu/tạm dừng/dừng, retry, cảnh báo, tìm/thay/copy, API/key/model, lịch sử/hàng đợi, Console, cài đặt và các nút dialog. Primary/secondary/danger/ghost/icon dùng cùng component; nút Qt tạo trong `QDialogButtonBox` được skin theo vai trò.

2. **Style còn lại:** các lệnh ứng dụng dùng hệ thống chung. Tool button nội bộ Qt dùng QSS cùng token. Thành phần chọn file/thư mục vẫn dùng cơ chế QFileDialog hiện có; không viết picker riêng hoặc thay cấu hình picker ở `app.py`. Viền/title bar hệ điều hành vẫn do Windows quản lý.

3. **Light:** nền ivory/cream, chữ nâu đậm, copper primary; có gradient trên/dưới, highlight mép trên và bóng nhẹ. Bảng nội dung vẫn phẳng, rõ chữ. [Ảnh toàn cửa sổ Light](../artifacts/liquid-glass-v3/after/1/full-False.png).

4. **Dark:** espresso/chocolate với copper sáng; chữ trên primary/chip đã chọn dùng nâu đậm để tăng tương phản. Chữ normal/disabled và các nút nguy hiểm có màu riêng. [Ảnh Dark](../artifacts/liquid-glass-v3/after/1/full-True.png).

5. **Nút chữ theme:** đã bỏ cả nút sidebar “Giao diện sáng/tối” lẫn nút chuyển theme trong Cài đặt. Chỉ còn một SkySwitch ở đáy sidebar.

6. **Day/Night:** mặt trời/mây ↔ mặt trăng/sao, click hoặc Space, lưu theme. Sidebar thu gọn vẫn chứa đủ switch 62×32px; lựa chọn chip không bị reset. [Ảnh sidebar thu gọn](../artifacts/liquid-glass-v3/after/1/collapsed-True.png).

7. **Dropdown:** control đóng có lớp phản sáng/bóng, mũi tên đồng bộ; popup dùng QListView và delegate vẽ màu/text/checkmark rõ. Chiều cao theo số item, tối đa 11 hàng và cuộn khi dài. Native mechanics, item model, keyboard selection và popup positioning được giữ. Wheel đóng không đổi giá trị; wheel popup cuộn; wheel Luồng vẫn tăng/giảm.

8. **EN không biến mất:** combo và popup vẫn có cả EN/ID, checkmark EN theo giá trị thật của combo, hover item khác không che EN. Chọn ID chuyển đúng document variant, không gọi API. [Popup Light](../artifacts/liquid-glass-v3/after/1/en-id-popup-False.png), [popup Dark](../artifacts/liquid-glass-v3/after/1/en-id-popup-True.png), [11 locale](../artifacts/liquid-glass-v3/after/1/locales-11-False.png).

### Thao tác

9. **Dấu X:** hit rect 32×32px dùng chung cho vẽ và kiểm tra tọa độ viewport. Ghi source instance lúc nhấn, chỉ bỏ khi thả đúng instance/vùng X; nhận sự kiện để không phát sinh click mở thẻ. Hỗ trợ cuộn, DPR, hover và tooltip. Test thật vị trí đầu/giữa/cuối danh sách 12 file.

10. **Nguồn/lịch sử:** gọi interface `remove_workspace_instances` hiện có. Giữ file nguồn, bản xuất, document snapshot, bản dịch và job trong lịch sử. File đã dịch/đang có job vẫn xác nhận; hủy giữ nguyên; bỏ file đang mở chuyển sang file còn lại. Không viết lại storage hoặc scheduler.

11. **Focus:** mouse click không giữ viền copper kiểu focus mặc định trên button/combo. Tab/Shift+Tab có indicator mảnh, vẫn dùng được bàn phím. Sidebar dùng nhóm chọn duy nhất; click lại trang đang mở vẫn giữ selected. Trạng thái selected của chip/file độc lập với focus.

12. **Thứ tự:** nguồn/provider/model/luồng → chip đích và “Đang xem” → bắt đầu/tạm dừng/dừng → tiến độ → bảng. Chip nằm trên action row, chiều cao strip giảm từ 55 xuống 42px; cửa sổ nhỏ dùng cuộn ngang.

13. **Khởi động mới:** target chips trống, không có số thứ tự, Bắt đầu disabled. Không đọc lựa chọn chip cũ để chọn lại và không ghi persistence mới cho chip. Lịch sử/run config vẫn giữ target/order đã dùng. Test hồi quy cũ về persistence được cập nhật theo yêu cầu mới, không xóa test.

14. **Cùng phiên:** chọn EN rồi ID hiện `1 EN`, `2 ID`; đổi file, nhập thêm, trang và theme giữ lựa chọn. Nguồn/provider/model/luồng/font/layout/theme giữ cơ chế lưu cũ. Không auto-start khi mở app hoặc đổi bản đang xem.

15. **Nhập/xuất và dialog:** toolbar dùng component chung. Dialog Qt có token cùng theme và nút xác nhận/hủy được vẽ chung; xử lý cache màu label của nút do Qt tạo, kiểm tra cả grab trực tiếp và grab từ dialog cha. [Dialog Light](../artifacts/liquid-glass-v3/after/1/export-dialog-light.png), [dialog Dark](../artifacts/liquid-glass-v3/after/1/export-dialog-dark.png). Native frame/picker mechanics được giữ.

16. **Cột số:** dùng QFontMetrics của font/bold header để đo số ordinal lớn nhất của toàn document, dấu trạng thái rộng nhất, khoảng trắng và 12px padding. Cache theo document/font/ordinal; lọc dòng không đổi width, không đo lại mỗi hàng. Font 12/22px và 9/99/999/9999 dòng được test; checkbox vẫn cột riêng 38px. [9999 dòng, font 22](../artifacts/liquid-glass-v3/after/1/gutter-9999-font-22.png).

### Kiểm thử

17. **Kết quả:** xem phần “Kết quả cuối” bên dưới và XML/log liên kết; không tính các lượt chạy bị ngắt/crash thành test đạt. Các test mới dùng Qt thật, HTTP mock hoặc cấm HTTP; không xóa test cũ.

18. **Windows/DPI:** chạy chính `run_transcomic.py`, platform `windows`, SQLite/LOCALAPPDATA tạm. Windows giữ mức hệ thống 125%; `QT_SCALE_FACTOR=0.8/1/1.2` cho Qt DPR đo được **1.0/1.25/1.5**. Mỗi mức kiểm tra Light/Dark, 900×580, 1200×720, maximized, sidebar/panel thu gọn, popup EN/ID và 11 locale. [100%](../artifacts/liquid-glass-v3/after/0.8/report.json), [125%](../artifacts/liquid-glass-v3/after/1/report.json), [150%](../artifacts/liquid-glass-v3/after/1.2/report.json).

   Cả ba DPR còn click X bằng GUI Windows thật: hủy giữ nguyên, bỏ ba file đúng vị trí và kiểm tra nguồn/lịch sử còn nguyên. SHA-256 ba DOCX người dùng không đổi trước/sau smoke; các request count đều bằng 0.

19. **Ảnh trước/sau:** `artifacts/liquid-glass-v3/before/0.8` lấy từ snapshot mã UI trước V3, chạy native entry point với cùng ba file. `after/0.8`, `after/1`, `after/1.2` là GUI Qt thật sau sửa; không dùng mockup. [Trước Light](../artifacts/liquid-glass-v3/before/0.8/full-False.png), [sau Light](../artifacts/liquid-glass-v3/after/0.8/full-False.png); [trước Dark](../artifacts/liquid-glass-v3/before/0.8/full-True.png), [sau Dark](../artifacts/liquid-glass-v3/after/0.8/full-True.png).

20. **Regression:** ghi rõ các lượt ban đầu và lượt cuối bên dưới. Kiểm thử đã phát hiện cache màu dialog, selected sidebar khi click lại và vòng đời filter; các phần này được sửa trong UI. Những lỗi thời gian đóng/tạm dừng của phiên backend trước không được sửa ở V3. Không suy luận từ screenshot rằng backend đã được xử lý.

21. **Backend:** SHA-256 của cả 20 file `transcomic/*.py` không đổi so với đầu V3. Không sửa endpoint/client/timeout/retry/rate limiter/prompt/validator/schema/concurrency. Chỉ gọi interface backend hiện có cho workspace và lịch sử.

22. **API thật:** **0** Kira, **0** Gemini. Smoke chặn cả `httpx.Client.send` và `AsyncClient.send`, dùng database tạm không có key; chỉ import Word và chèn sample cục bộ để kiểm tra UI. Các URL POST trong log pytest là request qua MockTransport, không phải lưu lượng thật.

23. **EXE:** không chạy PyInstaller, không build EXE/installer, không thêm updater.

## Kết quả cuối

Sau sửa vòng đời UI, chạy hai lượt toàn bộ liên tiếp, cùng phiên bản mã:

- Lượt thứ nhất: **439 test: 438 đạt, 0 thất bại, 1 bỏ qua**, trong **154,71 giây**. [Log](../artifacts/liquid-glass-v3/regression-stability-1.log), [XML](../artifacts/liquid-glass-v3/regression-stability-1.xml).
- Lượt thứ hai: **439 test: 437 đạt, 1 thất bại, 1 bỏ qua**, trong **187,45 giây**. Lỗi duy nhất là `test_cancel_and_safe_exit_do_not_resend_inflight`: cửa sổ chưa đóng trong thời hạn kiểm thử 900ms. [Log hồi quy cuối](../artifacts/liquid-glass-v3/regression.log), [XML toàn bộ](../artifacts/liquid-glass-v3/regression.xml).

Cả hai lượt không tái hiện native crash Qt. **22/22 GUI tests V3 mới đạt** ở cả hai lượt; [XML GUI của lượt cuối](../artifacts/liquid-glass-v3/gui-tests.xml). Nhóm retry/tìm/thay **26/26 đạt** khi chạy riêng. Không kết luận toàn bộ hồi quy xanh vì lượt cuối còn lỗi Safe Exit.

Test bỏ qua là `test_actual_docx_snapshot_context_export_unchanged_original`: ledger giới hạn thử tài liệu của đợt trước đã cạn. Không reset ledger hoặc sửa điều kiện này để chạy thêm.

Lượt hồi quy ban đầu hoàn tất: **433 đạt, 1 thất bại, 1 bỏ qua** trong 747,68 giây, [log](../artifacts/liquid-glass-v3/regression-initial.log), [XML](../artifacts/liquid-glass-v3/regression-initial.xml). Lỗi ở ca pause: số request mock tăng 3→4 trong khoảng chờ; chạy riêng ca này đạt. Safe Exit với timeout test 900ms thất bại trong kiểm tra riêng **cả UI trước V3**, [XML baseline](../artifacts/liquid-glass-v3/baseline-lifecycle.xml).

Hai lượt sau đó gặp native access violation trong `QListWidget.clear()` khi tìm/thay sau nhiều cửa sổ kiểm thử: [log thứ nhất](../artifacts/liquid-glass-v3/regression-crash.log), [log thứ hai](../artifacts/liquid-glass-v3/regression-crash-2.log). Đã chuyển skin sang **một QObject filter chung thuộc QApplication**, không giữ strong reference tới cửa sổ; cài combo view sau khi widget khởi tạo, không thay view trong `Polish`; focus chỉ cập nhật trạng thái/vẽ, không repolish ngay trong callback. Theo [Qt QComboBox](https://doc.qt.io/qt-6/qcombobox.html#setView), combo nhận ownership của view; việc thay view trong vòng khởi tạo là rủi ro vòng đời được loại bỏ. Stack crash không đủ để chứng minh nguyên nhân duy nhất. Thêm ca lặp focus/popup/theme và tìm kiếm để kiểm tra đường đi này.

Hai lượt cuối không tái hiện crash hoặc lỗi pause. Ca Safe Exit 900ms đạt ở lượt thứ nhất nhưng thất bại ở lượt thứ hai; nó cũng từng không đạt với snapshot UI trước V3. Ghi nhận đây là lỗi thời gian đóng cửa sổ cần theo dõi ở đợt riêng; chưa khẳng định nguyên nhân duy nhất. Không sửa backend, không nới thời gian chờ của test để làm xanh kết quả.

## Chạy lại

```powershell
python run_transcomic.py
python -m pytest -q
python scripts/liquid_glass_verify_scope.py
$env:QT_SCALE_FACTOR='1'
python scripts/liquid_glass_gui_smoke.py
```

Smoke dùng các file `15-16.docx`, `17-18.docx`, `19-20.docx` trong workspace để kiểm tra nhập và hiển thị, không dịch thật hoặc xuất đè. Bản sample EN/ID trong ảnh không phải kết quả dịch API. Có thể dùng `0.8` và `1.2` để lặp các DPR đã ghi; script từ chối platform khác Windows.
