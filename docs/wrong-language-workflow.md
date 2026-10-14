# Chặn bản dịch sai ngôn ngữ — 13/10/2026

## Báo cáo nghiệm thu 17 yêu cầu

1. **Nguyên nhân:** trước đây JSON/ID hợp lệ và nội dung không rỗng đủ để lưu `done`. `quality.language_evidence` chỉ tạo cảnh báo. Renderer còn thay dòng thiếu bằng nguồn, nên bản EN có thể chứa tiếng Việt dù mang tên `_EN` hoặc `_EN_INCOMPLETE`.

2. **Validator:** `transcomic/language_validator.py` kiểm tra offline với bốn kết luận `VALID`, `WRONG_LANGUAGE_CONFIRMED`, `SUSPECTED_WRONG_LANGUAGE`, `INSUFFICIENT_EVIDENCE`. Kết hợp NFC, token, so khớp bỏ dấu, độ tương đồng, chuỗi trùng liên tiếp, tỷ lệ các cụm sao chép, từ ngữ pháp Việt/Anh và dấu. Chỉ chặn bằng chứng mạnh; `VALID` không chứng nhận đúng ngữ nghĩa. Ưu tiên VI→EN/EN-CA; bản sao Việt rõ ràng cũng bị chặn ở các đích khác, kiểm định chuyên sâu các ngôn ngữ đó vẫn là cảnh báo.

3. **Lỗi thực tế:** tìm thấy các bản cũ tại `D:\word 50 cach\TransComic\English`. Đối chiếu nguồn/bản EN thật phát hiện đúng **dòng 67, 68, 69 của `17-18_EN.docx`**, toàn bộ nội dung sao chép nguồn. Hai bản cũ `15-16_EN.docx`, `19-20_EN.docx` không có lỗi ngôn ngữ được xác nhận bằng bộ kiểm tra này. Bằng chứng nằm trong `artifacts/wrong-language/*-old-faults.json`; test hồi quy đọc trực tiếp DOCX thật. Ba bản nguồn trong workspace có SHA-256 giống các bản cùng tên trong thư mục nguồn.

4. **Phát hiện nhầm:** test Cael/Evelyn/Karine, tên đơn lẻ, từ quốc tế, số, ký hiệu, placeholder, URL và đoạn giữ nguyên có khai báo `preserve_terms` đều không bị kết luận sai chắc chắn. Văn bản ngắn/mơ hồ trả về thiếu bằng chứng; nghi vấn chỉ cảnh báo. Không thể đảm bảo hết mọi trường hợp âm tính/dương tính giả; trường hợp giữ nguyên có chủ đích cần ngữ cảnh rõ ràng.

5. **Batch ba dòng:** kiểm tra sau chuẩn hóa, trước commit thành công; chấp nhận hai dòng tốt, chỉ đưa dòng sai vào retry. Trace giữ raw/processed của nội dung bị từ chối với `accepted=0`; không ghi đè bản dịch tốt hoặc sửa tay bằng nội dung sai.

6. **Scheduler chung:** dùng cùng retry queue, batch ID, provider/model, context nguồn, revision và bộ điều phối đã có. Test nhiều file và hai ngôn ngữ tuần tự ở cap 1/30/50; retry hoàn tất trước khi qua phase sau. Không tạo scheduler riêng cho lỗi ngôn ngữ.

7. **Ngân sách attempt:** mặc định lần đầu + tối đa năm retry, tổng sáu. `prepare_attempt`, `allowed_retry`, tái dựng hàng đợi và đối soát cuối đều nhận lỗi `wrong_target_language`. Không tạo batch mới để reset ngân sách retry tự động; test không có attempt 7. Lượt thủ công chỉ được tạo sau xác nhận riêng của người dùng.

8. **Tự xử lý:** `WRONG_LANGUAGE_CONFIRMED` không được chấp nhận như kết quả mới thành công, mang trạng thái `wrong_target_language`, tự retry sớm nếu đủ điều kiện. Retry có chỉ dẫn ngắn, giữ prompt/ngữ cảnh gốc, không đưa bản sai vào context đã xác minh. Hết ngân sách giữ lỗi để can thiệp. `SUSPECTED` lưu kèm cảnh báo, không tự retry. Console ghi locale, batch/line/attempt, kết luận, mức tin cậy và mã lý do; không log văn bản truyện/key hoặc gán lỗi chất lượng thành HTTP/parser.

