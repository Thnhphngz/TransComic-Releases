# Hoàn thiện 9 yêu cầu cuối giai đoạn — 13/10/2026

Đây là báo cáo lịch sử. Chính sách retry, cooldown, import trùng và kết quả API mới được cập nhật ở [retry-management.md](retry-management.md).

Giữ UI V2, bảng hai cột và SQLite hiện có. Không gọi API thật, không build EXE. Tất cả request nêu trong kiểm thử mới là HTTP mock, không phải bằng chứng chất lượng dịch của nhà cung cấp.

## 1. Retry tối đa bao nhiêu lần, loại lỗi nào?

Cài đặt Tắt/1/2/3, mặc định 3 **sau attempt đầu**, tối đa 4 attempt, không có lần 5. Chụp vào job/config mới; migration job cũ mặc định 0 cho chính sách mới, giữ chính sách 504 đã lưu. `request_attempts` migration giữ ID/số attempt, schema 7 không xóa lịch sử hay key. Reserve attempt trước HTTP, kiểm tra budget/revision trong transaction.

Cho phép lỗi JSON/schema/ID và partial response an toàn, chỉ gửi phần thiếu. 429 tạm thời cần thời điểm phục hồi từ response. 504 Kira có chính sách riêng tối đa một retry, không nhân thành ba. Không tự retry timeout/mạng/crash/401/403/5xx không rõ thực thi hoặc safety/content filter. Không tự resume/replay khi mở app. Batch thất bại giữ bản dịch cũ; revision manual luôn thắng. Raw API hợp lệ, processed text, phiên bản normalization, warnings và accepted flag được lưu riêng, không đưa truyện vào Console.

## 2. Cooldown HTTP 429

Kira đọc `Retry-After` giây hoặc HTTP date, lưu rate-limit headers; Gemini đọc `Retry-After` và structured RetryInfo. Các worker trong scope dùng một dispatch gate và deadline chung, không gửi mới trước deadline. Requests đã gửi được chờ/lưu. Sau 429 tạm thời giới hạn hiệu lực xuống **1** và hiển thị cạnh mức cấu hình; giữ mức đã chọn. Không tự tăng concurrency. Nhịp gửi giây/request do người dùng đặt được chụp vào job, mặc định 0; đó không phải hạn mức chính thức API.

Quota exhausted có bằng chứng cấu trúc hoặc reset không rõ: pause, không retry liên tục. Người dùng xử lý quota rồi chủ động tiếp tục phần chưa gửi hoặc xác nhận dịch lại lỗi. Không giả định 429 đã xử lý model, mất token hay miễn phí. HTTP client không có retry ẩn.

## 3. Có kiểm tra retry storm?

Có mock 50 batch đồng thời nhận 429: mỗi batch có một lần đầu và một retry, 100 request tổng, không trùng attempt. Recovery peak **1**, mọi retry sau deadline cuối. Kiểm tra retry 0/1/2/3, không lần 5, timeout/auth/crash/budget/partial/manual edit; không deadlock và Stop thoát chờ cooldown.

[Đo mock](../artifacts/final/retry-mock-comparison.json): cùng fixture 150 dòng, cấu hình 50. Tắt retry: 50 request bị từ chối, 0 thành công. Bật 3: 100 request, 50 bị từ chối + 50 thành công, 150 dòng xong, recovery peak 1. Đợt đo này khoảng 1,59s, 5644 dòng/phút; **tốc độ HTTP mock cục bộ**, không dự đoán tốc độ Kira. Usage 1100 token cũng là số mock. Scheduler ghi request/success/retry/429/cooldown window/elapsed và usage khi được trả; usage thiếu là không biết, không phải 0đ.

## 4. Retry mọi file/ngôn ngữ

Nút riêng lấy error/unknown của workspace, độc lập filter/file đang mở. Plan giữ provider/model/ngôn ngữ/key config gốc, không đưa lịch sử ngoài workspace vào. Xác nhận số file/dòng theo ngôn ngữ, batch, model/provider, concurrency và request/token mới. Không lỗi thì không tạo job.

Dùng lại Scheduler chia batch round robin. Mỗi provider có scope riêng; các cấu hình/model khác trong cùng provider lần lượt dùng pool để giữ giới hạn tổng, không đổi model của job. Các file/ngôn ngữ cùng cấu hình chạy chung và đồng thời. Budget run chung trong scope, attempt và revision bền vững. Test ba file/hai ngôn ngữ, provider riêng, pause/remove/new import, không ghi sang file mới. Native `7-8.docx` retry hết ba dòng lỗi mock dù filter che chúng.

## 5. Giới hạn 50

