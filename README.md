# TransComic · Đa ngôn ngữ và dịch tuần tự

**Phát hành tự động V2:** Sửa và lưu source, chạy `release_transcomic.bat`. BAT tự kiểm tra, chọn version carry 0–9, commit cục bộ, test/build/package, publish và xác minh GitHub khi mọi gate PASS. `--check` chỉ đọc; `--build-only` không ghi GitHub. Không gọi API dịch thật. [Hướng dẫn](docs/release-workflow.md) · [Báo cáo triển khai](docs/automatic-release-system-v2.md).

Các tài liệu Stage A/B1/B2.1 là lịch sử thiết kế; trạng thái preflight/locked trong đó không mô tả chế độ BAT hiện hành.

## Text to Speech — v1.1.0

**TTS V4** có lịch sử/tìm kiếm/xóa bản ghi, popup Xem câu và player chung. Hỗ trợ TXT/DOCX hàng loạt, nhập trực tiếp, WAV/MP3 và tối đa hai worker. **Tạm dừng cho phép tiếp tục; Dừng/Hủy kết thúc lượt**, giữ audio đã xuất. Bản Windows tự chuẩn bị runtime/model/voice qua **TTS → Cài đặt → Tải model**; lần đầu cần internet. CUDA tùy phần cứng/driver, có CPU fallback; không yêu cầu cài Python/CUDA Toolkit/cuDNN thủ công. Không hỗ trợ tiếng Việt. Xem [hướng dẫn](docs/tts-workflow.md), [release notes](docs/release-notes-1.1.0.md), [giấy phép](docs/tts-licenses.md).

## Xuất Project CapCut — source chưa phát hành

Trang **Xuất Project CapCut — v1.2.0** nhập nhiều cặp thư mục, ghép theo vị trí sau sắp xếp. Audio theo tên tự nhiên; ảnh chọn theo tên hoặc Date created cho từng nhóm. Giao diện hai cột có thumbnail, Phát/Dừng và Xem ảnh trên từng hàng. Xuất riêng, gộp hoặc chia đều thành nhiều part, đặt tên tùy chỉnh và tạo cover theo ảnh đầu mỗi project. Project liên kết media gốc, không copy ảnh/audio, không tạo MP4 hoặc MP3 gộp, gap = 0. Effect MAU được đóng gói riêng trong project. Xem [hướng dẫn](docs/capcut-positional-import.md) và [release notes](docs/release-notes-1.2.0.md).

## Gemini và dịch hàng loạt

