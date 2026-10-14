# Retry, tìm/thay nhiều tài liệu và lưu giao diện — 13/10/2026

> Báo cáo sau đợt này: [đa ngôn ngữ và dịch tuần tự](multilingual-sequential.md). Sáu lượt và số liệu dưới đây thuộc đợt cũ, không dùng lại quyền thử.

## Kết quả và bằng chứng

Đã sửa mã nguồn, chạy hồi quy, smoke bằng entry point Windows và hoàn thành đúng sáu lượt Kira được cấp quyền. Model thật cố định `deepseek-v4.1-flash`, Việt → Anh, cấu hình 30 luồng. Tổng 750/750 đơn vị có bản dịch được lưu; không còn dòng lỗi trong sáu lượt. Không gọi Gemini, không đóng gói EXE.

Bằng chứng: [đối chiếu máy đọc được](../artifacts/retry-speed/comparison.json), [ledger sáu lượt](../artifacts/retry-speed/live/authorization-ledger.json), [benchmark trước](../artifacts/retry-speed/before.json), [benchmark sau](../artifacts/retry-speed/after.json), [Console GUI đã loại nội dung truyện và key](../artifacts/retry-speed/gui/events.json), [Console API xác minh 7-8](../artifacts/retry-speed/live/7-8-pass-2-console.json), [smoke Windows](../artifacts/retry-speed/gui/report.json). Ledger chứa summary; `live/*-console.json` chứa metadata; `live/pass-1` và `live/pass-2` chứa bản xuất riêng từng file. Không xóa/reset ledger để chạy lại API.

## A. Dịch lại

### 1. Nguyên nhân retry chậm

Khảo sát tìm thấy lỗi phía ứng dụng: sau HTTP 429, cap thực tế giảm xuống 1 và không phục hồi; vòng retry giữ worker; dispatch gate có thể chờ tiếp khi hàng đợi đã hết. Metadata retry cũ còn dùng lại thời gian chờ và số worker của lần đầu. Scheduler mới đưa mỗi attempt về pool chung, luân phiên batch mới và retry sẵn sàng, kiểm tra hết việc và đối soát batch còn thiếu trước khi kết thúc. Tra cứu batch trực tiếp thay cho quét toàn bộ batch mỗi lần retry.

Máy chủ cũng ảnh hưởng thời gian: lượt baseline 7-8 có request 504 kết thúc rất muộn. Không quy toàn bộ độ chậm đó cho ứng dụng.

### 2. Vì sao từng còn 1/30?

Nhánh 429 đặt `effective_concurrency=1` nhưng thiếu nhánh tăng lại. 30 là giới hạn cấu hình, không phải số request luôn hoạt động. Lượt retry nhóm tiếp theo còn có thể kế thừa cap thấp; nay kế thừa cả trạng thái phục hồi và thời điểm 429.

### 3. Phục hồi sau sửa

Mặc định sau ba kết quả hợp lệ và ít nhất một giây yên sau 429/cooldown, tăng cap hai worker mỗi bước đến giới hạn đã cấu hình. 429 mới hạ cap và đặt lại probe. Có khoảng cách dispatch tối thiểu 50 ms sau rate limit; giữ cooldown chung và giới hạn số vòng/thời gian. Không bật lại 30 request đồng thời tức thì. Console ghi cap trước/sau, lý do, thời gian bị giảm và scope. Benchmark dùng tham số tăng tốc cố định cho cả hai phiên bản để đo nhanh; không phải quota chính thức của Kira.

### 4. Retry có bắt đầu sớm?

Có. Mock chứng minh retry chạy trước batch đầu cuối cùng. API thật lượt xác minh 7-8 trả HTTP 200 nhưng thiếu một trong ba dòng: hai dòng hợp lệ được lưu, chỉ một dòng thiếu gửi lại. Khoảng từ phản hồi lỗi đến HTTP retry là **32,47 ms**; còn sáu request lần đầu đang chạy. Retry thành công.

