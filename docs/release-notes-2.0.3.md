# TransComic 2.0.3

- Cải thiện hiệu năng, tiến độ và độ ổn định khi dịch nhiều tài liệu; Start không cần chọn trước một file.
- Giữ cơ chế tự phục hồi lỗi tạm thời Kira/DeepSeek và checkpoint của dòng đã dịch.
- DeepSeek Automation mới dùng cửa sổ tối đa 10 file, hoàn thành một file sẽ bổ sung file kế tiếp; workflow cũ giữ policy đã lưu.
- Kira Automation tiếp tục ưu tiên nhóm 10 file với ngưỡng 9/10.
- Sao lưu database dịch và TTS trước khi nâng constraint retry attempt; dừng migration nếu backup không đạt kiểm tra.
- Giữ nguyên Kokoro TTS, exporter CapCut MAU và các resource hiện có.

Lỗi key, model hoặc số dư vẫn cần xử lý theo phản hồi nhà cung cấp. Không bảo đảm API luôn thành công hoặc không gặp lỗi.

Trạng thái nghiệm thu và phát hành được ghi trong báo cáo đi kèm; release notes này chưa xác nhận đã publish.
