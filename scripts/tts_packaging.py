"""Future isolated packaging resource audit; importing this never builds an EXE."""
from importlib import metadata,util
from pathlib import Path

PACKAGES=('kokoro_onnx','onnxruntime','numpy','soundfile','lameenc','phonemizer',
          'espeakng_loader','misaki','fugashi','unidic_lite','jaconv','jieba','pypinyin',
          'cn2an','psutil','ordered_set','regex')
CUDA_PACKAGES=('nvidia.cuda_runtime','nvidia.cublas','nvidia.cudnn','nvidia.cufft',
               'nvidia.curand','nvidia.cuda_nvrtc','nvidia.nvjitlink')
# The frozen GUI uses the existing independent interpreter over stdio. Keep
# inference libraries out of that process; source execution remains unchanged.
FROZEN_EXCLUDES=('kokoro_onnx','onnxruntime','phonemizer','espeakng_loader',
                 'misaki','fugashi','unidic_lite','jaconv','jieba','pypinyin',
                 'cn2an','nvidia','torch','transformers')
GUI_PACKAGES=('numpy','soundfile','lameenc','psutil')
UNUSED_NATIVE={'qpdf.dll','qt6pdf.dll','qt6virtualkeyboard.dll',
               'qtvirtualkeyboardplugin.dll','qtvirtualkeyboard.pyd','nvcuda.dll','nvml.dll'}
REVIEWED_QT={'qt6core.dll','qt6gui.dll','qt6widgets.dll','qt6multimedia.dll',
             'qt6multimediawidgets.dll','qt6network.dll','qt6opengl.dll',
             'qt6qml.dll','qt6qmlmeta.dll','qt6qmlmodels.dll','qt6qmlworkerscript.dll',
             'qt6quick.dll','qt6svg.dll','qt6test.dll'}


def filter_native(entries):
    return [entry for entry in entries if Path(entry[0]).name.lower() not in UNUSED_NATIVE]


def audit_payload(directory):
    """Audit the actual result before ISCC, including auto-collected Qt plugins."""
    native=[p for p in Path(directory).rglob('*') if p.suffix.lower() in ('.dll','.pyd')]
    for path in native:
        name=path.name.lower()
        if (name in UNUSED_NATIVE or (name.startswith('qt6') and name not in REVIEWED_QT)
            or any(v in name for v in ('onnxruntime','cublas','cudnn','nvrtc','cufft','curand','nvjitlink','espeak'))):
            raise ValueError('UNREVIEWED_NATIVE_PAYLOAD: '+name)
    return dict(native_files=len(native),qt_libraries=sorted(p.name for p in native if p.name.lower().startswith('qt6')))


def audit():
    missing=[n for n in PACKAGES if util.find_spec(n) is None]
    runtimes=[]
    for name in ('onnxruntime','onnxruntime-directml','onnxruntime-gpu'):
        try:runtimes.append((name,metadata.version(name)))
        except metadata.PackageNotFoundError:pass
    if any(name=='onnxruntime-gpu' for name,_ in runtimes):
        for name in CUDA_PACKAGES:
            try:found=util.find_spec(name)
            except ModuleNotFoundError:found=None
            if found is None:missing.append(name)
    return dict(missing=missing,runtimes=runtimes,ready=not missing and len(runtimes)==1,
                license_gate='Review GPL phonemizer/eSpeak and LGPL LAME/libsndfile plus dictionary source notices before distribution')


def resources():
    result=audit()
    if not result['ready']:raise RuntimeError('TTS_PACKAGING_DEPENDENCIES: '+str(result))
    if any(name!='onnxruntime' for name,_ in result['runtimes']):raise RuntimeError('TTS_CPU_BUILD_REQUIRED: build base Installer in isolated CPU environment; CUDA belongs in the managed runtime')
    from PyInstaller.utils.hooks import collect_all,copy_metadata
    datas=[];binaries=[];hidden=['PySide6.QtMultimedia']
    packages=GUI_PACKAGES
    for package in packages:
        d,b,h=collect_all(package);datas+=d;binaries+=b;hidden+=h
    for name in ('soundfile','lameenc','numpy','psutil'):
        datas+=copy_metadata(name)
    calibration=Path(__file__).resolve().parents[1]/'transcomic/tts/calibration.json'
    if calibration.is_file():datas.append((str(calibration),'transcomic/tts'))
    descriptor=calibration.with_name('gpu-pack.json')
    if descriptor.is_file():datas.append((str(descriptor),'transcomic/tts'))
    from transcomic.tts.managed_runtime import WORKER_FILES
    datas.append((str(calibration.with_name('setup-catalog.json')),'transcomic/tts'))
    for name in WORKER_FILES:datas.append((str(calibration.with_name(name)),'transcomic/tts/worker_source'))
    notices=calibration.parents[2]/'docs'
    for name in ('tts-licenses.md','tts-third-party-notices.md'):
        datas.append((str(notices/name),'transcomic/tts/notices'))
    from PySide6 import __file__ as qt_module
    plugins=Path(qt_module).parent/'plugins'/'multimedia'
    binaries.extend((str(path),'PySide6/plugins/multimedia') for path in plugins.glob('*.dll'))
    # Qt's hook collects the FFmpeg DLLs required by its multimedia backend.
    # Explicitly audit the packaged tree with WAV/MP3 playback before release.
    return datas,binaries,sorted(set(hidden))


if __name__=='__main__':
    import json
    print(json.dumps(audit(),indent=2))
