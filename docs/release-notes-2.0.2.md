# TransComic v2.0.2 — Automation Reliability & CapCut Workflow Improvements

- Cho phép yêu cầu dịch lại an toàn từ tab Dịch trong khi Automation hoạt động, giữ một scheduler, chống gửi trùng và lưu yêu cầu vào checkpoint.
- Sửa cách hiển thị lựa chọn trong dropdown xuất tài liệu bằng delegate Liquid Glass, hỗ trợ Light/Dark.
- Đối chiếu WAV/project để hiển thị đúng bước Kokoro/CapCut sau Safe Stop/Resume và tái sử dụng kết quả hợp lệ.
- Kéo thả trực tiếp một thư mục ảnh hoặc audio vào đúng ô của từng cặp trong hộp thoại CapCut.
- Tự thêm một cặp thư mục trống dự phòng, cuộn vừa đủ và giữ focus; không quét media khi chỉ nhập đường dẫn.
- Workset Automation mới bắt đầu với tên project trống, yêu cầu tên hợp lệ; workset đã lưu giữ tên riêng khi mở lại hoặc Resume.
- Bảo toàn mapping, các chế độ chia/gộp project, WAV và project đã xuất; kết quả thay đổi tiếp tục dùng cơ chế phiên bản hiện có.

Đã kiểm thử API Kira bằng 3 dòng tổng hợp, 2 request thực tế và 1 worker. Không cố gây lỗi dịch vụ; các trường hợp 429/504/JSON lỗi được kiểm thử bằng mock.

Nâng cấp giữ nguyên dữ liệu ứng dụng. Hãy dừng tác vụ đang chạy và đóng TransComic trước khi cài bản cập nhật.
