# Đa ngôn ngữ và dịch tuần tự — 13/10/2026

## Kết quả

Đã nâng cấp dự án hiện có, không viết lại ứng dụng. Registry có 11 locale; scheduler xử lý toàn bộ file của một ngôn ngữ trước khi chuyển sang ngôn ngữ kế tiếp. Thứ tự theo thao tác chọn, không theo alphabet. Đợt Kira mới đã hoàn tất đúng **ba bản dịch trọn file mỗi nguồn**, tổng **9 bản dịch, 1.125/1.125 dòng**, 393 request gồm 15 retry. Không còn dòng lỗi API trong tập thử; chất lượng ngữ nghĩa vẫn cần người đọc kiểm tra.

Yêu cầu trực tiếp trong chat cấp quyền Kira thật đã thay thế mục “chỉ offline” của attachment. Không hỏi lại ngân sách và không dùng ledger các đợt trước. Mỗi file/locale được tính là một lượt để tránh vượt giới hạn ba lần/file. Không gọi API đánh giá chất lượng bổ sung, không gọi Gemini thật, không build EXE/installer/updater.

Bằng chứng chính:

- [Đối chiếu chín bản dịch, token, DOCX và rào ngôn ngữ](../artifacts/multilingual/verification.json)
- [Ledger quyền thử riêng](../artifacts/multilingual/live/authorization-ledger.json)
- Console đã che key, không chứa truyện/prompt: [3-4](../artifacts/multilingual/live/3-4-console.json), [5-6](../artifacts/multilingual/live/5-6-console.json), [7-8](../artifacts/multilingual/live/7-8-console.json). JSONL đầy đủ còn trong `artifacts/multilingual/live/results_logs`; snapshot Console trong RAM giới hạn 2.000 sự kiện.
- Smoke Windows: [scale 100%](../artifacts/multilingual/gui/1/report.json), [125%](../artifacts/multilingual/gui/1.25/report.json), [150%](../artifacts/multilingual/gui/1.5/report.json).

## 1. Scheduler đã sửa ở đâu?

`transcomic/translation.py`: giữ pool, hàng đợi batch/retry, admission gate, cooldown và đối soát hiện có; thêm vòng pha theo locale bên ngoài. Mỗi pha chỉ cấp job thuộc locale hiện tại cho pool. Chuyển pha sau khi worker/request/retry đủ điều kiện đã hết và trạng thái lưu được đối soát. Không tạo scheduler riêng cạnh tranh thêm luồng.

Rào chuyển pha dùng cùng dispatch lock với Pause/Stop. Pause giữ ngôn ngữ hiện tại, kể cả khi phản hồi cuối vừa xong; Resume tiếp tục đúng pha, Stop không mở pha mới. Retry hết ngân sách hoặc lỗi phản hồi có thể kết thúc “đã xử lý, còn lỗi”; quota, lỗi quyền/model, request unknown hoặc lỗi lưu không âm thầm chuyển tiếp.

`transcomic/workspace_retry.py`: trong một provider, nhóm lại theo thứ tự ngôn ngữ trước khi xử lý các cấu hình/model khác nhau. Unknown ở child chặn nhóm tiếp theo. Các scope provider độc lập của chức năng retry cũ vẫn giữ chính sách độc lập; một lượt dịch thông thường có một provider/model cố định.

## 2. Thứ tự được lưu thế nào?

SQLite settings `target_order` lưu danh sách đã chọn; bỏ rồi chọn lại đưa locale xuống cuối. Chip đánh số và hộp chọn đích dùng thứ tự thao tác. Run config lưu `language_order`, `target_locales`, `source_locale`, `current_locale`, `language_states`, cùng config/provider/model/attempt hiện có. Job snapshot lưu `target_locale` và `source_locale`; nhãn tiếng Việt trong các cột cũ được giữ tương thích lịch sử.

Chỉnh chip khi chạy chỉ cấu hình lượt sau. Run đang chạy đọc snapshot đã lưu. Khi khởi động lại, pha đang chạy/chờ bị đánh dấu gián đoạn, request inflight trở thành unknown; không tự gọi API. Trang Dịch trống, lịch sử/layout còn. Tiếp tục từ lịch sử đưa cả các pha đã xong/unknown vào kiểm tra rào, không bỏ qua chúng để chạy ngôn ngữ sau.