- **Quản lý API → Google Gemini:** thêm key đơn/hàng loạt, mã hóa Windows DPAPI, phát hiện trùng và sắp thứ tự ưu tiên. Thêm key không gọi API.
- **Làm mới model:** xác nhận riêng tối đa một GET metadata; lưu cache và giữ cache khi offline. Danh sách lọc `generateContent`, chưa bảo đảm quyền dịch thành công của từng model. Không tự tải khi mở ứng dụng.
- Chọn **Provider Gemini**, model từ cache; khai báo và xác nhận RPM, TPM input, RPD còn lại, concurrency đã kiểm tra trong AI Studio. Các giới hạn phải phù hợp với mọi project/key dùng trong lượt. Gemini không mặc định có 30 request đồng thời.
- **Nhập tài liệu** chọn nhiều TXT/DOCX; **Nhập thư mục**, **Xuất tài liệu**, **Xuất hàng loạt** hiển thị trực tiếp. Kéo thả nhiều file/thư mục, duyệt thư mục con và sắp thứ tự tự nhiên. File lỗi có thông báo tổng hợp và nút xem chi tiết, không tự mở popup. Nhập lại khi file còn trong workspace chọn mục đã có; sau khi bỏ file rồi nhập lại mới tạo bản trống.
- Panel **Tài liệu** có tìm tên, tiến độ theo bản dịch, checkbox/X để bỏ file khỏi workspace, thu gọn và kéo splitter để đổi chiều rộng. Các bản ngôn ngữ của cùng lần nhập được gom trong một thẻ file; lịch sử và dữ liệu vẫn giữ khi bỏ file.
- Chip **Đích lượt dịch** hỗ trợ VI, EN, ID, HI, DE, MS, JA, ZH-CN, FIL, EN-CA và FR-CA. Số thứ tự là thứ tự dịch; bỏ/chọn lại đưa xuống cuối. Thanh chip cuộn ngang. Cả nguồn và đích dùng registry 11 locale; không chọn cùng locale, EN → EN-CA được phép. **Đang xem** chuyển bản đã tạo mà không gửi API. Cuộn, dòng đã chọn và vị trí editor được giữ riêng theo file/ngôn ngữ.
- **Hàng đợi** và **Lịch sử** là hai trang riêng. Chỉnh sửa tay được bảo vệ trước phản hồi đến muộn. Pause/Resume/Stop áp dụng toàn lượt; các request đang gửi vẫn được chờ/lưu an toàn.
- Một scheduler xử lý **toàn bộ file trong một ngôn ngữ**, gồm retry đủ điều kiện và đối soát, rồi chuyển ngôn ngữ kế tiếp theo snapshot thứ tự chọn. File cùng ngôn ngữ chạy song song trong giới hạn tổng. Kira hỗ trợ **1–50, mặc định 30**, giữ cấu hình đã lưu; Gemini dùng giới hạn/quota riêng đã xác minh. Cấu hình provider/model/prompt/ngôn ngữ/key được chụp khi bắt đầu.
- Xuất một file và hàng loạt dùng chung ba phương thức: trực tiếp cùng thư mục nguồn; `TransComic/<Ngôn ngữ>` cạnh nguồn; thư mục tự chọn. Suffix lấy từ registry, Indonesia đúng `_ID`, Canada có `_EN-CA`/`_FR-CA` và thư mục riêng. Luôn hỏi và ghi nhớ cách gần nhất, xác nhận đường dẫn, xử lý tên trùng bằng phiên bản/ghi đè/hủy. Bản thiếu dùng suffix `INCOMPLETE` và chỉ xuất sau xác nhận; snapshot không đổi theo chỉnh sửa sau lúc chụp. Nguồn mất/di chuyển yêu cầu chọn thư mục thay thế. Nút mở thư mục xuất nằm cạnh hai nút xuất, chỉ mở khi click.

Gemini không tự retry timeout/5xx hay đổi model/provider. Lỗi JSON/ID an toàn có thể retry phần thiếu theo ngân sách đã chụp. 429 dùng cooldown, thiếu reset dùng backoff có giới hạn; quota cạn hoặc vượt giới hạn chờ cần can thiệp. Chính sách key theo snapshot/project độc lập và ngân sách quota bền vững vẫn được giữ; không đổi key để vượt quota.

**Trạng thái nghiệm thu:** các phần offline và giao diện Windows đã kiểm thử. Đợt Gemini thật được duyệt đã dùng đúng 1 GET model (200, cache 19 model sau lọc) và 1 POST một dòng (404 với `gemini-2.5-flash-lite`); không retry/đổi key/model. Chưa có bản dịch/usage/chi phí thực tế, nên chưa nghiệm thu thành công Gemini thật hoặc toàn bộ Giai đoạn 2. Xem [báo cáo Giai đoạn 2](docs/stage2-workflow.md) và [ảnh GUI](artifacts/gui/stage2/report.json). Không build EXE trong giai đoạn này.

## Chạy từ mã nguồn

Chi tiết thay đổi, kiểm thử mock và ảnh Windows ở DPI 100/125/150%: [báo cáo giao diện V2](docs/ui-v2-workflow.md). Theme sáng/tối nằm dưới sidebar; timeout, cỡ chữ và retry 504 nằm trong Cài đặt. Logo SVG được tự thiết kế trong `transcomic/ui/assets/transcomic-*.svg`.

```powershell
python -m pip install -e '.[test]'
python run_transcomic.py
```

Vào **Quản lý API** để lưu Kira API key bằng Windows DPAPI. Trong **Dịch văn bản**, nhập TXT hoặc DOCX, chọn ngôn ngữ, model và số luồng, rồi bấm **Bắt đầu dịch**. Các model gồm Kira 2.5 Flash, Kira Auto, Kira Mini 1.0, Qwen3.8 27B (`qwen3.8-27b`), Qwen3.8 Flash (`qwen3.8-flash`), Coding MiMo (`coding-mimo-v2.6-flash`), DeepSeek (`deepseek-v4.1-flash`) và GLM (`glm-5.3-flash`). Lựa chọn model được ghi nhớ; mỗi lượt dịch lưu model riêng và không tự chuyển model khi request lỗi.