### 5. Các dòng lỗi cuối

Baseline 7-8 có một batch ba dòng HTTP 504: cả ba được tự dịch lại thành công. Lượt xác minh có một dòng thiếu: tự xử lý thành công. Đối soát cuối kiểm tra batch/attempt đã kết thúc, revision và chính sách retry; không kết thúc chỉ vì hàng đợi tức thời trống. Sáu lượt không còn dòng thiếu. Đây không phải cam kết mọi lỗi máy chủ tương lai đều tự khắc phục được.

### 6. Tốc độ lần đầu và retry

Baseline 7-8: pha lần đầu trải dài 67,76 s, retry ba dòng có HTTP 11,90 s; phản hồi 504 → bắt đầu retry 69,33 ms. 504 là phản hồi cuối cùng của pha đầu, nên retry diễn ra sau pha đầu. Không có bằng chứng ứng dụng buộc chờ cả file.

Sau sửa 7-8: pha lần đầu 40,49 s, HTTP retry một dòng 2,34 s và chồng lên pha đầu. Hai lỗi khác nhau và số dòng retry khác nhau; không thể gán chênh lệch 11,90 → 2,34 s chỉ cho tối ưu scheduler. Metadata cũ không đủ đo chính xác từng loại chờ retry; không diễn giải giá trị tái sử dụng thành số đo thực.

### 7. Trường hợp phải dừng

Quota cứng, cooldown quá số vòng/thời gian, xác thực thất bại, can thiệp người dùng hoặc request không rõ kết quả vẫn dừng theo chính sách. Attempt đã gửi trước crash không tự replay. Mỗi dòng tối đa lần đầu + năm retry, không reset khi regroup; dòng sửa tay hoặc revision thay đổi được bảo vệ. Transport không retry ngầm. Chờ queue/gate/cooldown có phần chồng nhau, không cộng chúng thành tổng thời gian. Console phân biệt queue, dispatch, HTTP, parse và lưu SQLite.

## B. Tìm kiếm/thay thế

### 8. Toàn workspace

Có ba phạm vi: file hiện tại, mọi file trong workspace, các file được chọn. Kết quả hiển thị file, dòng, cột và điều hướng sang đúng tài liệu. Không kéo lịch sử ngoài workspace vào thao tác. Nguồn chỉ được đếm một lần theo source instance/dòng dù có nhiều bản dịch ngôn ngữ.

### 9. Checkbox file

Có chọn tất cả/bỏ chọn và checkbox từng nguồn. Smoke chọn đúng hai trong ba file, tìm 356 vị trí trên 250 dòng. Số vị trí có thể lớn hơn số dòng vì một dòng có nhiều lần xuất hiện. Test kiểm tra tập nguồn thực tế thay vì suy ra từ số vị trí.

### 10. Cột và ngôn ngữ

Tìm nguồn, bản dịch hoặc cả hai; lọc Anh, Indonesia hoặc mọi ngôn ngữ. Thay thế chỉ vào cột đã chọn. Sửa nguồn được truyền sang các bản ngôn ngữ cùng nguồn trong workspace và đánh dấu kết quả cũ theo cơ chế revision hiện có. Không sửa file gốc trên đĩa.

### 11. Preview và Undo

Replace All nhiều file có preview nhóm theo file/dòng, trước → sau và tổng số vị trí. Checkbox loại cả file hoặc từng dòng khỏi lần thay thế. Kiểm tra toàn bộ revision trong một transaction trước khi ghi; một dòng bị sửa trong lúc preview sẽ chặn cả lần áp dụng. Undo xử lý toàn bộ lần thay và cũng kiểm tra revision để tránh ghi đè chỉnh sửa mới. Dấu xuống dòng/timecode tiếp tục được bảo vệ. Thanh phạm vi nâng cao có thể thu lại để trả vùng bản thảo.

## C. Giao diện

### 12. Sidebar

Lưu trạng thái thu gọn và chiều rộng. Smoke mở lại sidebar 72 px đúng trạng thái đã lưu; cửa sổ nhỏ tiếp tục tự thu theo quy tắc responsive.