## 3. Bằng chứng EN kết thúc rồi ID mới bắt đầu

Test kiểm tra thời điểm kết thúc tất cả attempt EN, gồm retry, nhỏ hơn thời điểm HTTP/translate đầu tiên của ID. Có kịch bản một ngôn ngữ, EN → ID, JA → DE → EN, mười file, hết retry, quota, unknown, crash, Pause/Resume/Stop và thay cấu hình UI khi run đã bắt đầu. Kiểm tra tương tự với adapter Gemini mock và limiter được dùng tiếp qua pha.

API thật có sáu rào giữa chín locale/file. Khoảng từ phản hồi cuối pha trước đến HTTP đầu pha sau nằm **0,259–0,366 giây**; không chồng request khác locale trong cùng run. Nhật → Indonesia → Hindi; Đức → Malay → Trung giản thể; Filipino → Anh Canada → Pháp Canada. Các rào bao gồm cả request retry, không chỉ lần dịch đầu.

## 4. Có chia concurrency giữa ngôn ngữ khác nhau không?

Không trong một lượt dịch. Mọi slot thuộc ngôn ngữ hiện tại; các file trong pha đó vẫn dùng hàng đợi công bằng và chạy đồng thời. Cấu hình 30 không bị chia 15 EN + 15 ID. Mock với mười file kiểm tra concurrency 30/50 và không lẫn context/ID/kết quả.

## 5. Kira tối đa bao nhiêu request tổng?

UI giữ giới hạn 1–50 cho Kira; tổng pool của một lượt không vượt số cấu hình. Đợt thật cấu hình 30 và interval HTTP chứng minh peak không vượt 30. 50 không phải cam kết quota của Kira. HTTP 429 vẫn dùng cooldown chung, tăng dần concurrency sau probe thành công, bounded wait và chống storm; retry tối đa năm lần sau lần đầu. Đợt thật không có 429 nên không thêm kết luận về quota máy chủ.

## 6. Registry và UI 11 locale

Registry duy nhất `transcomic/languages.py`, dùng cho UI nguồn/đích, validation, snapshot, prompt Kira/Gemini, tên file/thư mục và lọc Search/Replace:

| Nhãn | Locale | Suffix | Thư mục TransComic |
|---|---|---|---|
| Tiếng Việt | vi | _VI | Vietnamese |
| Tiếng Anh | en | _EN | English |
| Tiếng Indonesia | id | _ID | Indonesian |
| Tiếng Hindi | hi | _HI | Hindi |
| Tiếng Đức | de | _DE | German |
| Tiếng Malay | ms | _MS | Malay |
| Tiếng Nhật | ja | _JA | Japanese |
| Tiếng Trung giản thể | zh-CN | _ZH-CN | Simplified-Chinese |
| Tiếng Filipino | fil | _FIL | Filipino |
| Tiếng Anh Canada | en-CA | _EN-CA | Canadian-English |
| Tiếng Pháp Canada | fr-CA | _FR-CA | Canadian-French |

Nguồn và đích trùng chính xác locale bị chặn. EN → EN-CA được phép khi chọn chủ động. Alias lịch sử như English/Vietnamese/VI được giải qua registry; không sửa lại văn bản nguồn hoặc snapshot cũ. Thanh chip cuộn ngang với scrollbar, không thêm nhiều hàng cao; chip có tooltip tên đầy đủ.

## 7. Malay và Indonesian

Hai locale `ms`/`id`, prompt Bahasa Melayu/Bahasa Indonesia, suffix và thư mục khác nhau. Kiểm tra từ vựng có tín hiệu riêng cho Malay/Indonesia; chữ Latin không đủ phân biệt. Từ vay mượn/tên riêng hoặc câu ngắn không tự bị coi là sai. Đợt thật có cả hai, nhưng kiểm tra cục bộ để lại nhiều dòng “không đủ bằng chứng”; không tuyên bố phân loại chắc chắn.

## 8. EN và EN-CA

Hai identity riêng trong run, lịch sử, prompt, Search và export. EN-CA có prompt Canadian English, suffix `_EN-CA`, thư mục riêng. Bộ kiểm tra hệ chữ xem cả hai cùng họ English, tránh cảnh báo “giữ nguyên nguồn” chỉ vì chuyển locale gần nhau. Chưa có bộ tham chiếu đủ để chứng nhận chính tả/diễn đạt Canada ở mọi dòng.