Mỗi request tối đa ba đơn vị, ghép bằng ID. **Cài đặt → Tự động dịch lại lỗi**: Tắt/1/2/3/4/5, mặc định 5 lần sau lần đầu, tối đa 6 attempt cho batch gốc. Job và cấu hình đã lưu giữ ngân sách cũ; dòng thành công không gửi lại. Retry lỗi JSON/ID an toàn và 429 tạm thời; thiếu reset dùng backoff, hết quota hoặc vượt trần chờ cần can thiệp. Cooldown chung tự tiếp tục, không bật pause của người dùng; sau 429 giới hạn hiệu lực xuống 1 và có nhịp gửi phục hồi. HTTP 504 Kira nếu bật dùng cùng ngân sách retry, không cộng thêm lượt. Timeout, crash, mất kết nối, 401/403 và 5xx khác không chắc kết quả không tự replay. Tiếp tục dựng lại cả batch chưa gửi và retry đủ điều kiện; khởi động không gửi lại attempt đã chuẩn bị/gửi. API thật có thể tốn token/tiền; không tự kiểm tra key.

## Bảng bản thảo và cửa sổ

Bảng vẫn dùng hai cột nguồn/bản dịch chung hàng và chung cuộn. Nhấp vào ô để sửa trên gần toàn bộ chiều rộng; chữ dài tự wrap và tăng chiều cao hàng. Chỉnh sửa được lưu ngay. Enter lưu và sang hàng tiếp, Shift+Enter sang hàng trước, Tab/Shift+Tab chuyển ô, Escape đóng editor an toàn. Xuống dòng hiển thị không thêm dòng logic. Dòng cực dài được giới hạn chiều cao theo viewport và cho cuộn trong editor để truy cập toàn bộ nội dung.

Mỗi lần mở ứng dụng, trang Dịch văn bản và lựa chọn chip ngôn ngữ đích bắt đầu trống; nút Bắt đầu chỉ bật khi đã nhập tài liệu và chọn đích hợp lệ. Lịch sử, snapshot và API key vẫn được giữ; mở công việc cũ bằng double-click trong Hàng đợi & lịch sử. Nguồn, model, provider, luồng, theme, font và layout vẫn được ghi nhớ. Trong cùng phiên, chuyển file/trang/theme không reset chip đích. Dropdown chỉ cho chọn mục có sẵn; chặn dịch khi nguồn/đích trùng nhau.

**File cùng đường dẫn đang ở workspace không được nhập trùng**: chọn mục đã có, giữ bản dịch và cảnh báo nếu nguồn ổ đĩa thay đổi. File cùng tên khác thư mục vẫn riêng. Sau khi bỏ file khỏi workspace rồi nhập lại, tạo ID mới và cột dịch trống, giữ lịch sử cũ. Lịch sử liệt kê cả lần nhập chưa dịch và từng job; chọn một mục để xóa hoặc checkbox nhiều mục rồi xóa sau xác nhận. SQLite xóa trong transaction; công việc đang chạy/inflight bị chặn. Snapshot còn được job khác dùng, file nguồn/file xuất, API key và cấu hình chung được giữ.

**Dịch lại dòng lỗi** xử lý file/ngôn ngữ đang xem; **Dịch lại tất cả lỗi** xử lý `error`/`unknown` của toàn workspace, kể cả bị ẩn, không lấy file lịch sử bên ngoài hoặc dòng chỉ có cảnh báo biên tập. Xác nhận file, ngôn ngữ, batch, provider/model gốc, concurrency và request/token mới. Các nhóm dùng scheduler chung, chia công bằng, Kira tối đa 50; provider khác có phạm vi riêng. Không đổi provider/model, bản cũ được giữ khi lỗi và chỉnh sửa mới được ưu tiên. **Bỏ tất cả file** luôn hỏi số file, chỉ loại khỏi workspace; job tiếp tục lưu đúng ID, lịch sử/nguồn/key/cấu hình được giữ.

Checkbox bên trái chọn theo ID dòng. Shift+click chọn khoảng, Ctrl+click bật/tắt một dòng; checkbox header tác động tới toàn bộ dòng thuộc bộ lọc hiện tại. Nút bỏ chọn xóa toàn bộ lựa chọn. Ba nút Copy đã được thay bằng tìm/thay thế và **Dịch lại dòng đã chọn (N)**. Ctrl+C trong editor vẫn hoạt động.