### 13. Panel Tài liệu

Lưu ẩn/hiện, chiều rộng và vị trí splitter vào SQLite, debounce 250 ms; flush khi đóng. Restore sau khi layout có kích thước hợp lệ, clamp để vùng bản thảo còn chỗ. Ẩn panel không ghi đè chiều rộng bằng 0. Smoke xác minh chiều rộng mở lại sai lệch dưới 5 px.

### 14. Cửa sổ, theme và font

Giữ cơ chế window geometry/maximized/screen trước đây, bổ sung persistence panel/sidebar; clamp khi đổi màn hình. Test và smoke xác minh theme/font, sidebar/panel khi khởi động lại. Workspace mới trống, không scheduler hoặc gọi API; lịch sử còn nguyên. Kiểm tra nhiều màn hình dùng mock; máy kiểm thử không cung cấp phép đo chuyển qua nhiều màn hình vật lý.

## D. API thật

### 15–17. File, số lượt, dòng/request

File thứ ba là đường dẫn người dùng đã xác nhận `D:\Sourch Code\TransComic\7-8.docx`. Hai file còn lại ở `D:\word 50 cach`. Mỗi file đúng hai lượt đầy đủ; snapshot scheduler trước sửa dùng cho baseline, scheduler mới dùng cho xác minh.

| File | Lượt | Dòng hoàn tất | Request | Retry | 429 | 504 | Thời gian | Dòng/phút |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 3-4.docx | Baseline | 121/121 | 41 | 0 | 0 | 0 | 39,42 s | 184,16 |
| 5-6.docx | Baseline | 129/129 | 43 | 0 | 0 | 0 | 26,24 s | 294,99 |
| 7-8.docx | Baseline | 125/125 | 43 | 1 | 0 | 1 | 79,82 s | 93,96 |
| 3-4.docx | Xác minh | 121/121 | 41 | 0 | 0 | 0 | 32,11 s | 226,12 |
| 5-6.docx | Xác minh | 129/129 | 43 | 0 | 0 | 0 | 29,19 s | 265,14 |
| 7-8.docx | Xác minh | 125/125 | 43 | 1 | 0 | 0 | 40,55 s | 184,97 |

### 18–21. Thành công, lỗi, retry và tốc độ

750/750 dòng có kết quả hợp lệ được lưu (**100% độ phủ**, không phải chấm điểm chất lượng dịch). Tổng 254 request, hai request retry, một 504, không 429. Xác minh 7-8 có một phản hồi partial HTTP 200 được xử lý như mục 4. Attempt lớn nhất là 2. HTTP đồng thời lớn nhất 30; không đánh đồng cap 30 với 30 request luôn hoạt động.

3-4 nhanh hơn trong lượt xác minh, 5-6 chậm hơn, 7-8 nhanh hơn nhưng có kiểu lỗi khác. Mỗi điều kiện chỉ một lượt/file và thời gian máy chủ biến động; không kết luận tăng tốc chung từ sáu lượt này. Không có 429 thật nên việc phục hồi sau 429 mới được chứng minh bằng mock. Runner API không có GUI; không có số đo độ trễ GUI cho những request thật này.

### 22. Token và chi phí

