# Final pytest workspace cleanup

**PYTEST WORKSPACE CLEANUP PASS**

## 25 mục nghiệm thu

1. Ban đầu 23 thư mục .pytest_* (filesystem kiểm tra lại).
2. Archive thêm 23, 1,910,090,373 bytes; không ghi đè archive 61 thư mục của đợt trước.
3. Còn 0 thư mục .pytest_* ở root sau hai full suite và ba GUI smoke.
4. Không còn candidate bị giữ; mọi candidate đã qua process/lock/Git/hash/reparse gate.
5. 22 junction fixture đều trỏ về parent chapters trong cùng candidate, không junction nào trỏ ngoài workspace. External-junction negative test xác minh bị từ chối và sentinel target giữ nguyên.
6. Không tháo/xóa junction nguồn. Dùng FSCTL_GET_REPARSE_POINT để đọc raw metadata; copy chỉ plain directory/file rồi FSCTL_SET_REPARSE_POINT dựng entry mới. Getter/setter mở OPEN_REPARSE_POINT|BACKUP_SEMANTICS, không dereference.
7. Link object và parent target ID khác nhau; sau rename cả hai giữ nguyên inode/file identity. Hash toàn bộ regular file trước/copy/moved khớp, không xóa target. Raw links trong archive giữ target tuyệt đối cũ, có thể dangling; không chạy test qua archive alias. Restore đúng original location mới làm vòng lặp/alias hoạt động lại.
8. Archive `D:\TransComic-TestArchive\final-pytest-cleanup-20261014-230833-30d66606`; giữ cả verified copy và archived original. Manifest ghi từng SHA, raw reparse blob/tag/target, directories, Git state/times/receipts.
9. Đã hash lại độc lập cả hai bản của cả 23 candidate sau regression/GUI; aggregate và metadata link khớp.
10. Restore rehearsal một candidate có junction ra native-restore-rehearsal ngoài workspace, copy no-follow, toàn bộ hash và raw reparse khớp. Không overwrite root hoặc bản archive cũ.
11. Pytest cache nằm trong runtime/projects/<project-hash>/runs/<pid-uuid>/cache; cấu hình cache_dir chính thống dùng biến môi trường được root conftest thiết lập trước cache plugin.
12. Runtime mặc định trên máy dev: `D:\TransComic-TestRuntime`. TRANSCOMIC_TEST_RUNTIME cho override ngoài project/production/signing; fallback temp hệ thống nếu default không an toàn/không ghi được. basetemp và TEMP/TMP riêng mỗi process, gui dùng unique TemporaryDirectory trong runtime/gui. Không đổi LOCALAPPDATA/SQLite/DPAPI production.
13. Không script bình thường nào tạo root .pytest_*. README đổi về python -m pytest -q; từ chối --basetemp hoặc cache_dir trỏ vào workspace. Các literal .pytest_old trong negative/archive tests nằm dưới tmp_path riêng, không phải root thật. Docs cũ giữ lệnh historical làm bằng chứng. 21 harness test chuyển sang wrapper runtime; provisioning key production không sửa.
14. Root trước archive 50 → 27 ngay sau; snapshot trước/sau test không có thêm root pytest folders. Không dọn sau chạy để che cấu hình.
15. {'tests': '801', 'failures': '0', 'errors': '0', 'skipped': '1', 'time': '236.149', 'passed': 800}
16. {'tests': '801', 'failures': '0', 'errors': '0', 'skipped': '1', 'time': '194.679', 'passed': 800}
17. Windows native Light/Dark ở DPR 1.0,1.25,1.5: dịch văn bản/workspace, SRT, popup manual/auto, queue clear, Search/Replace/Undo, Safe Exit/process exit đạt. GUI dùng source hiện tại và HTTP guards, DB giả ngoài workspace; không rebuild EXE.
18. Safe Exit 900ms giữ nguyên; hai full regression và ba GUI smoke đạt. Không kết luận đã sửa nguyên nhân timing gián đoạn từng gặp ở đợt trước; không nới timeout/skip test.
19. Không sửa backend dịch, schema, locale, prompt, retries, scheduler hoặc DPAPI. Transcomic runtime files vẫn khớp hash build trước.
20. Không gọi API Kira/Gemini thật hoặc reset live ledger; fixtures/mocks và skip cũ giữ nguyên.
21. Không build EXE/Installer; hash mọi file trong build-0.1.0-devtest-final trước/sau trùng.
22. Không chạy installer/helper native. Cài đặt không thuộc scope này.
23. Không upload/tag/commit/push/publish; HEAD, tags và remote fingerprint trước/sau trùng; không in URL/token.
24. Không xóa file quan trọng, code, DOCX/TXT/SQLite thật, backup/journal/artifact. Source folder entries được same-volume rename có manifest verified; bản gốc và copy được giữ. Chỉ thay config/harness/docs được phép; không xóa hoặc nới test cũ.
25. No verified available Windows Sandbox/VM from prior environment probe; installer testing not authorized in this task.

## Bằng chứng và khôi phục

artifacts/final-pytest-cleanup chứa inventory.json (raw native reparse), archive-receipt.json, acceptance.json, native-junction-verification.json, restore-rehearsal.json, protected-build-before/after.json, regression-1/2.log/xml, focused*.log và windows/<scale> ảnh/report/process.log. Các đợt trước giữ nguyên.

Restore khi idle và original path không tồn tại: dùng scripts.archive_pytest_outputs.copy_no_follow(archived_original, original_path, entry_inventory), sau đó snapshot(original_path, original_path) phải khớp inventory. Raw absolute junction/alias target được bảo toàn; không follow liên kết trong archive. Không overwrite hoặc rmtree. Archive originals và verified giữ độc lập; manifest và raw blobs đủ dựng lại link.

Native setter thử đầu trả WinError87 vì truyền output buffer cho FSCTL_SET_REPARSE_POINT. Đã sửa đúng setter dùng output NULL/0; negative/restore/sentinel tests và thao tác thực tế đạt, log fail giữ trong focused.log. Không xử lý source trước khi native test gate đạt.

Hai lượt cuối chạy cùng mã, không chỉnh source giữa hai lượt. Các thay đổi hợp lệ: pyproject.toml, root conftest.py, scripts/test_runtime.py, scripts/native_reparse.py, archive tool, 21 smoke/benchmark harness, README, tests mới về native/no-follow/runtime. Artifact build đầu và code backend giữ nguyên.
