# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import json
root=Path(SPECPATH)
marker=root/'.build-local.json'
if not marker.is_file() or json.loads(marker.read_text(encoding='utf8')).get('permission')!='BUILD_LOCAL':
    raise RuntimeError('STAGE_A_LOCKED: use the isolated reviewed BUILD_LOCAL entry point')
from transcomic.version import VERSION
from scripts.release_config import exe_version_resource
from PyInstaller.utils.win32.versioninfo import VSVersionInfo, FixedFileInfo, StringFileInfo, StringTable, StringStruct, VarFileInfo, VarStruct

# Same inputs, exclusions and onefile options as the original helper Analysis.
# A new process releases the GUI module graph before analyzing the helper.
helper_analysis=Analysis(
    [str(root/'scripts/update_helper.py')],
    pathex=[str(root)],binaries=[],hiddenimports=[],hookspath=[],
    hooksconfig={},runtime_hooks=[],excludes=['pytest','tests','PySide6','tkinter'],
    noarchive=False,optimize=0,
)
helper_pyz=PYZ(helper_analysis.pure)
helper_exe=EXE(
    helper_pyz,helper_analysis.scripts,helper_analysis.binaries,helper_analysis.datas,[],
    name='TransComic-UpdateHelper',console=False,debug=False,upx=False,
    icon=str(root/'installer/TransComic.ico'),version=eval(exe_version_resource(VERSION,'TransComic-UpdateHelper.exe')),
)