Kira tối đa 50 request trong scope, Gemini tối đa 30 theo cấu hình riêng. Không mở pool Kira thứ hai đồng thời cho model khác để vượt 50. Cấu hình 50/effective 1 sau 429 được hiển thị; pause/stop giữ requests đang chạy đến khi lưu an toàn. Hai provider độc lập có giới hạn riêng và UI tổng hợp đúng mức cấu hình.

## 6. Nút mở thư mục xuất

Đã chuyển cạnh Xuất file/Xuất hàng loạt; chỉ có một nút, disable nếu chưa có thư mục hợp lệ, chỉ mở Explorer khi click. Chọn thư mục của bản xuất thành công thuộc tài liệu đang xem nếu có trong đợt xuất; nếu không thì bản thành công cuối đợt. Cửa sổ nhỏ dùng tên ngắn với tooltip đầy đủ, không tràn 900×580.

## 7. Footer và Console

Nhãn notice/footer kỹ thuật không còn hiển thị trên bản thảo, trả diện tích cho bảng. Lỗi kỹ thuật vẫn lưu Console metadata an toàn; Console nạp ngay khi mở tab. Giữ Cần kiểm tra, số lỗi, navigation và tooltip dòng. Không thêm popup từng lỗi hoặc card mới. Không triển khai badge Console vì mục này tùy chọn.

## 8. Quy tắc dấu chấm nằm ở đâu?

`transcomic/postprocess.py`, gọi trong `Store.finish_batch` cho kết quả API có attempt đã xác minh. `Mr. P`, `Mrs. Florence`, `mr.p` thành tên không dấu chấm; dấu tách mệnh đề thành phẩy/khoảng trắng, chấm cuối bỏ. Không xóa từ/tên/mệnh đề hoặc thêm dòng. Idempotent, cả VI/EN/ID, URL thuần và decimals. Placeholder/tag/timecode chứa chấm ưu tiên toàn vẹn và cảnh báo xung đột; hyperlink/metadata không biến đổi. Không áp dụng cho manual, nguồn, dữ liệu cũ hoặc file đã xuất trước.

## 9. Ví dụ Emily/Karine/Evelyn

Dùng đúng fixture người dùng, từ raw không mong muốn, hậu xử lý cho ra:

```text
Only at that moment did Emily whisper, "What does the young lady plan to do next? You haven't even gotten the duke's permission yet", Karine frowned and thought, I heard all of that, you know, And Evelyn went on, "That little boy said he has nowhere else to go, Let's secretly take care of him while we look for his parents"
```

Không còn chấm; toàn bộ từ và tên trong raw giữ đúng thứ tự. **Ngoặc kép và dấu hỏi vẫn còn**: cảnh báo `New quotation marks` và `Additional sentence segments`, không tự xóa lời thoại khi chưa chắc sửa an toàn. Prompt `review-v3` cấm thêm chúng từ đầu, nhưng chưa thử API thật nên không khẳng định model đã tuân thủ hoặc chất lượng ngữ nghĩa tốt hơn. [Kết quả và warnings](../artifacts/final/emily-normalization.json).

## 10. Nguồn và DOCX

Ba lượt fixture `7-8.docx` giữ hash `1103b346f781c4cc9f1aca7ee787b8421b12749e1ff28d96524a59645a288696`. Native pass giữ 125 đơn vị và locator sau EN/ID và sáu bản xuất. Nguồn không ghi đè; manual có dấu chấm giữ nguyên. Tests TXT giữ dòng/ending, DOCX snapshot giữ locator/relationships. Bộ nhập DOCX vẫn từ chối hyperlink trong thân và các cấu trúc Word chưa hỗ trợ; không âm thầm nhận rồi làm hỏng.

## 11. Bỏ tất cả file

Nút dưới Bỏ các file đã chọn, luôn xác nhận số source instances. Chỉ bỏ workspace IDs, không xóa DB/source/export/history/key/settings. Job paused/running tiếp tục giữ dữ liệu; request cũ trả về đúng ID cũ. Test bỏ tất cả khi ba request đang chạy, nhập file mới rồi resume: cả 24 dòng EN/ID cũ hoàn thành, file mới vẫn trống bản dịch. Native pass giữ history và hiện workspace trống.

## 12. Ba phương thức xuất

Một file và hàng loạt dùng cùng policy:

| Cách | Đường dẫn |
| --- | --- |
| A | `SourceParent/Chapter_EN.docx`, không tạo thư mục con |
| B | `SourceParent/TransComic/English/Chapter_EN.docx`, Indonesian tương tự |
| C | `ChosenFolder/Chapter_EN.docx` |