**Dịch lại dòng đã chọn** nhận cả dòng lỗi, 504/không rõ, chưa dịch và đã có bản dịch. Xác nhận ghi rõ số dòng, model/ngôn ngữ gốc và nguy cơ tốn thêm token; dòng ẩn và dòng không cần dịch không được gửi. Nếu nhiều dòng thuộc cấu hình gốc khác nhau, cần chọn từng nhóm. Bản cũ giữ nguyên khi thất bại; thành công lưu phiên bản trong `line_edits`. Chỉnh sửa/Replace trong lúc chờ luôn được ưu tiên trước phản hồi cũ. **Bắt đầu dịch** chỉ nhận dòng chưa gửi đủ điều kiện, không phải nút retry.

Ctrl+F mở tìm kiếm toàn chương, phạm vi hai cột/nguồn/dịch; Ctrl+H mở thay thế. Tìm literal Unicode, không phân biệt hoa/thường, tô sáng tất cả kết quả; gõ truy vấn không tự cuộn. ↑/↓ điều hướng. Thay thế có phạm vi nguồn hoặc dịch riêng, thao tác hiện tại/trong ô/toàn bộ và Hoàn tác. Replace All xem trước số lần/số dòng rồi xác nhận. Không thêm dòng logic, không sửa timecode; sửa nguồn đánh dấu bản dịch cũ, thay thế tăng revision để chặn phản hồi đến muộn. Hoàn tác theo nhóm trong phiên, từ chối nếu nội dung bị sửa tiếp bởi thao tác khác. Dấu • trên nút Xuất báo có thay đổi chưa xuất.

**Cần kiểm tra: N dòng** mở danh sách lỗi API, thiếu/ID sai, bản dịch trống/cũ, sai ngôn ngữ đích và heuristic dấu câu/placeholder. Một dòng có nhiều cảnh báo vẫn chỉ tính một lần. Click mục để bỏ bộ lọc đang che và điều hướng đúng dòng; hover xem nguồn/bản dịch. Nút dịch lại các dòng sai ngôn ngữ yêu cầu xác nhận. Mở lịch sử chỉ kiểm tra cục bộ, không gửi API. Sửa tay được bảo vệ; nếu vẫn sai ngôn ngữ sẽ chặn xuất. Cảnh báo được lưu kèm revision và cập nhật khi sửa, không tự xóa dấu câu. Dòng trống bản dịch cũng được tính, nên tài liệu vừa nhập có thể có nhiều dòng cần kiểm tra.

Prompt hiện tại `review-v4-locale` giữ mệnh đề, thứ tự ý, tên/xưng hô và cách nối bằng dấu phẩy; yêu cầu đúng locale, giữ nghi vấn hàm ý và dịch thành ngữ tự nhiên. Ngữ cảnh tối đa tám dòng/4000 ký tự, `reference_only`, không phải mục tiêu dịch. Giữ các prompt cũ cho lịch sử. `transcomic/postprocess.py` chuẩn hóa dấu chấm cục bộ trước khi lưu API mới, cả Kira/Gemini/retry, giữ raw và thông tin phiên bản trong `api_text_versions`; bảo vệ URL/placeholder/tag/timecode kỹ thuật. Sau chuẩn hóa, validator kiểm tra ngôn ngữ trước khi chấp nhận kết quả mới. Không chuẩn hóa lại nguồn/manual/lịch sử cũ. Retry sai ngôn ngữ thêm chỉ dẫn ngắn, giữ prompt/context gốc. Mock không chứng minh chất lượng ngữ nghĩa thật của prompt.

Xem [báo cáo kiểm thử với 7-8.docx](docs/review-workflow.md). Fixture có 11 tình huống thực tế; mock “Say ah” xác minh ID và ngữ cảnh thìa thức ăn, không chứng minh bản dịch Kira thực tế đã đúng.

Cỡ chữ bản thảo 12–22px áp dụng ngay cho bảng và editor, đo lại chiều cao và giữ vị trí đọc; được lưu cho lần mở sau. Đây là cỡ chữ giao diện, không thay font DOCX xuất ra. Có thể kéo ranh giới hai cột để đổi tỷ lệ.

Lần mở đầu dùng màn hình Qt tại vị trí con trỏ. EDID Windows hợp lệ và khớp thiết bị dùng để tính đường chéo: dưới 21 inch mở maximized, từ 21 inch mở cửa sổ giữa vùng làm việc. Thiếu hoặc không xác định chắc chắn EDID thì maximized; không suy ra inch từ độ phân giải. Vị trí, kích thước và trạng thái lưu khi thoát được ưu tiên lần sau; có nút đặt lại trong Cài đặt.