## 9. Kiểm tra chất lượng đã thêm

Giữ validation JSON/ID/đủ text/single line và cấu trúc TXT/DOCX hiện có. Cục bộ thêm: script Hindi/Devanagari, chữ Nhật/Hán, dấu hiệu phồn thể thường gặp, từ vựng Latin, lẫn Malay/Indonesia/Filipino, giữ nguyên nguồn, tên riêng nổi bật cho EN/ID, sắc thái câu hỏi, đối tượng trong câu ly hôn, thành ngữ và đại từ đầu câu EN/EN-CA.

Placeholder mismatch là lỗi cấu trúc kiểm tra được; nghi sai ngôn ngữ/tên/đại từ là cảnh báo suy đoán. Cảnh báo xuất hiện trong panel Cần kiểm tra, click tới dòng; không làm API retry chỉ để kiểm chứng chất lượng, không đổi model và không ghi đè sửa tay. Tooltip nút Cần kiểm tra báo số dòng nghi vấn/không đủ bằng chứng.

Prompt mới giữ nền `review-v3`, context lân cận và response ID; thêm tên nguồn/đích, target locale và yêu cầu giữ nghi vấn hàm ý, tránh thêm đại từ, diễn đạt thành ngữ tự nhiên. Không tạo character profile/glossary. Không thêm dấu chấm ASCII trong văn bản thông thường; placeholder/tag/timecode và URL kỹ thuật được bảo toàn. Sửa bảo vệ URL chỉ áp dụng khi nhận API mới, không hậu xử lý lịch sử; URL được kiểm thử offline, không dùng thêm lượt thật.

## 10. Những phần chỉ là heuristic

`language_evidence` trả `compatible`, `suspected`, `insufficient`. Compatible chỉ nghĩa hệ chữ/từ vựng phù hợp, không chứng minh đúng nghĩa hoặc đúng biến thể quốc gia. Insufficient là thông tin, không tự biến dòng hợp lệ thành lỗi. Mức chữ, word bags, danh sách chữ phồn thể và các mẫu đại từ/thành ngữ đều hữu hạn; có thể bỏ sót hoặc cảnh báo nhầm.

Đối chiếu sau đợt thật: **689 dòng có bằng chứng phù hợp, 436 dòng chưa đủ bằng chứng, 0 dòng bị heuristic nghi sai ngôn ngữ**. Các cảnh báo sắc thái câu hỏi/dấu câu/đại từ vẫn còn. Không dùng HTTP 200 hoặc các số trên để kết luận 100% ngữ nghĩa đúng.

## 11. Lỗi đáng chú ý trong mẫu

Các câu “cael bị mù màu sao”, “ly, ly hôn ư”, “dài như sớ” và các mẫu Indonesia được đưa vào fixture negative; không bịa bản dịch tham chiếu chuẩn. Candidate tổng hợp được ghi rõ là tổng hợp. Không thấy đúng các cụm đó trong ba nguồn được thử, nên không báo đã sửa chúng bằng API thật.

Kiểm tra mẫu EN-CA thật `7-8.docx`:

- Dòng 74: nguồn mở bằng “cậu ta”, output mở “she spoke…”. Đã thêm cảnh báo **Đại từ**, giữ nguyên output; cần đọc ngữ cảnh và kiểm tra khả năng nguồn dùng đại từ sai.
- Dòng 30: “Evelyn still couldn't stop blaming, such a beast” còn thiếu tự nhiên về đối tượng trong tiếng Anh; ghi nhận cần biên tập, không tự chèn “him”.
- Dòng 29 giữ cấu trúc đối thoại/phản bác; dòng 73 diễn đạt “đổ thêm dầu vào lửa” bằng “added fuel to the fire”. Đây là kiểm tra mẫu, không phải chấm toàn bộ 1.125 dòng.

Không có người đọc bản ngữ/reference đáng tin cho cả tám locale mới. Fixture script/câu ngắn là dữ liệu kỹ thuật tổng hợp, không phải ground truth ngữ nghĩa. Các bản dịch cũ/người dùng đã sửa không bị sửa hàng loạt.

## 12. Indonesia có đúng _ID?

Có. Bản thật đã xuất [3-4_ID.docx](../artifacts/multilingual/live/3-4/3-4_ID.docx). Một và hàng loạt dùng cùng `plan_exports` → `languages.export_name`, không lấy suffix từ chip/model/nhãn UI.