9. **Xuất đơn:** guard đọc snapshot nhất quán và kiểm tra nội dung thực tế renderer sẽ dùng, kể cả status cũ ghi `done`. Chặn trước tạo thư mục/file, ghi đè hoặc lưu phiên bản mới. Bản xuất cũ còn nguyên nếu lỗi.

10. **Xuất hàng loạt:** kết quả riêng `blocked_language` cho cặp tài liệu/đích lỗi; file hợp lệ tiếp tục xuất. Áp dụng TXT/DOCX, cạnh nguồn, thư mục TransComic và thư mục tùy chọn. Dialog ghi tài liệu, ngôn ngữ, số dòng và lý do, cho click điều hướng và mở danh sách để xác nhận dịch lại.

11. **INCOMPLETE:** guard kiểm tra cả văn bản nguồn được dùng thay thế; đoạn Việt được xác nhận không lọt vào bản EN qua suffix `_INCOMPLETE`. Tên riêng, dòng ngắn và dữ liệu bảo vệ không bị chặn chỉ vì thiếu bằng chứng.

12. **Lịch sử:** mở tài liệu và cập nhật cảnh báo chạy kiểm tra cục bộ, giữ nguyên văn bản/revision chỉnh sửa, hủy tính hợp lệ của bản sai. Batch lịch sử đã hoàn tất có bằng chứng nhận sai được đánh dấu để tiếp tục đúng attempt/revision đang có, không gọi API khi mở. Attempt chưa rõ kết quả do crash/mạng không được tự replay.

13. **Sửa tay:** kết quả API đến muộn không ghi đè revision mới; dòng manual không đủ điều kiện retry tự động. Sửa tay vẫn còn Việt được cảnh báo/chặn xuất, sửa thành Anh cập nhật trạng thái. Bản tốt trước một request lỗi vẫn được giữ và có thể xuất nếu bản đó qua kiểm tra.

14. **Test:** nền **360 passed, 1 skipped**. Thêm 41 test về validator, partial retry, cảnh báo nghi vấn, six-attempt, manual/previous-good protection, lịch sử, file thực tế, nhiều file/phase/cap, guard TXT/DOCX × ba vị trí × status cũ/fallback. Có thêm ca response chứa nguồn Việt nhưng transport chưa rõ kết quả: giữ nguyên lỗi mạng/unknown, không biến thành retry an toàn và không vượt rào ngôn ngữ. Suite cuối **401 passed, 1 skipped trong 92,13 giây** (`python -m pytest -q --basetemp .pytest_language_uncertainty_final`); không sửa/xóa test cũ. Skip cũ thuộc kiểm thử có điều kiện.

15. **GUI Windows:** `python -m scripts.wrong_language_gui_smoke` chạy entry point `run_transcomic.py` bằng Qt platform `windows`, DB tạm riêng. Kiểm tra Light/Dark, ba dòng lịch sử, click điều hướng, nút retry và hủy xác nhận không gọi API, dialog chặn xuất và sửa tay cập nhật. Bằng chứng: `artifacts/wrong-language/gui/report.json` và ảnh `history-*.png`.

16. **API thật:** người dùng trực tiếp cho phép Kira DeepSeek trên đúng `15-16.docx`, `17-18.docx`, `19-20.docx`, tối đa ba lượt/file, chín lượt tổng, không hỏi ngân sách. Quyền này thay thế mục offline-only của tài liệu cho ba file được nêu. Đợt mới dùng ledger riêng `artifacts/wrong-language/live/authorization-ledger.json`, không dùng lại quyền/ledger cũ; không gọi Gemini. Kết quả cuối được ghi ở phần bên dưới.

17. **Không build EXE:** chỉ sửa nguồn, test và chạy entry point Windows. Giữ DB/key/lịch sử của người dùng, file nguồn và các bản EN cũ. DB/ledger/ảnh/bản xuất thử nằm riêng trong `artifacts/wrong-language`; ba bản EN đủ dòng nằm ở `live/verified`.

## API thật và kiểm tra bản xuất

Đã kết thúc **5 lượt toàn file**: `15-16` một lượt, `17-18` một lượt, `19-20` ba lượt. Không vượt ba lượt/file hoặc chín lượt tổng; không gọi thêm sau lượt thứ ba của `19-20`.

