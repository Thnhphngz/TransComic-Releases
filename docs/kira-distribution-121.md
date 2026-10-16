# Điều tra phân phối Kira Multi-Key — 17/10/2026

## Kết luận từ mã nguồn và mock

Không tái hiện được tình trạng chỉ Key 1 gửi request trên mã nguồn đầu lượt điều tra. `refresh()` giữ nguyên vòng luân phiên `_order`; mỗi lần cấp slot xoay sang key tiếp theo, bỏ qua key không đủ điều kiện. Adapter của mỗi key có credential riêng. Các đường Start/retry trong UI tạo `KiraPoolProvider` khi có danh sách Kira key.

Phát hiện một giới hạn thực tế: mọi key đều bị coi là **cùng tài khoản**. Concurrency tài khoản 30, RPM 60, TPM 1.000.000, bảng reservation và cooldown dùng chung. Hai tài khoản độc lập vì thế cũng bị giới hạn tổng 30 thay vì 60 slot. Giới hạn này không tự giải thích việc chỉ một tài khoản bị tính tiền: baseline vẫn gửi request qua cả hai credential tổng hợp.

`Kira: 2 key` trước đây đếm key đang bật, không phải số key đã gửi HTTP. Không đọc DOCX, credential, database hoặc lịch sử riêng của người dùng trong đợt này. Vì vậy chưa thể kết luận request của lần dịch thật trước đó đã đi qua tài khoản nào, hoặc vì sao giao diện số dư chỉ thay đổi ở Key 1.

## Bằng chứng trước/sau

Nguồn thử: tự tạo DOCX 121 đoạn dịch được, nhập qua importer DOCX thật, một run/một file, batch tối đa 3 dòng, đúng 41 batch. HTTP hoàn toàn là `httpx.MockTransport`; handler đếm theo header Authorization của hai credential giả, chỉ ghi nhãn Key 1/Key 2. Kiểm tra line ID, attempt UUID, số batch duy nhất và kết quả đã lưu.

| Trường hợp | Request Key 1 | Request Key 2 | Peak HTTP Key 1/Key 2 | Peak tổng | Trần tổng |
|---|---:|---:|---:|---:|---:|
| Trước sửa, mặc định chung tài khoản | 21 | 20 | 15 / 15 | 30 | 30 |
| Sau sửa, giữ chung tài khoản | 21 | 20 | 15 / 15 | 30 | 30 |
| Sau sửa, hai nhóm tài khoản độc lập | 21 | 20 | 21 / 20 | 41 | 60 |

Peak đo bằng barrier giữ HTTP đang xử lý cho tới khi đạt trần hoặc hết batch. File chỉ có 41 batch nên không thể đạt 60 HTTP đồng thời. Mỗi ca hoàn tất 121/121 dòng; Key 1 lưu 61 dòng, Key 2 lưu 60 dòng, không gửi trùng. Cả phản hồi tức thời và phản hồi chồng thời gian đều được thử.

Khi dùng chung nhóm, lý do chờ được ghi `account_slots_full`. Khi hai nhóm riêng đã cấp cả 41 batch, không còn batch chưa gửi (`no_pending_work`), dù còn slot lý thuyết. Ca riêng key chậm/nhanh ở 1 slot/key: Key 1 giữ một request, Key 2 xử lý 40 request còn lại trước khi giải phóng Key 1; không bắt buộc chia 50/50 khi tốc độ khác nhau.

Bằng chứng JSON/XML trong [`artifacts/kira-distribution-121`](../artifacts/kira-distribution-121): `before-shared-*`, `after-shared-*`, `after-independent-*`, `504.json`, `timeout.json`. Các UUID trong bằng chứng thuộc fixture, không phải dữ liệu người dùng.

## Thay đổi

- `kira_keys.py`: lưu ánh xạ ID key → nhóm tài khoản bằng ID ổn định; không suy ra tài khoản từ chuỗi secret hoặc tên key.
- `kira_pool.py`: giữ round-robin, tính slot/RPM/TPM/cooldown theo nhóm; một nhóm bị chặn không cản nhóm READY khác. Giữ limit 1–30/key. Nhóm và các trần được chụp khi tạo provider; đổi nhóm không chuyển reservation đang chạy sang tài khoản khác.
- `storage.py`: migration bổ sung `account_scope`, `key_alias` và index vào bảng reservation; không sửa các bảng bản dịch. Reservation cũ giữ nguyên. Đổi nhóm vẫn tính reservation gần đây của key; reservation legacy chưa rõ owner được tính bảo thủ cho các nhóm cho tới khi hết cửa sổ 60 giây. Không reset budget bằng đổi nhóm. Cooldown đã biết của key cũng đi theo khi đổi nhóm.
- `kira_dispatch.py`: chỉ tăng request khi observer xác nhận bắt đầu HTTP; đếm kết quả sau khi `finish_batch` xác minh và lưu; attempt diagnostics có scope và số dòng được chấp nhận. Kết thúc run ghi `kira_distribution` vào Console.
- `ui/kira_api.py`: nút **Nhóm tài khoản**, thống kê theo key và lý do chờ. Tooltip của `Kira: N key` giải thích đây là số key bật. Không đưa secret vào thống kê.
- `ui/stage2.py`: cập nhật tooltip Luồng cho giới hạn theo nhóm; giữ bố cục dịch.
- `diagnostics.py`: mô tả sự kiện tổng kết phân phối.

### Cách cấu hình hai tài khoản độc lập

