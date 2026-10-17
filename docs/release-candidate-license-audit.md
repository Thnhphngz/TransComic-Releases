# RC 1.0.4 — license và redistribution audit

> Hồ sơ lịch sử trước khắc phục. Nhiệm vụ Windows distribution kế tiếp đã cho
> phép chuẩn bị source/notices và đổi cách đóng gói. Xem
> [hồ sơ phân phối hiện tại](windows-distribution-rights.md) và báo cáo
> `artifacts/windows-distribution`; các trạng thái BLOCKED bên dưới mô tả thời
> điểm RC cũ, không tự động là quyết định cho artifact mới.

17/10/2026. **BLOCKED** cho gate license của Installer RC. Đây là trạng thái thiếu bằng chứng tuân thủ của gói cụ thể, không phải kết luận mọi dependency bị cấm sử dụng hoặc không được build riêng tư.

## 1. Phạm vi và bằng chứng

- [95 artifact](../artifacts/rc-audit/artifacts.json): 39 artifact runtime + 2 model + 54 voice, cache đúng SHA-256/size, nguồn online khớp pin. Có license metadata không đồng nghĩa gói cuối đã đáp ứng nghĩa vụ phân phối.
- [56 dependency pins của release lock](../artifacts/rc-audit/package-licenses.json): version đang cài, license metadata, đường dẫn và SHA của notices có sẵn. Đây là inventory môi trường phát triển; CPU ORT của target chưa được cài vào môi trường build riêng. Không cài chồng CPU lên GPU.
- [Native Qt codecs](../artifacts/rc-audit/qt-codec-inventory.json): avcodec-61, avformat-61, avutil-59, swresample-5, swscale-8, đều x64. Không lấy phiên bản FFmpeg từ tài liệu Qt latest để gán cho các DLL này.
- [eSpeak provenance](../artifacts/rc-audit/espeak-provenance.json), workflow/build scripts và license upstream đã lưu trong `artifacts/rc-audit/upstream-*`.

## 2. Phân biệt quyền sử dụng, tải và phân phối