## 13. Kiểm thử suffix và xuất

Cả 11 suffix được parameterize cho TXT/DOCX và cả ba chế độ: cạnh nguồn, `TransComic/<Language>`, thư mục chọn. Giữ `_INCOMPLETE`, xử lý trùng basename, nhiều dấu chấm, phiên bản mới/ghi đè/hủy và snapshot export nhất quán. EN/EN-CA không chung thư mục ngôn ngữ.

Chín DOCX thật được đối chiếu tên, trace đủ dòng, danh sách ZIP và mọi phần ngoài `word/document.xml` giống snapshot gốc. Hash cả ba file nguồn không đổi; không lỗi foreign key. Bản thử xuất riêng dưới `artifacts/multilingual/live/{3-4,5-6,7-8}/`.

## 14. Chip selected/hover

Sửa ưu tiên QSS cho `#languageChip:checked:hover/:pressed/:focus` và disabled. GUI native kiểm tra pixel nền chip trước/sau hover: Light **#9b552c**, Dark **#d88a4e**; không đổi trắng. Bỏ chọn/chọn lại cập nhật số thứ tự, restart giữ thứ tự. [Ảnh Light](../artifacts/multilingual/gui/1.25/hover-False.png), [Dark](../artifacts/multilingual/gui/1.25/hover-True.png).

## 15. Unit/integration/hồi quy

Baseline được chạy lại trước sửa: **310 passed, 1 skipped**, 66,68 s. Test cũ kỳ vọng chạy đồng thời EN/ID được thay bằng kiểm tra thứ tự EN trước ID, giữ kiểm tra fairness/file/context/request/concurrency. Test số nguồn từ 3 đổi thành 11 theo yêu cầu. Test URL đổi từ phá dấu chấm URL sang bảo toàn URL kỹ thuật; các assertion khác giữ nguyên.

Hồi quy cuối: **360 passed, 1 skipped, 0 failed trong 162,26 s**, lệnh `python -m pytest -q --basetemp .pytest_multilingual_complete_final`. Smoke Windows cuối ở scale 125% exit 0; report mới giữ đầy đủ các assertion. Các lần chạy hồi quy trung gian có lỗi được sửa/đối chiếu, không tính chúng là đạt.

Test storm 50 phản hồi 429 trước đây mặc định cap phải còn 1 suốt lượt. Khi bộ test chạy lâu hơn cửa sổ phục hồi, assertion đó trái với tính năng đã sửa. Đã thay bằng kiểm tra probe đầu đúng 1/1, mọi request retry không vượt cap thực tế hoặc 50, giữ nguyên đủ 50 batch × hai request, thời gian cooldown và đủ dòng. Không bỏ test hoặc tắt phục hồi để che lỗi.

Một lượt hồi quy giữa chừng gặp timer GUI coalescing chưa phát sau 70 ms khi nhiều smoke/test chạy đồng thời; giữ test, không bỏ hoặc nới assertion. Các lượt sau kiểm tra lại. Một skip là ledger Word đợt cũ đã hết quyền, không reset. Không có request thật trong pytest.

## 16. Windows smoke

Chạy đúng `run_transcomic.py` với SQLite/key tạm và HTTP mock, Qt platform Windows. Ba DOCX, 1.125 dòng JA → EN → DE; 428 request mock, peak 30, có lỗi và retry trước rào. Kiểm tra màu hover cả theme, checkbox chip/thứ tự chọn lại, Console, bảng không tự cuộn khi refresh, cửa sổ 1400×850 và 900×580, sidebar/panel, khởi động lại trống và lịch sử chín bản còn.

Các subprocess dùng `QT_SCALE_FACTOR=1/1.25/1.5` để kiểm tra scale tương đương 100/125/150%; đây là scale Qt đặt trong phép thử, không khẳng định đã đổi DPI vật lý của Windows. [Cửa sổ nhỏ](../artifacts/multilingual/gui/1.25/layout-900.png), [mở lại](../artifacts/multilingual/gui/1.25/reopened.png).

## 17. Kira/Gemini thật và số đo

