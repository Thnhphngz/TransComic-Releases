# TransComic 1.0.0 — Official release

TRANSCOMIC 1.0.0 OFFICIAL BUILD COMPLETE

GITHUB RELEASE V1.0.0 PUBLISHED AND VERIFIED

LAPTOP 2 UPDATE 0.1.1 → 1.0.0 PENDING USER TEST

## 1. Version chính thức

1.0.0, Windows x64, Internal channel.

## 2. Git HEAD / commit

Build và full regression từ commit sạch `025f1a2f3fec831c5eab735d2a8e563ae1fff057`. Commit báo cáo cuối chỉ thêm tài liệu; HEAD bàn giao ghi trong acceptance.json. Không push source.

## 3. Git status

Sạch trước build, trước publication; kiểm tra lại sau commit báo cáo. Không đổi origin/remotes; repository source không có remote.

## 4. Thay đổi mã nguồn

Bump VERSION duy nhất; hướng dẫn EXE chạy trực tiếp không tự cập nhật; sửa encoding UTF-8 cho preflight có release notes tiếng Việt; thêm nhánh build/publish cố định v1.0.0 dùng chung pipeline và journal. Tests dùng version fixture tương đối; không hạ assert/deadline. Provider, prompts và scheduler giữ nguyên nội dung commit trước. Không làm lại UI/SRT.

## 5. TXT / DOCX

PASS: kiểm thử import/decode/edit/render/export/persistence; frozen GUI dùng fixture tổng hợp TXT và DOCX, DOCX xuất đủ 2 units và nguồn không đổi. core-final.xml: 116 passed. Không đọc/dịch bản thảo cá nhân trong lượt live này.

## 6. Bulk translation

PASS: suite scheduler, retry/review, multi-document, queue clear và persistence trong full regression. Frozen GUI xác minh clear queue giữ nguyên workspace. Không khẳng định đã dịch hàng loạt tài liệu thật trong đợt này.

## 7. Kira API

PASS live: `deepseek-v4.1-flash`, HTTP 200, map đủ 3/3 dòng; không retry, không đổi key/model.

## 8. Gemini API

PASS live: `models/gemini-3.1-flash-lite`, HTTP 200, map đủ 3/3 dòng; metadata GET 1 và POST 1; không retry/rotation.

## 9. API requests / tokens / chi phí

