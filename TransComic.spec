# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import json
marker=Path(SPECPATH)/'.build-local.json'
if not marker.is_file() or json.loads(marker.read_text(encoding='utf8')).get('permission')!='BUILD_LOCAL':
    raise RuntimeError('STAGE_A_LOCKED: use the isolated reviewed BUILD_LOCAL entry point')
from transcomic.version import VERSION
from scripts.release_config import exe_version_resource
from PySide6 import __file__ as qt_module
from PyInstaller.utils.hooks import collect_submodules
from scripts.tts_packaging import resources, FROZEN_EXCLUDES, filter_native
tts_datas,tts_binaries,tts_hidden=resources()
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct
root = Path(SPECPATH)
qt_plugins = Path(qt_module).parent/'plugins'
# Only these plugin families; no root-directory data glob or personal files.
plugins = [(str(p), 'PySide6/plugins/'+family) for family in ('platforms','imageformats','styles')
           for p in (qt_plugins/family).glob('*.dll') if p.name!='qpdf.dll']


a = Analysis(
    [str(root/'run_transcomic.py')],
    pathex=[str(root)],
    binaries=plugins+tts_binaries,
    datas=[(str(p), 'transcomic/ui/assets') for p in (root/'transcomic/ui/assets').glob('*.svg')]+tts_datas,
    hiddenimports=collect_submodules('docx')+['PySide6.QtSvg','PySide6.QtNetwork','charset_normalizer']+tts_hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['pytest','tests','scripts','tkinter','PySide6.QtPdf','PySide6.QtPdfWidgets','PySide6.QtVirtualKeyboard']+list(FROZEN_EXCLUDES),
    noarchive=False,
    optimize=0,
)
# Qt's general image hook also discovers qpdf; PDF is not an application format
# and QtPdf has a different community license. Do not ship that unused module.
a.binaries=filter_native(a.binaries)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TransComic',
    icon=str(root/'installer/TransComic.ico'),
    version=eval(exe_version_resource(VERSION)),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app_distribution = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name='TransComic')

# External helper ships beside the app; native execution requires installed identity and Safe Exit.
helper_analysis = Analysis(
    [str(root/'scripts/update_helper.py')],
    pathex=[str(root)], binaries=[], hiddenimports=[], hookspath=[],
    hooksconfig={}, runtime_hooks=[], excludes=['pytest','tests','PySide6','tkinter'],
    noarchive=False, optimize=0,
)
helper_pyz = PYZ(helper_analysis.pure)
helper_exe = EXE(
    helper_pyz, helper_analysis.scripts, helper_analysis.binaries, helper_analysis.datas, [],
    name='TransComic-UpdateHelper', console=False, debug=False, upx=False,
    icon=str(root/'installer/TransComic.ico'), version=eval(exe_version_resource(VERSION,'TransComic-UpdateHelper.exe')),
)
