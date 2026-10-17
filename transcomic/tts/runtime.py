"""Runtime diagnostics separate model availability from successful inference."""
import importlib
import importlib.metadata
import sys
import traceback
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler

REQUIRED=('onnxruntime','kokoro_onnx','numpy','soundfile','lameenc','phonemizer','espeakng_loader')


def logger(directory):
    log=logging.getLogger('transcomic.tts.'+str(Path(directory).absolute()))
    if not log.handlers:
        Path(directory).mkdir(parents=True,exist_ok=True)
        handler=RotatingFileHandler(Path(directory)/'technical.log',maxBytes=4*1024**2,backupCount=3,encoding='utf8')
        handler.setFormatter(logging.Formatter('%(asctime)s %(levelname)s %(message)s'));log.addHandler(handler);log.setLevel(logging.INFO);log.propagate=False
    return log


def diagnostics():
    data=dict(executable=sys.executable,prefix=sys.prefix,path=list(sys.path),modules={},missing=[],providers=[],error=None)
    for name in REQUIRED:
        try:
            module=importlib.import_module(name);data['modules'][name]=str(getattr(module,'__file__',''))
            if name=='onnxruntime':data['providers']=module.get_available_providers()
        except (ImportError,OSError) as exc:data['missing'].append(name);data['error']=str(exc)
    variants=[]
    for name in ('onnxruntime','onnxruntime-gpu','onnxruntime-directml'):
        try:variants.append((name,importlib.metadata.version(name)))
        except importlib.metadata.PackageNotFoundError:pass
    data['runtimes']=variants;data['compatible']=not data['missing'] and len(variants)==1
    return data


def friendly(exc):
    text=str(exc)
    if isinstance(exc,ModuleNotFoundError) or 'No module named' in text:
        return 'Không khởi tạo được bộ máy Kokoro. Thiếu thành phần runtime. Mở Cài đặt → Tải model để thử lại.'
    if isinstance(exc,FileNotFoundError):return 'Không tìm thấy file hoặc thư mục cần thiết. Kiểm tra ổ đĩa, model hoặc liên kết lại thư mục audio.'
    if isinstance(exc,PermissionError):return 'Không có quyền ghi hoặc file đang được sử dụng. Đóng audio đang mở và kiểm tra quyền thư mục.'
    if isinstance(exc,MemoryError):return 'Không đủ RAM/VRAM. Giảm số đoạn đồng thời trong Cài đặt hoặc đóng tác vụ khác rồi thử lại.'
    if isinstance(exc,OSError) and getattr(exc,'errno',None)==28:return 'Ổ đĩa đã hết dung lượng. Giải phóng dung lượng rồi tiếp tục.'
    if 'ONNXRuntimeError' in text or 'CUDA' in text or 'DirectML' in text:return 'Thiết bị không khởi tạo hoặc tổng hợp được audio. Kiểm tra thông báo CPU dự phòng và xem Chi tiết kỹ thuật hoặc log trong Cài đặt.'
    return text if not text.startswith(('ValueError:','RuntimeError:','ModuleNotFoundError:')) else text.split(': ',1)[-1]