Tổng 6 dòng tổng hợp, 2 POST + 1 GET metadata. Kira prompt324 / output295 / total619; Gemini prompt246 / output87 / total333; tổng952 token. Ước tính Kira5.8656đ + Gemini5.76đ =11.6256đ; actual billed cost UNKNOWN. Đã đặt reservation trước gửi; không reset hoặc thử lại. Giá nguồn: [Kira](https://kiraai.vn/models/deepseek-v4.1-flash/), [Gemini](https://ai.google.dev/gemini-api/docs/pricing); Gemini dùng giả định30.000VND/USD. Không truy cập tài liệu/history, chỉ đọc credential rows và giải mã trong RAM; không in key.

## 10. SRT placeholder

PASS: sidebar SRT còn nguyên và hiện “Chức năng đang được cập nhật”; chưa triển khai dịch SRT.

## 11. Full regression

898 passed, 1 skipped / 199.76s. Skip duy nhất: test DOCX cá nhân cũ đã hết số lượt được cấp; không reset reservation. XML/log được giữ. Không tăng timeout/giảm assert để ép PASS.

## 12. GUI smoke

PASS frozen Windows: DPR1.0 /1.25 /1.5 (100/125/150%), hai theme, SRT sidebar/placeholder, TXT/DOCX, search/replace/undo, queue clear, popup manual/background/Later, download mock. Hình ảnh thực tế được rà soát; report mỗi scale dưới artifacts/official-release-1.0.0/windows. Không gọi API dịch thật từ smoke.

## 13. Safe Exit

PASS ở cả ba frozen GUI: deadline900ms giữ nguyên; exit0 được process cha quan sát. Không chạy installer/handoff trong smoke.

## 14. EXE path

`releases/1.0.0/TransComic.exe` — chạy trực tiếp, không gọi đây là portable tự cập nhật.

## 15. Helper path

`releases/1.0.0/TransComic-UpdateHelper.exe` — component của bản installed; không mở thủ công. Packaged --self-check exit0, arbitrary --plan bị từ chối exit2.

## 16. Installer path

`releases/1.0.0/TransComic-Setup-1.0.0-windows-x64.exe`. Người mới dùng Installer; laptop2 đang installed0.1.1 dùng updater trong app.

## 17. AppId

Inno `{CB58C770-47B7-42DC-A2CA-409DDF456487}`; app `TransComic.Desktop`; mutex `TransComic.Desktop.Running`; per-user lowest, default `%LOCALAPPDATA%\Programs\TransComic`, dữ liệu `%LOCALAPPDATA%\TransComic`; không có UninstallDelete dữ liệu người dùng.

## 18. Version PE

Cả app/helper/installer:1.0.0.0. App/helper x64; Inno bootstrapper x86 chứa payload/target x64 như cấu hình cũ.

## 19. SHA-256

Xem bảng inventory bên dưới và `releases/1.0.0/SHA256SUMS.txt`. Hash file gốc build = flat release = remote canonical assets đã kiểm tra.

## 20. Build provenance

Clean source commit `025f1a2f3fec831c5eab735d2a8e563ae1fff057`; không version overlay. Hash input root/staged khớp. `build-manifest.json` chứa source hashes và artifact provenance; build logs nằm ngoài release. Archive app/helper không có userDB, bản thảo, test suite, log hay khóa; dependency công khai default.docx và cacert.pem được phân biệt. DPAPI dummy credential Kira/Gemini roundtrip trên Windows qua core tests.

## 21. Manifest verification

PASS Internal metadata_format2, app_id/version/tag/name/platform/x64/size/hash; checksum đúng hai entry installer+manifest. HTTPS/SHA256 xác minh tính nhất quán, không thay thế chữ ký publisher. Không tuyên bố Authenticode/Ed25519 đã ký.

## 22. Compatibility 0.1.1 → 1.0.0

PASS trước upload: thực thi các module lấy từ PYZ của baseline EXE0.1.1, fixture offline chứa đúng bytes Installer1.0.0. Check/download/hash/confirm/prepare/ProductionUpdateHelper.validate PASS. Sau publish chạy lại từ baseline với GitHub ẩn danh thật PASS. Không dùng source mới giả làm baseline; không chạy PE Installer hoặc native handoff. NATIVE UPDATE 0.1.0 → 0.1.1 — USER CONFIRMED SUCCESS. Native0.1.1→1.0.0 còn chờ người dùng.

## 23. GitHub Release status

PUBLISHED AND VERIFIED, non-draft/non-prerelease, ID413177474, published_at `2026-10-14T20:58:57Z`. `/releases/latest` và `/releases/tags/v1.0.0` cùng ID. v0.1.1 giữ nguyên; journal trước transition đã backup, không reset; không tạo v1.0.1, không push source.

## 24. GitHub Release URL

https://github.com/Thnhphngz/TransComic-Releases/releases/tag/v1.0.0

## 25. Remote asset hashes

Ba canonical assets đã download kiểm tra authenticated trước/sau publication; independent anonymous GET manifest/checksums và baseline0.1.1 tải Installer thật xác minh size/hash. Xem bảng và acceptance.json.

## 26. Blockers / limitations

Không còn blocker local/release. Native update trên laptop2 PENDING, không có quyền điều khiển máy2. Bản này Internal không có publisher signature; SRT là placeholder; chi phí thực tính chưa có hóa đơn; kết quả live6dòng không bảo đảm mọi tài liệu/model tương lai; chưa xác minh phân phối cho người thân chỉ dựa vào publish. Không chạy Installer, native install/update hoặc thay đổi registry/Defender/reboot máy build.

## 27. Đề xuất dọn sau này

CHỈ ĐỀ XUẤT: sau khi laptop2 PASS và đối chiếu backup, cân nhắc `artifacts/official-release-1.0.0/build/work/` và staging `build/source/` nếu đã lưu provenance + packages. Chưa xóa gì trong lượt này. Giữ releases/1.0.0, artifacts/two-laptop-update-test, các báo cáo/update/release cũ, TestArchive, SecureBackup và toàn bộ dữ liệu người dùng.

## 28. Kiểm tra laptop2

1. Mở bản installed0.1.1 hiện có tại đường dẫn mặc định; ghi nhận history/tài liệu/settings/API đang có. 2. Kiểm tra cập nhật trong app → phải hiện1.0.0. 3. Tải và xác nhận cài, đợi SafeExit; không gỡ cũ/chạy Installer tay. 4. Khi app mở lại, xác minh version1.0.0, history/tài liệu/settings/API còn nguyên; mở TXT/DOCX tổng hợp, SRT vẫn placeholder. 5. Báo kết quả/ảnh/lỗi nếu có, không reset DB. LAPTOP 2 UPDATE 0.1.1 → 1.0.0 PENDING USER TEST.

## Release gates

- `SOURCE_REVIEW_PASS`: PASS
- `BUILD_1_0_0_PASS`: PASS
- `TXT_DOCX_PASS`: PASS
- `BULK_TRANSLATION_PASS`: PASS
- `KIRA_GEMINI_VALIDATION_PASS`: PASS
- `GUI_SMOKE_PASS`: PASS
- `REGRESSION_PASS`: PASS
- `SAFE_EXIT_PASS`: PASS
- `APPID_VERSION_COMPATIBILITY_PASS`: PASS
- `BASELINE_0_1_1_UPDATE_COMPATIBILITY_PASS`: PASS
- `MANIFEST_SHA256_PASS`: PASS
- `SECRETS_PRIVACY_SCAN_PASS`: PASS
- `RELEASE_PIPELINE_PREFLIGHT_PASS`: PASS

## Flat release inventory

| File | Bytes | SHA-256 |
|---|---:|---|
| SHA256SUMS.txt | 194 | `730dabbee359deaf8910e28ffb40b41598c80ead8938e5ccfb94fc1957753777` |
| TransComic-Setup-1.0.0-windows-x64.exe | 112892338 | `d0d5fee2812e037bd34845b27ff38a2b0b46ea568b52969c2bc075a24148f73d` |
| TransComic-UpdateHelper.exe | 33788709 | `83a4e609be8cce4a07f7093f1dce6c9d5b8ea38908770b638735477aabf0bdb8` |
| TransComic.exe | 77316287 | `c3ec008af54a4fc1c62f655dce486e624cc7262a06c81bc0e631e6f6c3fa96c5` |
| build-manifest.json | 9744 | `c7976630821073285c3ccdad5d632af6d783bb77c2ba3ee4fa764ae69c620f1d` |
| release-notes.md | 1559 | `cfad012c710ecbd15068b228697343c7059be46c721ab74470da865da687da57` |
| transcomic-update.json | 539 | `174de325f47000817aaa17b35fbbb0ab643770e61f3044dad637ed40027bad99` |

Evidence: `artifacts/official-release-1.0.0/acceptance.json`, full.xml/log, core-final.xml, gates.json, build-audit.json, baseline-offline.json, baseline-remote.json, independent-latest/tag/ref.json, published-journal.json, command-events.json, privacy-scan.json. Các kết quả chẩn đoán trước sửa được giữ riêng, không tính PASS.