Nhấn X hoặc Ctrl+Q luôn hỏi xác nhận. Khi đang dịch, **Hủy** giữ công việc chạy; **Chạy nền** chỉ xuất hiện khi system tray sẵn sàng; **Thoát an toàn** dừng điều phối mới, chờ request đang chạy ghi kết quả rồi đóng. Không gửi lại request và không hỏi xác nhận lặp khi hoàn tất thoát an toàn.

## Timeout và chẩn đoán

Read timeout cấu hình 30–300 giây, mặc định 90; connect/pool 10 giây, write 30 giây. Model, concurrency và timeout được lưu riêng cho từng lượt dịch. Timeout HTTPX là thời gian chờ từng giai đoạn, không phải giới hạn tổng thời gian request. Tăng read timeout không sửa được HTTP 504 do gateway trả về.

Sidebar **Console** cho xem, lọc mức độ/provider/model/job/import, tìm metadata, xem chi tiết, copy lỗi/copy báo cáo và xuất TXT/JSON. Chỉ tự cuộn khi đang ở cuối; ẩn/dọn log cần xác nhận. Log JSONL ghi bằng thread riêng, tối đa khoảng 2MB/file × 4 file, 2.000 sự kiện trong bộ nhớ; nằm cạnh database, thư mục `transcomic_logs`. Console báo lỗi đọc/ghi hoặc queue đầy. Log là metadata, không có key, Authorization/cookie, truyện hoặc prompt đầy đủ.

Theo dõi queued → worker → attempt đã lưu → HTTP → gửi body nếu quan sát được → headers/body → parse/ID → commit → GUI nhận cập nhật; phân biệt queue/HTTP/parse/SQLite/GUI bằng thời gian riêng. GUI đã nhận thông báo không đồng nghĩa document đó đang mở; log ghi rõ khi import khác đang hiển thị. Không suy ra server đã thực thi request từ việc client gửi body. Trong lịch sử, **Chẩn đoán batch** còn hiển thị từng attempt. Batch cũ không có số liệu được ghi rõ thiếu metadata.

Kiểm tra dữ liệu cũ từng thấy gateway HTTP 504 với Qwen, chưa xác định tải server/model/prompt là nguyên nhân. Đợt thử thật được duyệt ngày 13/10/2026 dùng đúng ba request, một/model, retry tắt, input dưới 4.000 ký tự và `max_tokens=512`: MiMo/DeepSeek trả JSON hợp lệ; GLM HTTP 200 nhưng không phải JSON và usage đầu ra 564 vượt trần đã gửi. Không gọi thêm để kiểm chứng. Xem [báo cáo API, Console và lịch sử](docs/api-console-workflow.md) và [Console đã che dữ liệu](artifacts/live_api_20261013/console-report.json). Không kết luận model ổn định hoặc đã sửa gateway 504 từ ba request này.

## TXT và DOCX

TXT giữ nguyên số dòng, CRLF/LF, dòng trống và khoảng trắng đầu/cuối; bản xuất dùng UTF-8 không BOM. Với mã hóa cũ không rõ, ứng dụng yêu cầu chọn encoding trước khi nhập.

DOCX được phân thành các đơn vị theo đoạn văn, ô bảng và ngắt dòng thủ công. Ứng dụng giữ snapshot gói Word trong SQLite và dùng gói đó làm nền khi xuất, nên không cần file gốc còn trên đĩa. Đoạn trống, bảng lồng nhau, hình ảnh và các phần không dịch được giữ tại vị trí cũ. Việc thay chữ trong một đoạn nhiều run có thể làm mất một phần định dạng ký tự của đoạn đó, nhưng không tái tạo tài liệu từ văn bản thuần.

DOCX có chữ trong header/footer, footnote/endnote, text box, shape, field, equation, content control, hyperlink trong thân hoặc track changes nằm ngoài phạm vi xử lý an toàn hiện tại. Ứng dụng từ chối nhập những cấu trúc đó; metadata/relationship không bị hậu xử lý dấu chấm. Ánh xạ không khớp snapshot thì chặn xuất. File `.doc` cũ cần chuyển thủ công sang `.docx` trước khi nhập.