Model Kira cố định `deepseek-v4.1-flash`, nguồn Việt, concurrency 30, timeout 90 s, tối đa sáu attempt/batch. Mỗi file đúng ba lượt/locale, không gửi lại cả file vì lỗi export/report. Router ledger dự trữ trước từng HTTP, giữ ID correlation, chặn replay unknown và request vượt bound theo attempt.

Nguồn chính xác: `D:\word 50 cach\3-4.docx`, `D:\word 50 cach\5-6.docx`, `D:\Sourch Code\TransComic\7-8.docx`.

| File | Locale | Dòng | Request | Retry | 504 | Pha HTTP gồm retry |
|---|---|---:|---:|---:|---:|---:|
| 3-4.docx | [ja](../artifacts/multilingual/live/3-4/3-4_JA.docx) | 121/121 | 43 | 2 | 0 | 58,19 s |
| 3-4.docx | [id](../artifacts/multilingual/live/3-4/3-4_ID.docx) | 121/121 | 42 | 1 | 1 | 84,42 s |
| 3-4.docx | [hi](../artifacts/multilingual/live/3-4/3-4_HI.docx) | 121/121 | 43 | 2 | 1 | 81,26 s |
| 5-6.docx | [de](../artifacts/multilingual/live/5-6/5-6_DE.docx) | 129/129 | 43 | 0 | 0 | 43,19 s |
| 5-6.docx | [ms](../artifacts/multilingual/live/5-6/5-6_MS.docx) | 129/129 | 44 | 1 | 1 | 93,08 s |
| 5-6.docx | [zh-CN](../artifacts/multilingual/live/5-6/5-6_ZH-CN.docx) | 129/129 | 47 | 4 | 3 | 90,17 s |
| 7-8.docx | [fil](../artifacts/multilingual/live/7-8/7-8_FIL.docx) | 125/125 | 45 | 3 | 2 | 110,74 s |
| 7-8.docx | [en-CA](../artifacts/multilingual/live/7-8/7-8_EN-CA.docx) | 125/125 | 42 | 0 | 0 | 50,20 s |
| 7-8.docx | [fr-CA](../artifacts/multilingual/live/7-8/7-8_FR-CA.docx) | 125/125 | 44 | 2 | 0 | 58,47 s |

Tổng **393 request, 15 retry, 8 HTTP 504, 0 HTTP 429**, attempt lớn nhất 3. Usage có báo cáo **476.909 input + 302.452 output = 779.361 token**. Tám request 504 thiếu usage; không coi miễn phí, không tuyên bố tổng khấu trừ ví. Không đặt ngân sách tiền mới hoặc hỏi lại. Các số trên là đợt mới độc lập, không cộng lại số thử các báo cáo cũ.

Không gọi Gemini thật. Gemini chỉ được kiểm tra offline; phép thử POST 404 cũ vẫn không được coi là nghiệm thu thật.

## 18. Giới hạn API/chất lượng còn lại

Đã có output thật cho tám locale mới và Indonesia trên model này, không có nghĩa mọi locale đã được người bản ngữ nghiệm thu. VI và EN thường được kiểm tra offline trong đợt này; EN có thử thật ở đợt trước, không mượn số liệu đó để báo thử mới. Chưa chứng minh chất lượng Canada, sự phân biệt Malay/Indonesia ở mọi dòng, mọi hệ chữ/phồn thể hoặc ngữ nghĩa của mọi tên/đại từ.

Không còn quyền lượt thứ tư trên ba file trong đợt này. Việc đọc lại SQLite/bản xuất/Console và kiểm thử mock không phát sinh API. Các lỗi gateway tương lai và quota vẫn tuân thủ rào an toàn, không hứa tự khắc phục tất cả.

## 19. Build

Không chạy PyInstaller, Inno Setup, tạo EXE/installer/GitHub Release. Không làm updater, Bộ truyện, glossary hoặc SRT. Chạy nguồn bằng `python run_transcomic.py`.

## 20. Còn lại trước Giai đoạn 3

Cần người dùng/người đọc bản ngữ kiểm tra các cảnh báo và mẫu dịch, nhất là đại từ, câu ngắn và biến thể Canada; thu thập tham chiếu có provenance. Gemini cần đợt xác minh thật riêng nếu muốn nghiệm thu adapter trên tài khoản/model có quyền. Giữ giới hạn DOCX đã mô tả trong README. Đây là các giới hạn nghiệm thu chất lượng, không phải dòng lỗi scheduler bị bỏ sót trong đợt thử.
