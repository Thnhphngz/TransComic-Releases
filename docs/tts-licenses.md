# TTS: nguồn, phiên bản và điều kiện đóng gói

**Windows distribution 1.1.0, 17/10/2026:** bộ source/notices thực tế đi kèm Installer và asset source công khai xử lý các phát hiện của RC trước. Xem [quyền và hướng dẫn thay thư viện](windows-distribution-rights.md). Manifest xác minh từng file trước build; phát hành chỉ sau các release gates.

## Nguồn đã đối chiếu

- GUI tham khảo: <https://github.com/EliseWindbloom/kokoro-onnx-gui>. Không sao chép GUI Tkinter.
- Engine `kokoro-onnx 0.6.1`: <https://github.com/thewh1teagle/kokoro-onnx>, MIT.
- Model Kokoro v1.0 và voices: <https://huggingface.co/hexgrad/Kokoro-82M>, Apache-2.0 theo model card.
- Bản ONNX tin cậy: <https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/tree/1939ad2a8e416c0acfeecc08a694d14ef25f2231>.
- Misaki: <https://github.com/hexgrad/misaki>, Apache-2.0. Dùng bản 0.7.4 tương thích Python 3.13; không dùng extra `ja` vì `mojimoji` đòi compiler trên môi trường này.
- `transcomic/tts/japanese.py` là bản điều chỉnh `ja.py` từ wheel Misaki 0.7.4: dùng `jaconv.z2h/h2z` thay `mojimoji`, chỉ định dictionary `unidic-lite` đã đóng gói. Thuật toán gốc ghi nhận [Cutlet](https://github.com/polm/cutlet), MIT. Không thay model, phoneme inventory hoặc voice embedding.

## Asset bất biến

Catalog đi kèm mã nguồn chứa đường dẫn, kích thước và SHA-256 từ LFS metadata tại revision trên. Không lấy checksum mới từ response tải xuống để tự tin cậy response đó.

| Asset | Bytes | SHA-256 |
|---|---:|---|
| `onnx/model.onnx` | 325532232 | `8fbea51ea711f2af382e88c833d9e288c6dc82ce5e98421ea61c058ce21a34cb` |
| `onnx/model_quantized.onnx` | 92361116 | `fbae9257e1e05ffc727e951ef9b9c98418e6d79f1c9b6b13bd59f5c9028a1478` |

Voice bins được kiểm tra riêng trước khi tạo NPZ nội bộ; không dùng pickle. Tên voice sinh từ chính catalog, không tạo giọng giả. Model nhẹ là lựa chọn riêng; không tự thay model tiêu chuẩn. Test decode chứng minh hoạt động, chưa thay thế đánh giá chất lượng phát âm bởi người nghe.

Ngôn ngữ: English US/UK, Español, Français, हिन्दी, Italiano, 日本語, Português Brasil, 中文. Đây là 9 locale / 8 ngôn ngữ. Không có tiếng Việt hoặc voice cloning.

## Dependency và giấy phép

| Thành phần | Giấy phép / việc cần lưu ý |
|---|---|
| ONNX Runtime | MIT; chỉ một distribution runtime trong bundle |
| NumPy, psutil | BSD và các notices đi kèm |
| SoundFile | BSD-3-Clause; binary libsndfile có LGPL riêng |
| lameenc / LAME | LGPL-3.0-or-later theo wheel đã cài; cần giữ notices và đáp ứng điều kiện binary distribution |
| phonemizer 3.4.0 | GPL-3.0; cần rà soát việc phân phối ứng dụng kết hợp |
| espeakng-loader | Wheel không kèm license text; phải bổ sung provenance/notices và corresponding source của binary eSpeak NG trước phát hành |
| eSpeak NG | [GPL-3.0](https://github.com/espeak-ng/espeak-ng/blob/master/COPYING) |
| Misaki | Apache-2.0 |
| jaconv, jieba, pypinyin, cn2an | MIT theo metadata cài đặt |
| fugashi / MeCab | MIT / BSD; giữ cả license wrapper và MeCab |
| unidic-lite | Giữ `LICENSE`, `LICENSE.unidic`, `dicdir/COPYING`; dictionary có điều khoản riêng |
| PySide6 / Qt Multimedia / FFmpeg | Giữ notices Qt và codec tương ứng với binary phân phối |

Các license text trong wheel được giữ trong `ThirdParty/notices`, cùng [tts-third-party-notices.md](tts-third-party-notices.md). Corresponding source Qt/PySide, FFmpeg, libsndfile/codecs, LAME/lameenc, eSpeak và phonemizer đi kèm trong `ThirdParty/sources`; không chỉ cung cấp một lời hứa source offer. Bộ hồ sơ có manifest, source commits và hướng dẫn thay thư viện. Kiểm tra frozen và Windows sạch được báo riêng trong báo cáo cuối.

## Chuẩn bị đóng gói

- Windows x64, Python 3.13, PySide6 6.11.1. Pin dependencies ở `requirements-release.lock`; extra `tts` phục vụ môi trường phát triển riêng. Không bắt người dùng cuối cài pip.
- Môi trường CPU sạch đã thử: ONNX Runtime 1.24.4. Môi trường nghiên cứu DirectML tách riêng; không trộn CPU và DirectML wheels vào build.
- Môi trường CUDA riêng đã chạy thật: `onnxruntime-gpu 1.24.4`, CUDA runtime 12.9.79, cuBLAS 12.9.2.10, cuDNN 9.27.0.42, cuFFT 11.4.1.4, cuRAND 10.3.10.19, NVRTC/NVJitLink 12.9.86. Không đưa toàn bộ CUDA dependency vào bản CPU mặc định. Bundle GPU sau này cần kiểm tra thêm điều khoản redistribution NVIDIA và kích thước cài đặt.
- `scripts/tts_packaging.py` thu thập phần GUI/audio và Qt Multimedia. Frozen GUI không nhúng inference/GPL stack; dùng worker CPython riêng qua JSON/stdio có sẵn. Môi trường source vẫn giữ nguyên engine CUDA.
- Model/voice, interpreter TTS, runtime và dictionary tải từ upstream đã pin qua một nút Tải model, vào dữ liệu người dùng với kiểm tra SHA-256. DLL NVIDIA không ở trong Installer.
- Qt/audio native libraries nằm ngoài EXE trong `_internal` để người nhận thay được thư viện tương thích ABI. `qpdf.dll`/QtPdf không được đóng gói vì ứng dụng không dùng PDF và module này có điều khoản khác.
- `BUILD_LOCAL` yêu cầu bộ source/notices đã xác minh; kiểm kê resources không tự chứng minh frozen app hoạt động. Mỗi lượt đóng gói phải nằm trong quyền người dùng đã cấp; lỗi phát hiện sau build phải được báo cáo trước lượt tiếp theo.
- `onnxruntime.quantization` báo thiếu `onnx` khi collect submodules. Ứng dụng chỉ inference model có sẵn; không dùng quantizer/training. Không thêm ONNX training stack chỉ để tắt cảnh báo thu thập.