Chỉ khi bấm **Xuất tài liệu**, ứng dụng mới tạo file đầu ra. Nếu còn đơn vị chưa có bản dịch hợp lệ, ứng dụng hỏi trước về bản `INCOMPLETE`. Guard kiểm tra cả bản dịch lẫn nguồn thay thế: đoạn Việt được xác nhận không được xuất dưới dạng bản EN. Chặn riêng tài liệu/ngôn ngữ lỗi, không tạo file thiếu và không ghi đè bản xuất cũ; các file hợp lệ trong lượt hàng loạt vẫn được xuất. Không ghi đè file nguồn; nếu file đích tồn tại, ứng dụng hỏi ghi đè, lưu phiên bản mới hoặc hủy.

## Kiểm thử

```powershell
python -m pytest -q
```

Pytest tự dùng runtime ngoài workspace (`<ổ chứa project>:\TransComic-TestRuntime` trên Windows; fallback thư mục temp hệ thống). Có thể đặt `TRANSCOMIC_TEST_RUNTIME` tới một thư mục riêng ngoài project. Mỗi process có cache, `tmp_path` và TEMP/TMP riêng; không dùng lại `--basetemp .pytest_*`. Smoke harness dùng runtime/gui; logs/XML và ảnh nghiệm thu được giữ trong `artifacts`. Không thay đường dẫn SQLite/DPAPI production.

Các test dùng HTTP mock, không gọi Kira API thật. Để chạy giao diện trực tiếp: `python run_transcomic.py`. Smoke Console Windows với file Word, DB tạm và HTTP mock: `python -m scripts.console_gui_smoke`; chạy chính entry point này và xuất ảnh Light/Dark vào `artifacts/gui/console`. Script `scripts/live_kira_three.py` dành riêng cho đợt đã duyệt; ledger đã khóa không cho chạy thêm request. Không xóa/reset ledger để thử lại.

Chụp giao diện Windows với dữ liệu tạm và provider giả lập: `python -m scripts.gui_smoke --output artifacts/gui/native`. Kiểm tra riêng các công cụ biên tập với Word đã cung cấp: `python -m scripts.review_gui_smoke` (cần file `D:\word 50 cach\7-8.docx`). Ảnh mới nằm ở `artifacts/gui/review`: workspace trống, tìm/thay thế Light/Dark và danh sách cảnh báo. DPI Windows thực tế 125%, cửa sổ maximized, 1000×700 và 900×580. Các ảnh DPI mô phỏng 100%/150% từ đợt giao diện trước được giữ tại `artifacts/gui/dpi100`, `artifacts/gui/dpi150`. EDID của máy kiểm tra không xác định được; inch và nhiều màn hình được kiểm thử bằng mock. Cửa sổ nhỏ với thanh thay thế mở hiển thị ít hàng hơn; thanh bên tự thu khi cửa sổ dưới 1100px.

## Dữ liệu và giới hạn

- API key được mã hóa bằng Windows DPAPI cho tài khoản Windows hiện tại. Chuyển database sang tài khoản khác sẽ cần nhập lại key.
- Batch đã gửi trước khi ứng dụng đóng bất ngờ được đánh dấu không rõ kết quả và không tự gửi lại.
- Chỉnh sửa được ghi vào SQLite ngay; phản hồi API cũ không ghi đè bản dịch đã sửa.
- DOCX chỉ hỗ trợ các cấu trúc được kiểm tra ở trên; không đảm bảo mọi biến thể Word đều nhập được.

Tài liệu Kira: https://kiraai.vn/models/ và https://kiraai.vn/documents/.


## Retry, tìm/thay và lưu layout — 13/10/2026

Retry sẵn sàng chia pool với batch mới, chạy sớm và được đối soát trước khi kết thúc. Sau 429, concurrency tăng dần theo kết quả hợp lệ và thời gian yên; Console ghi cap và các loại thời gian chờ. Mặc định năm retry sau lần đầu, tối đa sáu attempt; bảo vệ chỉnh sửa tay và không replay request unknown.

Tìm/thay hỗ trợ file hiện tại, toàn workspace hoặc checkbox chọn file, lọc cột và ngôn ngữ. Replace All nhiều file có preview loại file/dòng, kiểm tra revision nguyên tử và Undo. Sidebar, panel Tài liệu, splitter, cửa sổ, theme/font được khôi phục; mở lại workspace trống và giữ lịch sử.