Usage có báo cáo: **301.730 input + 128.795 output = 430.525 token**. Một request HTTP 504 không có usage; không coi nó là miễn phí. Giá công khai quan sát ở [Kira Models](https://kiraai.vn/models/) cho model này: input gốc 3.900đ/sale 2.730đ và output gốc 15.600đ/sale 10.920đ mỗi triệu token. Từ usage có sẵn, ước tính **3.185,95đ theo giá gốc hoặc 2.230,16đ theo giá sale**; chưa tính khoản không rõ của 504. Chưa xác minh khấu trừ ví thực tế hoặc cách tính riêng reasoning, nên đây không phải tổng hóa đơn.

Đợt mới theo yêu cầu không thêm trần tiền/token; giữ giới hạn lượt và attempt. Ledger ngân sách các đợt cũ không bị thay đổi hoặc gộp vào số liệu này.

### 23. Phạm vi và file xuất

Đúng hai lượt/file, không gửi lại cả file khi xuất/báo cáo lỗi. Baseline 3-4 dịch xong nhưng script dùng nhầm tên hàm export; phục hồi báo cáo/xuất từ SQLite offline, **không replay HTTP**. Script đã sửa và lưu kết quả lượt trước khi xuất. Sáu DOCX xuất riêng ở `artifacts/retry-speed/live/pass-{1,2}/{3-4,5-6,7-8}/`. Hash ba file gốc không đổi. Các phần ZIP ngoài `word/document.xml` của bản xuất giống snapshot nguồn; đối chiếu trace đủ số dòng và không lỗi foreign key.

### 24. Gemini

Không gọi Gemini trong đợt này. Tất cả request dịch thật thuộc Kira với model DeepSeek cố định; mock GUI không dùng API thật.

## E. Kiểm thử

### 25. Hồi quy và Windows

Hồi quy cuối: **310 passed, 1 skipped, 0 failed trong 78,03 s**, lệnh `python -m pytest -q --basetemp .pytest_final_retry_speed`. Một test skip do ledger kiểm thử Word của đợt cũ đã hết quyền; không reset ledger. Test import 120 file được bổ sung yield 1 ms cho thread đọc file trong vòng chờ Qt, giữ nguyên timeout và toàn bộ assertion.

Smoke mới chạy qua `run_transcomic.py` trên Qt platform `windows`, DB/key tạm, đúng ba nguồn: 375 dòng hoàn tất, 173 request mock gồm 47 retry, peak 30, cap cuối 30. Kiểm tra preview, Undo, navigation, sidebar, splitter, theme/font, workspace mở lại trống và lịch sử còn. [Ảnh preview](../artifacts/retry-speed/gui/preview.png), [khởi động lại](../artifacts/retry-speed/gui/restored-empty.png). Có hai lần smoke bổ sung thoát lỗi trước bản cuối; không tính các lần đó là đạt. Bản cuối exit 0 và report được ghi mới.

### 26. Benchmark trước/sau

Cùng ba file giả lập, 360 dòng, cấu hình 30, HTTP mock; snapshot scheduler trước sửa so với mã mới:

| Kịch bản | Request/retry | Trước | Sau | Giảm thời gian | Cap cuối trước → sau |
|---|---:|---:|---:|---:|---:|
| JSON không hợp lệ lần đầu | 240/120 | 1,629 s | 1,523 s | 6,5% | 30 → 30 |
| 30 phản hồi 429 ban đầu | 150/30 | 6,483 s | 2,396 s | 63,0% | 1 → 30 |

Cả hai đều đủ 360 dòng và peak không vượt 30. Số đo một lần, có biến động máy; tốc độ mock không dự báo tốc độ API thật. Retry cùng chia pool, không cấp thêm 30 luồng riêng. Các pha có thể chồng lên nhau nên không cộng span initial/retry thành tổng thời gian.

### 27. Giới hạn còn lại

Không còn dòng lỗi bị bỏ sót trong tập thử. Chưa kiểm chứng phục hồi 429 với máy chủ thật, chưa chấm điểm ngữ nghĩa từng dòng hoặc xác minh hóa đơn. Request unknown/quota vẫn cần người dùng can thiệp. Kết quả preview loại theo file/dòng, chưa loại từng lần xuất hiện bên trong một dòng. Bảng thấy ít dòng khi mở preview lớn; có thể thu thanh nâng cao sau thao tác. DOCX tiếp tục có giới hạn cấu trúc/định dạng như README.

### 28. Build

Không chạy PyInstaller, Inno Setup, tạo EXE, installer hoặc GitHub Release. Chỉ sửa mã, kiểm thử, xuất tài liệu thử và lưu bằng chứng.
