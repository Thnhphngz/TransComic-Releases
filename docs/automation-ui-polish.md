# Automation UI/UX final polish & TTS consistency

## A. Hành vi TTS

Nguyên nhân: `TtsPage.__init__` gọi `TtsStore.draft()` để khôi phục bản nháp thủ công gần nhất. Job Automation dùng `TtsStore` chung nhưng được tạo thành run riêng và đưa vào history. Vì vậy batch `5-6_EN` và history `1-2`, `3-4` đang phản ánh hai ngữ cảnh khác nhau.

Đã sửa trong UI, không xóa/reset draft hoặc chuyển run_id sang job khác:

- Khi workset running/stopping, workspace thủ công được ẩn; card chỉ rõ bộ Automation, **1 luồng / 1 nhóm mỗi lượt**, và hướng dẫn xem history.
- History job thuộc Automation có nhãn **Automation · Chỉ đọc**. Xem câu/nghe audio vẫn có; các lệnh retry/cancel/relink/delete không còn được gợi ý như tác vụ thủ công.
- Sau dừng/kết thúc, bản nháp được hiển thị lại. Chú thích riêng phân biệt bản nháp thủ công đã lưu với job Automation, kể cả lần mở tab đầu tiên sau khi hoàn tất.
- Không tạo thêm batch từ tài liệu lịch sử, không xóa file/audio/history và không thay đổi owner/checkpoint.

## B. UI/UX đã chỉnh

- Giữ sidebar, cấu trúc hai cột và engine hiện có.
- Hàng công cụ bốn nút cao 36 logical px: Thêm tài liệu, Bắt đầu/Tiếp tục, Dừng an toàn, Kiểm tra lại.
- Không còn panel nhật ký hoặc khoảng trống giữ chỗ; bảng chương nhận diện tích đó.
- Tiến độ tổng thể gồm ba card, màu riêng Dịch/Kokoro/CapCut, số lượng thật từng stage và vòng hoàn tất theo **nhóm**, không lấy trung bình giả. Cửa sổ hẹp thu gọn vòng tròn, vẫn giữ số nhóm trong mô tả.
- Bảng dùng delegate theo theme, checkbox, tiến độ ba bước và badge trạng thái; loại native focus/hover ở cell. Click và keyboard vẫn dùng stable group ID. Focus keyboard là nét đồng mảnh màu accent, không có viền native xanh/trắng; hover chỉ trên nút glass.
- Preview part cũng bỏ native focus/hover, vẫn sửa tên bằng editor hiện có.
- Số part và preview chỉ hiện khi mode split; separate/merged không để lại control xám hoặc hàng trống.
- Cấu hình active/stopping bị khóa và opacity 0.8 để đọc được. Sau dừng, các option được phép sửa mở lại; các giá trị bất biến của bộ đã chạy giữ chính sách cũ.
- Trạng thái Đang xuất được suy ra từ part checkpoint đang exporting để hiển thị; không ghi lại hoặc đổi state machine backend.

## C. Đã bỏ khỏi UI

- Nhật ký theo nhóm và nút mở nhật ký.
- Dropdown Model Kokoro, Runtime.
- Nút xuất HTML/JSON thủ công.
- Số part và preview trong hai mode không chia.

`variant` thực sự chọn Standard/Light, và `device` vẫn ảnh hưởng runtime nội bộ. Chúng được **ẩn khỏi UI và giữ nguyên giá trị**, không bị coi là logic thừa rồi xóa. Auto/GPU/CPU fallback, fingerprint runtime, retry, checkpoint, recovery và báo cáo tự động không thay đổi. Source xác nhận Kokoro adapter `workers=1`, coordinator chỉ có một TTS future; UI hiển thị đúng 1 luồng.

## D. Kiểm thử và ảnh

| Phạm vi | Kết quả | Bằng chứng |
| --- | --- | --- |
| Automation UI + TTS GUI/V4/V4.1/redesign/hotfix liên quan | **58 PASS / 0 FAIL** | `artifacts/automation-polish-regression.log/xml` |
| Toàn bộ Automation GUI ở DPR 1.5 | **14 PASS / 0 FAIL** | `artifacts/automation-polish-gui-150.log/xml` |
| Chốt control/preview/context và ảnh DPR 1.0 | **5 PASS / 0 FAIL** | `artifacts/automation-polish-final-100.log/xml` |
| Chốt control/preview/context và ảnh DPR 1.5 | **5 PASS / 0 FAIL** | `artifacts/automation-polish-final-150.log/xml` |
| Bổ sung chú thích manual draft sau hoàn tất | **1 PASS / 0 FAIL** | `artifacts/automation-polish-tts-context-final.log` |

Các lượt có ca trùng, không cộng thành tổng số ca duy nhất. Không chạy lại full offline vì thay đổi nằm trong UI và bộ focused liên quan đã PASS.

Đã kiểm tra: mock pipeline sáu nhóm → ba project thật qua MAU, Start/Stop lock, đồng bộ tab, Undo, filter/stable ID, click/keyboard/drop, checkbox, hover pixel không đổi ở cell, focus state bị loại, mode part, giữ nguyên variant/device, bản nháp TTS cũ trong lúc synthesize đang chờ, history read-only và khôi phục draft sau hoàn tất. Resize 900×580, 1200×780, 1640×940; Light/Dark; DPR 1.0/1.5. Không dùng dữ liệu truyện sản xuất hoặc API thật.

Ảnh từ cửa sổ Qt thật với fixture và pipeline mock đã hoàn tất, không phải ảnh thiết kế:

| Scale | Light | Dark |
| --- | --- | --- |
| 100% | [Automation](../artifacts/automation-polish/gui-100/polish-light.png) | [Automation](../artifacts/automation-polish/gui-100/polish-dark.png) |
| 150% | [Automation](../artifacts/automation-polish/gui-150/polish-light.png) | [Automation](../artifacts/automation-polish/gui-150/polish-dark.png) |

[TTS trong lúc Automation đang xử lý](../artifacts/automation-polish/gui-100/tts-automation-context.png). DPR và kích thước logical của ảnh lưu trong `polish-dpr.json` từng thư mục.

## E. Giới hạn

Phong cách Qt được thực hiện bằng card, gradient glass, badge và delegate; không mô phỏng blur/acrylic của ảnh tham khảo theo từng pixel. Ở cửa sổ hẹp, bảng/cuộn cấu hình và vòng tiến độ thu gọn theo diện tích. Kiểm thử lần này là source với mock translation và PCM tổng hợp; không gọi Kira/Gemini thật, không chạy inference GPU, Sandbox, build hay Installer.

Chỉ thay đổi `ui/automation_page.py`, thêm `ui/automation_widgets.py`, sửa UI `tts_page.py`/`tts_history.py`, tests và tài liệu trong lượt này. Tám file worker Kokoro giữ nguyên từng byte; version vẫn 1.2.0. Không commit/push/release.

## F. Trạng thái

**READY FOR USER ACCEPTANCE**
