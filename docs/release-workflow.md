# One-click release — Giai đoạn A

Máy dev chạy `release_transcomic.bat` ở working directory bất kỳ. **A chỉ preflight/mô phỏng**, không build/upload/publish. Không có `--publish`, env hoặc override; spec có guard, Inno có `#error`. B cần quyền và thay đổi mã riêng.

Nguồn version: `transcomic/version.py`, giữ `0.1.0` từ pyproject cũ. `--bump patch/minor/major` hoặc version cao hơn chỉ báo đề xuất. Include installer sẽ được sinh từ nguồn đó ở B, không duplicate version. Repo phân phối luôn `--repo Thnhphngz/TransComic-Releases`; không push mã nguồn riêng vào đó. Gh dùng keyring login có sẵn, không log/token file. Người dùng cuối không cần Git/gh.

## Preflight

Python/venv, Git/source dirty/commit, gh/auth/public repo/remote versions, PyInstaller/ISCC discovery, cấu trúc/version, dữ liệu nhạy cảm, template manifest, gate. Báo `production_locked=true` cả khi đủ tool. Không cài tool ngầm. DB, Word cá nhân, cache/log/.env/credential/artifact cũ không đóng gói; spec allowlist entry point và SVG. Detector literal token không in bí mật; vẫn cần secrets review trước production.

## Quy trình B cần bổ sung

| Bước | Cách dừng/phục hồi |
|---|---|
| Preflight/test | Chặn thiếu tool/commit/test lỗi, không nới Safe Exit |
| Version/commit | Chặn dirty, duplicate/downgrade, giữ build source SHA |
| Build/package | Dừng nếu lỗi; không dùng output cũ, thiếu signature/version sai |
| Verify local | Size/hash/signature + nội dung allowlist + clean VM smoke |
| Draft | Tag gắn exact commit; `--verify-tag`, không mặc định default branch. Repo phân phối khác cần source SHA và distribution commit đã chốt |
| Upload | Assets installer + signed manifest + SHA256SUMS; lỗi giữ draft |
| Verify remote | Repo/tag/name/bytes/hash/signature khớp local; thiếu thì không publish |
| Publish | Chỉ sau mọi gate; không clobber/ghi đè asset Stable hoặc release tồn tại |
| Report | Xác minh URL/assets/checksum, không tuyên bố đầy đủ nếu chưa đạt |

B mục tiêu một BAT điều phối toàn chuỗi, không upload tay. A chưa có các adapter build/ghi thật; chỉ kiểm tra kế hoạch version/assets/test/commit và khóa cố định. Chưa được quảng cáo như có thể phát hành production.

Nguồn chính thức: [GitHub releases và target_commitish](https://docs.github.com/en/rest/releases/releases), [assets](https://docs.github.com/en/rest/releases/assets), [PyInstaller spec](https://pyinstaller.org/en/stable/spec-files.html), [Inno PrivilegesRequired](https://jrsoftware.org/ishelp/topic_setup_privilegesrequired.htm), [AppId](https://jrsoftware.org/ishelp/topic_setup_appid.htm), [Ed25519 verify](https://cryptography.io/en/latest/hazmat/primitives/asymmetric/ed25519/).

Xem [updater, kiểm thử và giới hạn A](updater-stage-a.md).