| Thành phần | Sử dụng / tải | Installer / tải tự động / nghĩa vụ còn lại |
|---|---|---|
| Kokoro standard/light và 54 voice | Model card tại revision pin khai Apache-2.0 | Giữ nguồn, attribution, license và NOTICE nếu có; tải đúng revision/SHA. Installer không nhúng weights/voices. [Model card](https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/blob/1939ad2a8e416c0acfeecc08a694d14ef25f2231/README.md). |
| kokoro-onnx 0.6.1 | MIT theo LICENSE upstream/wheel | Giữ copyright/license; MIT của wrapper không thay license model hoặc các dependency. |
| ONNX Runtime CPU/GPU 1.24.4 | MIT, các notices bên thứ ba kèm distribution | Target base CPU, GPU interpreter riêng; giữ notices tương ứng đúng wheel. |
| espeakng-loader 0.2.4, phần Python | MIT upstream đã đối chiếu nội dung sau chuẩn hóa CRLF/LF | MIT notice có trong [third-party notices](tts-third-party-notices.md), nay ghim commit. Không áp MIT này cho DLL/data eSpeak. |
| eSpeak NG native/data trong wheel | Upstream eSpeak có GPLv3; wheel thiếu LICENSE/COPYING/NOTICE | **BLOCKED:** chưa xác minh đầy đủ mapping binary/data của đúng wheel tới source, build inputs và gói corresponding source/notices cung cấp cho người nhận. |
| phonemizer 3.4.0 | GPL-3.0 theo distribution | **BLOCKED:** cần chốt hồ sơ source/phương án phân phối phần kết hợp, quyền người nhận và notices. Chưa có quyết định cấp license cho source TransComic từ chủ sở hữu; không tự đổi license dự án. |
| PySide6 / shiboken6 / Qt 6.11.1 | Community licensing LGPL/GPL hoặc commercial tùy phần/module | Cần inventory đúng module, LGPL source/replacement/relink information hoặc bằng chứng commercial tương ứng; không tự suy ra quyền thương mại từ việc pip install. [Qt licensing](https://doc.qt.io/qt-6/licensing.html), [Qt for Python](https://doc.qt.io/qtforpython-6/commercial/index.html). |
| Qt FFmpeg backend | Qt có mô tả license/build provenance cho FFmpeg | Hoàn tất mapping DLL thực tế tới source/build options và notices. [Qt v6.11.1 attribution](https://github.com/qt/qtmultimedia/blob/v6.11.1/src/3rdparty/ffmpeg/qt_attribution.json); không thay bằng attribution của Qt latest. |
| SoundFile / libsndfile | BSD wrapper; libsndfile có license riêng, thường LGPL | Giữ cả wrapper và native license/source/replacement information đúng binary, không chỉ metadata SoundFile. |
| lameenc 1.9.0 / LAME | LGPL-3.0-or-later theo wheel | Giữ notices và hoàn tất source/replacement requirements cho encoder native. Có license text chưa đủ chứng minh gói hoàn chỉnh. |
| Misaki / Japanese adapter | Apache-2.0; attribution Cutlet MIT | Giữ attribution và ghi thay đổi adapter hiện có; không thay engine trong audit. |
| fugashi / MeCab / unidic-lite | Wrapper/dictionary có license riêng | Giữ LICENSE, LICENSE.unidic, dicdir/COPYING và các điều khoản chọn cho dictionary/MeCab. |
| NumPy, regex, attrs, joblib, cffi, pycparser, flatbuffers, protobuf, sympy, mpmath, packaging, cloudpickle, setuptools; các gói ngôn ngữ | Metadata/license cụ thể trong inventory | Giữ notices của từng distribution và thư viện native đi kèm; không gộp tất cả thành MIT. |
| Python embedded 3.13.14 | PSF và các notices đi kèm Python | Giữ LICENSE của bản embedded; vcruntime Microsoft không được đổi nhãn thành PSF. |
| Microsoft VC runtime | Điều khoản Microsoft áp dụng | Kiểm tra quyền phân phối các DLL cụ thể và runtime prerequisite của frozen app. [Microsoft redistribution](https://learn.microsoft.com/en-us/cpp/windows/redistributing-visual-cpp-files?view=msvc-170). Chưa cài redist hay sửa System32. |
| NVIDIA CUDA 12.9.x / cuDNN 9.27 và 7 wheel NVIDIA | EULA NVIDIA cụ thể cho phiên bản/thành phần | **Chưa đóng gate** terms/notices và điều kiện chuyển giao. CPU Installer loại NVIDIA; GPU tải trực tiếp upstream PyPI. Cách tải này không tự chứng minh mọi nghĩa vụ đã đáp ứng. [CUDA 12.9.1 EULA](https://docs.nvidia.com/cuda/archive/12.9.1/eula/index.html), [cuDNN 9.27](https://docs.nvidia.com/deeplearning/cudnn/backend/v9.27.0/reference/eula.html). |
| HTTPX, httpcore, anyio, idna, h11, charset-normalizer, python-docx, lxml, cryptography, certifi | License riêng; certifi MPL-2.0, cryptography Apache/BSD, không đồng nhất | Giữ notices/attribution; kiểm tra native lxml/OpenSSL/libxml dependencies trong bundle. TLS certifi CA bundle phải đi cùng EXE. |
| PyInstaller | GPL với bootloader exception | Exception không xóa nghĩa vụ của library được bundle. [PyInstaller license](https://www.pyinstaller.org/en/stable/license.html). |
| SVG/icon ứng dụng | Source assets đang ở repo | Không tìm thấy evidence license nguồn bên thứ ba mới; cần giữ quyền/attribution của assets nếu có bên thứ ba. Không tự tạo danh tính publisher hoặc đổi license của chủ sở hữu. |

## 3. Blocker cụ thể và việc đã xác minh

**L01 — eSpeak native/source.** Wheel pin `espeakng_loader-0.2.4-py3-none-win_amd64.whl`, SHA-256 `41f1e08ac9deda2efd1ea9de0b81dab9f5ae3c4b24284f76533d0a7b1dd7abd7`, không có license/COPYING/NOTICE. Wrapper Python khớp upstream commit `0ddc87adf77e5850d7eeb542ac8a87d421b64daa` sau chuẩn hóa xuống dòng; raw bytes khác vì CRLF, không phải phát hiện thay code. Đã ghim MIT notice đúng commit.

[Workflow upstream](https://github.com/thewh1teagle/espeakng-loader/blob/0ddc87adf77e5850d7eeb542ac8a87d421b64daa/.github/workflows/pypi.yml) lấy native/data qua `releases/latest`; workflow build hiện tại clone eSpeak tag 1.52.0. Hai điều này chưa đủ để chứng minh native/data của wheel cũ được dựng từ đúng source/build inputs đó. Không gắn license/version của main vào binary cũ chỉ vì tên package đều là 0.2.4. GPL nêu corresponding source bao gồm mã và scripts cần để dựng/cài/chạy, xem [eSpeak COPYING](https://github.com/espeak-ng/espeak-ng/blob/1.52.0/COPYING).

Đã kiểm tra thêm binary thay vì dừng ở metadata: archive Windows `v0.1.0` **427.032 byte**, SHA-256 `94a66fd30ec94dbe573e3f65491e32b8aa5b890108f890d2b68b42343474f2b6` khớp checksum công bố. DLL trong archive **khớp chính xác** DLL wheel: `646d387acbc7ac2aa45e3625aa00a6835ae5d446ff8b0748298c3900b4dde258`. [So sánh](../artifacts/rc-audit/espeak-native-comparison.json). Release tag loader trỏ commit `9ec68e20d173ff4c795b970f54324fbeae9cea8d`, submodule eSpeak là `685480238072018edfc0e4f3d85e131c278c2ccf`; đã lưu build scripts của tag. [Source links](../artifacts/rc-audit/espeak-release-source-links.json).

Đây là bằng chứng bổ sung native binary ↔ release và candidate source, chưa phải hoàn tất corresponding-source kit của cả wheel/data. Workflow tag upload vào latest và cho phép clobber, nên không tự coi target tag là provenance build bất biến; bộ data và hồ sơ source/build/distribution đầy đủ vẫn cần xác minh. Archive nhỏ chỉ dùng đọc/so sánh, không extract chạy hoặc thay DLL runtime.

**L02 — source/notice package và policy.** Các notice text hiện tại chưa là bộ source/notice/replacement package đã nghiệm thu cho GPL/LGPL dependencies và Qt/FFmpeg/LAME/libsndfile. Chưa có hồ sơ xác nhận phương án cấp quyền cho source phần kết hợp, quyền người nhận, source/relink/replacement, terms NVIDIA/Microsoft. Không tự đổi giấy phép toàn TransComic, đưa source private lên mạng, mua license, liên hệ upstream hoặc bỏ component bắt buộc.

Đây là thiếu evidence của **phương án phân phối cụ thể**. Không khẳng định GPL/LGPL cấm commercial use hoặc bắt mọi ứng dụng dùng Qt phải mua license. Cũng không gọi tải trực tiếp từ upstream là cách tự động bỏ qua license gate.

## 4. Điều kiện đóng gate

1. Có binary/data/source/build provenance cho eSpeak wheel đã pin, hoặc chọn artifact hợp lệ khác có đủ evidence và kiểm thử tương thích; không thay engine/model tùy tiện.
2. Hoàn tất corresponding source/notices và phương án phân phối được chủ sở hữu chấp thuận cho phần GPL/LGPL/Qt/codecs. Không cần công khai source trái phép trong task này.
3. Đối chiếu đúng library NVIDIA/Microsoft, terms và thông tin cần giao cho người nhận; bảo đảm luồng tải tự động phù hợp với điều khoản đã chọn.
4. Hash và đưa bộ notices/source instructions cuối vào staging/bundle, kiểm tra trên artifact frozen. Gate RC chỉ PASS khi có evidence; file license hiện diện đơn lẻ không tự đánh dấu PASS.

**Quyết định hiện tại: không build Installer.** Quyền một build nội bộ đã được cấp có điều kiện; điều kiện license chưa đạt. Không tiêu thụ lượt build, không sửa gate để ép chạy.
