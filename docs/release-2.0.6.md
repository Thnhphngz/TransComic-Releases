# TransComic v2.0.6 — Quét ảnh song song với 10 worker

- Quét tối đa 10 thư mục ảnh đồng thời. Các lượt kéo thả dùng chung hàng đợi và thư mục tiếp theo bắt đầu ngay khi có worker rảnh.
- Theo dõi tiến độ theo từng dòng và hủy riêng một thư mục đang quét hoặc đang chờ.
- Tiếp tục thả thư mục trực tiếp vào bảng Tự động hóa. Ứng dụng tự ghép một DOCX, cho chọn khi có nhiều DOCX và chờ tài liệu khi thư mục chỉ có ảnh. Bạn vẫn có thể nhập Word trước rồi thả thư mục ảnh vào dòng.
- Khi xóa một bộ Tự động hóa, tab Dịch gỡ các tài liệu do riêng bộ đó đưa vào. Tài liệu mở thủ công và tài liệu dùng chung vẫn hiện. File nguồn, bản dịch đã lưu và lịch sử được giữ.
- DeepSeek dừng và báo cần kiểm tra khi phản hồi có cấu trúc mâu thuẫn. Với các lỗi tạm thời, mỗi lô dùng tối đa 10 lần gửi, tính cả lần đầu.