Luôn chọn mode, ghi nhớ lần gần nhất và xác nhận target; collision hỏi ghi đè/version/hủy. Suffix EN/ID và INCOMPLETE, snapshot/atomic write, chống ghi đè bất kỳ nguồn trong plan. Bulk mỗi file dùng parent tương ứng, import trùng có suffix hash ổn định. Nguồn không còn, kể cả parent vẫn tồn tại: cảnh báo và yêu cầu chọn thư mục khác; không tự fallback. Native đã xuất sáu DOCX EN/ID qua A/B/C, các test có TXT, collision, nguồn mất và bảo vệ nguồn khác.

## 13. Bằng chứng rate limit

Đọc log hiện có, không mở/chỉnh DB người dùng: **282 event 429 = 94 attempt duy nhất**, model `deepseek-v4.1-flash`, cấu hình 30/40. Log cũ không ghi Retry-After hoặc usage cho chúng. Không suy ra hạn mức chính thức hay phí từ đó. Nguyên nhân điều phối đã xác định trong mã cũ: cap concurrency nhưng không có gate/cooldown chung cho 429. Đã thêm gate, cooldown, quota pause và pacing cấu hình; không hứa loại bỏ 429 do giới hạn động của nhà cung cấp. [Phân tích log](../artifacts/final/existing-429-analysis.json).

## 14. Pytest

Suite cuối: **282 đạt, 0 thất bại, 1 skip** (283 collected). Skip duy nhất là fixture Word thật sau khi đủ ba lượt được phép; không skip test retry/UI/export portable. Trước khi hết budget fixture, toàn suite 280 đạt/0 fail. Các lỗi hộp thoại/prompt cũ được điều chỉnh sang hành vi mới; assertion bảo toàn nguồn/ID/DOCX vẫn giữ. 35 test mới ở `tests/test_final_workflow.py`.

## 15. GUI Windows thật

Chạy Python entry point, platform `windows`, DB/key giả lập tạm, HTTP mock. [DPI 100%](../artifacts/gui/v2/final-100/report.json), [125%](../artifacts/gui/v2/final-125/report.json), [150%](../artifacts/gui/v2/final-150/report.json): năm TXT/DOCX, mười workspace, 300 request mock, peak 50, tám bản xuất, Light/Dark, 1200×720 và 900×580, đổi ngôn ngữ/file, editor/manual, pause/resume, bỏ file khi job còn chạy, history/API/settings/Console và hộp thoại đóng. DPI 150%, vùng màn hình làm việc giới hạn cửa sổ 1200×703; 900×580 giữ đúng. Bảng nhỏ còn 433×130px ở 125/150%, 433×137 ở 100%; không nới rộng cửa sổ để che lỗi bố cục.

Native Word lần 3: 125 nguồn, 250 mục EN/ID, **89 mock request**, peak 50, bốn retry tổng ở lượt đầu (ba parser + một 429), retry riêng toàn workspace, sáu DOCX, nguồn/manual/history giữ nguyên. [Report](../artifacts/final/docx-native/report.json), [ảnh hoàn tất](../artifacts/final/docx-native/complete.png), [workspace trống](../artifacts/final/docx-native/empty-preserved-history.png). Bốn retry tổng này thuộc hai batch khác nhau, không phải bốn retry cho một batch.

## 16. Giới hạn còn lại

Không có benchmark Kira/Gemini thật hoặc bằng chứng cải thiện ngữ nghĩa. Ngoặc kép mới chỉ cảnh báo; dấu chấm trong token bắt buộc được giữ. Quy tắc decimals/URL thuần có thể làm thay đổi khả năng dùng chuỗi kỹ thuật, có cảnh báo URL. Sau 429 giữ recovery concurrency 1 cho phần còn lại của scope, thận trọng nhưng có thể chậm hơn mức tối đa nhà cung cấp cho phép. Các model/config khác trong cùng provider chờ scope trước kết thúc. Không biết hạn mức chính thức từ log cũ. DOCX unsupported vẫn bị từ chối, định dạng nhiều run giữ giới hạn cũ. Raw API nằm trong SQLite cục bộ như snapshot nguồn, không log đầy đủ truyện/key.

## 17. API thật và giới hạn ba lượt

**0 request Kira/Gemini thật trong nhiệm vụ này.** Quyền test file tối đa ba lượt đã dùng đủ: hai regression pytest và một GUI toàn luồng. [Ledger](../artifacts/final/docx-test-ledger.json) khóa lượt thứ tư, không reset. Mục 12 yêu cầu ngân sách request/token/chi phí riêng cho API thật; không dùng lại quyền thử tiền từ đợt cũ. Không phát sinh phí API từ mock.

## 18. Build

Không chạy PyInstaller/Inno Setup, không tạo EXE/installer/release. Chỉ sửa mã, pytest và chạy ứng dụng Python. Dữ liệu người dùng, key, lịch sử và file nguồn không bị xóa.