| File | Lượt | Luồng | Dòng API hoàn tất | Request | Retry request | HTTP 504 | Attempt cao nhất |
|---|---:|---:|---:|---:|---:|---:|---:|
| 15-16 | 1 | 30 | 124/124 | 64 | 22 | 22 | 5 |
| 17-18 | 1 | 30 | 121/121 | 65 | 24 | 23 | 6 |
| 19-20 | 1 | 30 | 123/129 | 107 | 64 | 65 | 6 |
| 19-20 | 2 | 10 | 123/129 | 84 | 41 | 43 | 6 |
| 19-20 | 3 | 30 | 123/129 | 80 | 37 | 39 | 6 |

Tổng **400 request, 188 retry request, 192 HTTP 504, không có 429**, không có attempt 7. Usage nhận được: input 256.031, output 752.576, tổng 1.008.607 token; **192 request không có usage**, không coi chúng là miễn phí. Mỗi request có correlation ID riêng và số attempt SQLite khớp ledger. Giảm luồng xuống 10 không làm lượt thứ hai hoàn tất đủ file; không kết luận đã sửa được 504 của máy chủ.

Không có response sai ngôn ngữ được xác nhận phát sinh trong năm lượt thật; retry sai ngôn ngữ được chứng minh bằng mock và ba đoạn lỗi cũ, không tuyên bố đã đo hiệu quả prompt retry sai ngôn ngữ bằng API thật. Ba đoạn 67–69 của `17-18` trong lượt mới đều đã dịch sang Anh.

**Ba lượt `19-20` vẫn thiếu sáu dòng/lượt vì 504:** lần lượt 19–21/70–72, 28–30/79–81, 58–60/79–81. Guard chặn cả ba bản `_INCOMPLETE`; không tạo file thiếu. Mỗi lượt kết thúc xử lý (`job.state=finished`) không đồng nghĩa dịch đủ toàn bộ tài liệu. Những lỗi và số liệu gốc vẫn được giữ nguyên.

**Bản EN cuối của `19-20` là kết quả đối soát offline từ các đoạn API thực sự thành công:** 123 đoạn của lượt 3, ba đoạn 58–60 của lượt 2 và ba đoạn 79–81 của lượt 1. Kiểm tra hash nguồn, ordinal/văn bản nguồn, locale/model, trace API `accepted=1`, nội dung processed khớp bản lưu và validator trước khi ghép. Không tạo đoạn dịch giả, không dùng nguồn Việt, không gửi request hoặc tăng attempt; không đổi số liệu ba lượt thiếu thành 129/129. Việc ghép nằm trong script kiểm thử/artifact riêng, không phải tính năng tự ghép các lần nhập của UI.

Ba bản xuất cuối:

- [15-16_EN.docx](../artifacts/wrong-language/live/verified/15-16_EN.docx): 124 dòng.
- [17-18_EN.docx](../artifacts/wrong-language/live/verified/17-18_EN.docx): 121 dòng.
- [19-20_EN.docx](../artifacts/wrong-language/live/verified/19-20_EN.docx): 129 dòng, có provenance từng đoạn từ ba lượt.

Audit đọc trực tiếp ba DOCX xuất: **374/374 đơn vị khớp bản lưu**, không có lỗi ngôn ngữ được xác nhận hoặc nghi vấn theo validator, số đơn vị/các part ZIP giữ nguyên và tất cả part ngoài `word/document.xml` giống nguồn. SHA-256 của cả ba nguồn không thay đổi. Đây là kiểm tra ngôn ngữ/cấu trúc, không phải chứng nhận ngữ nghĩa hoàn hảo.

Bằng chứng: [ledger](../artifacts/wrong-language/live/authorization-ledger.json), [audit](../artifacts/wrong-language/live/audit.json), [provenance từng đoạn](../artifacts/wrong-language/live/verified-provenance.json). Script `live_wrong_language.py` chỉ cho phép đúng ba nguồn và từ chối replay reservation chưa kết thúc; `reconcile_wrong_language.py`/`analyze_wrong_language.py` không gọi HTTP.

## Giới hạn

Bộ kiểm tra là heuristic có ngưỡng kiểm thử, không thay thế người đọc song ngữ. Các dòng ngắn, tên/thuật ngữ và locale gần nhau thường thiếu bằng chứng. Chưa chứng minh retry sai ngôn ngữ bằng một response sai ngôn ngữ phát sinh trong đợt API thật; đường này được kiểm thử bằng mock và ba đoạn lỗi thật đã lưu. HTTP 504 có thể đã tiêu thụ token; usage chỉ cộng các response có số liệu, không suy ra chi phí đầy đủ từ response thiếu usage.