Xem [báo cáo 28 mục và bằng chứng](docs/retry-speed-workspace.md); [retry-management.md](docs/retry-management.md) là báo cáo đợt trước. Benchmark mock sau 429 giảm 6,48 → 2,40 giây; sáu lượt API thật không gặp 429 nên chưa xác minh phục hồi trên máy chủ thật. Không build EXE.

## Internal Update và Xóa toàn bộ

Trong Hàng đợi & lịch sử, **Xóa toàn bộ** xóa các lượt/batch/attempt và ẩn mục nhập khỏi danh sách; giữ tài liệu, bản dịch đã lưu, API key, settings và file nguồn/xuất. Có xác nhận số mục, mặc định Hủy; chặn khi worker/request còn hoạt động.

Ứng dụng hiện dùng **Internal Update**: repository GitHub cố định, HTTPS, manifest/checksum, size và SHA-256; không cần Ed25519 key hoặc SignTool. Hash từ cùng Release kiểm tra tính nhất quán, không xác minh publisher như chữ ký số. Native helper đã triển khai, chỉ cài sau xác minh và Safe Exit; cập nhật thật trên laptop 2 còn chờ kiểm thử. Signed Stable được giữ riêng, không fallback unsigned.

`release_transcomic.bat` hiện chạy AUTO RELEASE theo quyền người dùng chủ động mở BAT; không có automation nền. Chỉ `--check` là read-only và `--build-only` dừng trước GitHub writes. Xem [hướng dẫn và kết quả kiểm thử](docs/internal-update-and-queue-clear.md).

## Build cục bộ đầu tiên — 0.1.0 devtest

Kiểm tra cập nhật thủ công có bản Internal hợp lệ sẽ mở popup Liquid Glass với **Tải và cài đặt** / **Để sau**. Nút tải dùng downloader và native helper đã xác minh. Auto-check chỉ cập nhật trạng thái. Sidebar **Dịch file SRT** hiện là trang thông báo chức năng đang được cập nhật.

Sau full regression đạt và được cấp quyền build, dùng interpreter CPU riêng chạy `scripts/build_local.py --output <thư-mục-mới-trong-artifacts> --distribution-kit <kit-source-notices-đã-xác-minh>`. Script tạo snapshot allowlist, xác minh source/notices và payload, rồi chạy PyInstaller và ISCC; không chạy Installer, tăng version hoặc ghi GitHub. Xem [báo cáo phân phối Windows hiện tại](docs/windows-distribution-report.md). `release_transcomic.bat` vẫn là entry point phát hành hoàn chỉnh; không dùng BAT cho thử đóng gói này.

## Phiên bản và cập nhật

**v1.1.0** bổ sung TTS và Windows setup. [Hồ sơ kiểm thử v1.1.0](docs/release-1.1.0-readiness.md) ghi kết quả trên đúng Installer, CPU/CUDA hai lane, Sandbox sạch, nâng cấp và bảo toàn dữ liệu. Installer **UNSIGNED**. Luồng cập nhật dùng HTTPS + SHA-256; không phải chữ ký publisher.

[Báo cáo Windows distribution 1.0.4](docs/windows-distribution-report.md) và [RC audit](docs/release-candidate-audit.md) giữ nguyên làm lịch sử trước phát hành TTS. Bản v1.1.0 dùng source/notices đã xác minh trong Installer và asset source riêng.

v0.1.1 và v1.0.0 đã phát hành; các BAT flags cố định theo version trước đây đã được thay bằng Automatic Release V2. Giữ các báo cáo lịch sử để đối chiếu. Nguồn VERSION vẫn là `transcomic/version.py`; không tự sửa version mỗi lần phát hành.

Người dùng xác nhận laptop 2 đã cài 0.1.0, nâng 0.1.0 → 0.1.1 → 1.0.0 và giữ lịch sử sau cả hai lần nâng cấp. Đây là nghiệm thu người dùng, không phải automated E2E và không bảo đảm mọi bản tương lai.

Gói chính thức nằm ở `releases/<version>/`, không commit vào source. Installed edition dùng updater và Installer per-user mặc định. EXE chạy trực tiếp không có portable updater; không tự mở helper. Kênh Internal dùng HTTPS/SHA256, chưa xác thực publisher bằng chữ ký. SRT giữ **Dịch file SRT → Chức năng đang được cập nhật**.