Trong trang **API**, chọn **Kira 1 → Nhóm tài khoản → Tài khoản của Kira 1**. Chọn **Kira 2 → Nhóm tài khoản → Tài khoản của Kira 2**. Key thuộc cùng tài khoản phải chọn cùng nhóm. Key chưa phân nhóm tiếp tục dùng chung; không tự đổi cấu hình thật của người dùng trong phiên này.

Mặc định mỗi nhóm có concurrency 30, RPM 60, TPM 1.000.000; đây là trần cục bộ cấu hình được. Hai nhóm độc lập có trần slot tổng 60 khi mỗi nhóm có một key READY và Luồng/key = 30. Đổi nhóm có hiệu lực ở lượt mới. Thiết lập này không phải xác nhận quota dịch vụ hoặc số tiền thực tế.

### Ý nghĩa thống kê

- `requests`: lần bắt đầu gọi HTTP, kể cả request sau đó timeout. Không chứng minh server đã xử lý hoặc đã tính tiền.
- `successful_requests`: phản hồi không có lỗi parse/HTTP/unknown hoặc sai ngôn ngữ được xác nhận. Không chứng nhận chất lượng ngữ nghĩa.
- `batches`: batch đầy đủ, không lỗi, tất cả dòng được chấp nhận và lưu.
- `translated_lines`: số dòng thực sự được chấp nhận; có thể gồm dòng hợp lệ trong phản hồi partial. Không tính dòng bị bỏ qua vì người dùng đã chỉnh tay.
- `errors`: request đã gửi có lỗi/unknown/sai ngôn ngữ được xác nhận. Dừng trước HTTP không làm tăng số này.
- `busy`, `peak`: slot đã cấp đang bận và peak của từng key trong lượt hiện tại.
- `wait_reason`, `wait_reasons`: nguyên nhân hiện tại và số lần kiểm tra bị chặn; số lần kiểm tra không phải số request HTTP.

Trang API cập nhật trực tiếp, Console có tổng kết khi run kết thúc/dừng. Bộ đếm thuộc lượt hiện tại; dữ liệu attempt và tổng kết log hỗ trợ đối chiếu sau đó. Không hứa giữ bộ đếm RAM qua khởi động lại.

## Timeout/504 và toàn vẹn

Mock lỗi 504 và ReadTimeout riêng, cùng file tổng hợp 121 dòng: mỗi ca có 41 batch duy nhất, 40 thành công, 1 unknown, 118 dòng được lưu, không retry hoặc chuyển batch unknown sang key khác. Timeout dừng cấp việc mới; sau Resume chỉ cấp batch chưa từng gửi. Mỗi batch vẫn có đúng một attempt; không thay đổi fence, mapping dòng hoặc validation export. Các ca partial, chỉnh tay, Stop/Safe Exit và recovery dùng kiểm thử hồi quy hiện có.

## Kiểm thử

Các lệnh đều đặt `TRANSCOMIC_RELEASE_OFFLINE_TESTS=1` để chặn HTTP ngoài MockTransport:

```powershell
python -m pytest tests/test_kira_distribution.py tests/test_kira_multikey.py tests/test_kira_multikey_ui.py tests/test_toolbar_layout.py tests/test_diagnostics.py tests/test_console_policy.py -q
python -m pytest -q
```

Kết quả cuối và thời gian được ghi trong `focused-final.xml`, `full-offline.xml` cùng thư mục bằng chứng. Native GUI Light/Dark chạy riêng ở DPR 1,0 / 1,25 / 1,5; ảnh API và editor nằm trong các thư mục `dpi100`, `dpi125`, `dpi150`.

| Bộ kiểm thử | PASS | FAIL | SKIP | Thời gian |
|---|---:|---:|---:|---:|
| Focused trên mã cuối | 103 | 0 | 0 | 108,59 giây |
| Full offline trên mã cuối | 1.097 | 0 | 0 | 431,84 giây |
| Native GUI 100% | 12 | 0 | 0 | 22,56 giây |
| Native GUI 125% | 12 | 0 | 0 | 26,60 giây |
| Native GUI 150%, chạy lại | 12 | 0 | 0 | 21,14 giây |

Ghi nhận đầy đủ: lần native 150% đầu có 1 lỗi assertion hover của badge Dark (`get_light()==0`), 11 ca còn lại đạt; chạy lại riêng, không sửa UI hoặc làm yếu test, đạt 12/12. Giữ `dpi150.xml` và `dpi150-recheck.xml` để đối chiếu; đây là giới hạn độ ổn định của phép thử hover native ở forced scale, không bỏ qua ca lỗi. Một lượt full đang chạy đã được dừng khi bổ sung ca TPM batch nhỏ sau batch lớn; sau đó chạy lại toàn bộ trên mã cuối và đạt kết quả ở trên. Không tính lượt bị dừng là PASS.

[`acceptance.json`](../artifacts/kira-distribution-121/acceptance.json) tổng hợp XML, Git HEAD và xác nhận SHA-256 của mã cuối không thay đổi trong lúc kiểm thử. Phiên bản nguồn giữ nguyên **1.0.3**, HEAD giữ nguyên `dd232ad4af60c0611e1bb89e064a0c5414829360`.

Ảnh thống kê API: [150% Dark](../artifacts/kira-distribution-121/dpi150/account-stats-True.png), [150% Light](../artifacts/kira-distribution-121/dpi150/account-stats-False.png). Đây là fixture hiển thị bộ đếm, không phải screenshot dữ liệu hoặc tài khoản thật.

Không gọi API thật, không dùng file riêng, không xóa tiến độ, không build EXE, không sửa version, không commit hoặc phát hành.
