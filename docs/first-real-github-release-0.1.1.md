# TransComic 0.1.1 — Phát hành GitHub thật lần đầu

**GITHUB RELEASE V0.1.1 PUBLISHED AND VERIFIED**

**NATIVE INSTALL 0.1.0 — USER CONFIRMED**

**LAPTOP 2 NATIVE UPDATE TEST PENDING**

[Mở Release v0.1.1](https://github.com/Thnhphngz/TransComic-Releases/releases/tag/v0.1.1). Release ID thật `413145771`, publish lúc `2026-10-14T20:20:54Z` (UTC), draft=false, prerelease=false. Cài baseline0.1.0 do người dùng xác nhận; chưa có bằng chứng nâng cấp native0.1.0→0.1.1.

## Asset đã phát hành

| Asset | ID thật | Bytes | SHA-256 |
|---|---:|---:|---|
| TransComic-Setup-0.1.1-windows-x64.exe | 641549986 | 112892584 | `a91e61a3aff9edd1ea7c199b40196942d13d02add46e69c3db4f5a60668b51d1` |
| transcomic-update.json | 641550370 | 546 | `08c5dba7388867a76224b57e291fb0fe397365524cc3062430d4d033ed5fa7dd` |
| SHA256SUMS.txt | 641550427 | 194 | `01a432a4c436fa9090de5e62bfbf23a0df6388132cd630dec69d2e80f09fa0a1` |

Release notes tiếng Việt nằm trong nội dung Release, có build-ID gắn với journal. Chỉ ba asset giao thức được upload; không upload source hoặc báo cáo nội bộ. SHA256SUMS giữ đúng hai entry installer/manifest theo protocol baseline.

## 25 câu trả lời bàn giao

1. HEAD trước: `6fd3f061c3c78fcae3ec4ebd467858346441ff56`. Commit source phát hành: `aaed13bf4eeb05a99dbae29e2e62e089a5e2c4bb`. HEAD cuối sau commit tài liệu được ghi trong acceptance.json.
2. Đã tạo commit cục bộ cho83 file đã phân loại, sau đó hai commit sửa công cụ phát hành/draft và chặn cờ CLI viết tắt. Commit báo cáo cuối chỉ thêm tài liệu. Không push source/tag source.
3. Source sạch lúc nghiệm thu và phát hành; trạng thái cuối sau commit báo cáo ghi riêng trong acceptance.json. Không có/thay đổi origin.
4.86 build input nguyên byte khớp snapshot và staging; overlay version được khai báo. Git blob của commit khớp clean filter (chuẩn hóa newline); raw SHA kiểm tra riêng. Giữ nguyên lịch sử build từ dirty snapshot, không giả là build từ clean commit.
5. Không rebuild vì runtime/helper/installer không đổi. Công cụ release CLI/BAT mới, tests và docs nằm ngoài86 input của payload. Đã chạy full mới cho thay đổi release.
6. Installer canonical: `TransComic-Setup-0.1.1-windows-x64.exe`. Alias laptop-test có cùng byte; không ghi đè build cũ.
7. Installer: 112892584bytes.
8. SHA-256 installer: `a91e61a3aff9edd1ea7c199b40196942d13d02add46e69c3db4f5a60668b51d1`.
9. AppId `{CB58C770-47B7-42DC-A2CA-409DDF456487}`, identity TransComic.Desktop, PE app/helper0.1.1.0 x64, cùng thư mục per-user và dữ liệu ngoài thư mục chương trình. Inno bootstrap x86 không phải architecture payload. Source VERSION0.1.0, staging overlay0.1.1.
10. Internal manifest/checksum validator đạt trên byte local và remote; min-updater0.1.0, đúng repo/tag/name/size/hash. Không thay verifier Signed Stable.
11. Asset inventory đúng ba tên ở bảng. Release notes được publish trong body. Không source, DB, private log hoặc audit/test archive.
12. Mọi SHA trong bảng khớp GitHub digest và byte tải thật. Không chỉ dựa vào upload exit0.
13. Tag remote chỉ v0.1.1, trỏ commit có sẵn của repo phân phối `6dc2d5378d27eb90a455b473b306fdd5d988da66`. Không trỏ private source commit vào public repo.
14. URL: https://github.com/Thnhphngz/TransComic-Releases/releases/tag/v0.1.1.
15. Published=true, draft=false, prerelease=false; timestamp do GitHub trả ở trên.
16. Size/digest remote khớp local. Tải lại asset qua API trước/sau publish; kiểm tra ẩn danh và code baseline xác minh byte thật.
17. `/releases/latest` ẩn danh trả v0.1.1 cùng ID `413145771` với `/releases/tags/v0.1.1`.
18. Đã thực thi code object trích từ PYZ của EXE baseline0.1.0: Latest→manifest/sums→download/hash→confirm release→prepare/validate plan. Có probe offline và GET GitHub ẩn danh thật. Không chạy helper/installer, không coi là native update proof.
19. Full cuối: **889 passed, 1 skipped** (198.906s). Scope/BAT negatives29passed. Focused trước183passed và cặp runtime861passed/1skipped×2 được giữ; sáu frozen smoke cũ vẫn hợp lệ vì binary không đổi. Không nới deadline/assertion.
20. Scan source/secrets, allowlist và audit archive không thấy user DB/key/tài liệu trong payload. Manifest/body không có đường dẫn cá nhân hoặc source identity. GitHub auth dùng keyring, không in/upload token. Không tuyên bố scan chứng minh mọi encoding bí mật đều vắng mặt.
21. Laptop1 chạy installer0 lần, native handoff0 lần; không uninstall, đổi tính năng Windows hoặc reboot.
22. Kira/Gemini thật0; không reset ledger.
23. Push source công khai0; không tạo repo, đổi origin, xóa release/tag hoặc clobber asset. Quyền chỉ v0.1.1; BAT mặc định/generic adapters vẫn khóa các release khác.
24. Còn chờ laptop2 kiểm thử upgrade/restart/giữ dữ liệu sau upgrade. Baseline cài/đóng-mở/giữ dữ liệu là USER CONFIRMED. Chưa READY_FOR_FAMILY_DISTRIBUTION.
25. Bước tiếp theo là tự cập nhật trong app0.1.0 theo hướng dẫn dưới; không gỡ baseline hoặc chạy installer0.1.1 thủ công để thay bài thử.

## Người dùng thao tác trên laptop2

1. Giữ bản0.1.0 và dữ liệu đang có. Hoàn tất/dừng công việc, chờ request/worker kết thúc và lưu ô đang sửa.
2. Chọn **Cài đặt → Kiểm tra cập nhật → Tải và cài đặt**. Popup phải hiện0.1.1.
3. Chờ app tải, xác minh và thoát an toàn. Không mở thêm instance trong lúc nâng cấp.
4. Sau mở lại, kiểm tra phiên bản0.1.1, tài liệu, bản dịch sửa tay, queue/history và theme/settings. Gửi kết quả/ảnh lỗi, không gửi key hoặc DB cá nhân.
5. Nếu lỗi/không restart/kết quả unknown: giữ receipts/locks và ghi lại thông báo. Không xóa dữ liệu/lock, không chạy installer lặp. Không tắt Defender/SmartScreen.

## Lỗi đã giữ bằng chứng và giới hạn

- Probe baseline đầu kết hợp plan.exe thật với FakeWindowsRuntime vốn chỉ nhận.testdata nên lỗi fixture. Log giữ nguyên; probe đúng dùng production validation, không chạy helper.
- Full trước bắt được argparse nhận --publish như cờ viết tắt. Đã sửa allow_abbrev=False, thêm negatives, giữ nguyên assertion cũ; full cuối đạt.
- Lần publish đầu tạo draft thành công nhưng API list ngay sau đó trả rỗng; workflow dừng trước upload. GET độc lập xác minh đúng draft/tag/build ID, chưa asset; cùng commit/journal tiếp tục draft đó. Không tạo lại/xóa/ghi đè. Giữ publication-draft-propagation-failed.log, event và journal snapshot. Workflow có thể cần reconcile thủ công khi remote visibility chậm; không quảng cáo tự phát hành vô hạn.
- Internal kiểm tra consistency bằng HTTPS/SHA-256, không ký publisher; không bảo vệ khi repo/account bị chiếm. Không tuyên bố reproducible wheel-hash build. Preflight generic giữ các gate lịch sử; đường chạy chỉ v0.1.1 đã review dùng clean local source và immutable package reuse, không yêu cầu signing ceremony của Signed Stable.
- Draft dùng inventory có xác thực; URL untagged giới hạn đúng repo, API ID/byte được xác minh trước publish. Chỉ tạo identity canonical tương lai cho pre-publication schema check. URL published được kiểm tra nguyên trạng bằng baseline thật.

## Bằng chứng

`artifacts/first-real-github-release-0.1.1/acceptance.json`, gates.json, review/source snapshots/commit inventory, full/first-scope logs/XML, preflight reports, baseline-offline/remote.json, published-journal.json, command-events.json, independent-latest/tag/ref.json và anonymous-assets. Các artifact cũ không đổi. Technical-report-en.md lưu diễn giải bổ sung.

[GitHub Releases API](https://docs.github.com/en/rest/releases/releases) · [Release assets API](https://docs.github.com/en/rest/releases/assets).
