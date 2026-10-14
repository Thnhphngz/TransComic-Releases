"""Static B1 configuration inspection; does not execute build tools."""
import importlib.metadata as metadata
import importlib.util
import os
import platform
from pathlib import Path
import shutil
import sys


def discover(which=shutil.which):
    bases = [Path(os.environ.get(n, 'C:/missing')) for n in ('ProgramFiles', 'ProgramFiles(x86)', 'LOCALAPPDATA')]
    relative = {'git': ['Git/cmd/git.exe', 'Git/bin/git.exe', 'Programs/Git/cmd/git.exe'],
                'gh': ['GitHub CLI/gh.exe', 'Programs/GitHub CLI/gh.exe'],
                'ISCC': ['Inno Setup 6/ISCC.exe', 'Programs/Inno Setup 6/ISCC.exe']}
    inventory = {}
    # Registry locates tools installed outside the standard locations, without executing them.
    registered = []
    if sys.platform == 'win32':
        import winreg
        for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
            for key in (r'SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall', r'SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall'):
                try:
                    with winreg.OpenKey(hive, key) as parent:
                        for i in range(winreg.QueryInfoKey(parent)[0]):
                            try:
                                with winreg.OpenKey(parent, winreg.EnumKey(parent, i)) as entry:
                                    name = winreg.QueryValueEx(entry, 'DisplayName')[0]
                                    if any(x in name.lower() for x in ('git', 'inno setup')):
                                        location = winreg.QueryValueEx(entry, 'InstallLocation')[0]
                                        if location: registered.append(Path(location))
                            except OSError: pass
                except OSError: pass
    for name, paths in relative.items():
        found = which(name)
        candidates = [b/p for b in bases for p in paths]
        candidates += [b/p for b in registered for p in paths+[name+'.exe', 'cmd/'+name+'.exe']]
        if not found: found = next((str(p) for p in candidates if p.is_file()), None)
        inventory[name] = {'path': found, 'status': 'PATH' if which(name) else 'INSTALLED_OUTSIDE_PATH' if found else 'NOT_DETECTED_COMMON_PATHS_AND_REGISTRY'}
    sign = which('signtool')
    if not sign:
        for b in bases:
            kit = b/'Windows Kits/10/bin'
            if kit.is_dir():
                found = sorted(kit.glob('*/x64/signtool.exe'))
                if found: sign = str(found[-1]);break
    inventory['SignTool'] = {'path': sign, 'status': 'FOUND' if sign else 'NOT_DETECTED'}
    for name in ('PyInstaller', 'PySide6', 'cryptography', 'pytest'):
        try: inventory[name] = {'version': metadata.version(name), 'status': 'INSTALLED'}
        except metadata.PackageNotFoundError: inventory[name] = {'status': 'MISSING'}
    inventory['python'] = {'path': sys.executable, 'version': platform.python_version(), 'venv': sys.prefix != sys.base_prefix}
    inventory['platform'] = {'system': platform.system(), 'machine': platform.machine(), 'bits': 64 if sys.maxsize > 2**32 else 32}
    return inventory


def static_configuration(root):
    root = Path(root)
    required = ['run_transcomic.py', 'TransComic.spec', 'installer/TransComic.iss',
                'installer/TransComic.ico', 'requirements-release.lock', 'transcomic/ui/assets/transcomic-main.svg']
    missing = [name for name in required if not (root/name).is_file()]
    assets = list((root/'transcomic/ui/assets').glob('*.svg'))
    if any(p.is_symlink() for p in assets): missing.append('UNSAFE_RESOURCE_SYMLINK')
    deps = ['PySide6', 'httpx', 'charset-normalizer', 'python-docx', 'lxml', 'cryptography', 'PyInstaller']
    for dep in deps:
        try: metadata.version(dep)
        except metadata.PackageNotFoundError: missing.append('dependency:'+dep)
    lock=root/'requirements-release.lock'
    if lock.is_file():
        for line in lock.read_text(encoding='utf-8').splitlines():
            if not line or line.startswith('#'):continue
            if '==' not in line:missing.append('unpinned_dependency');continue
            name,pinned=line.split('==',1)
            try:
                if metadata.version(name)!=pinned:missing.append('lock_mismatch:'+name)
            except metadata.PackageNotFoundError:missing.append('lock_missing:'+name)
    plugin = importlib.util.find_spec('PySide6')
    qt_platform = Path(plugin.origin).parent/'plugins/platforms/qwindows.dll' if plugin else None
    return {'missing': missing, 'qt_windows_plugin': bool(qt_platform and qt_platform.is_file()),
            'resource_allowlist': [str(p.relative_to(root)) for p in assets],
            'root_data_glob': False, 'production_locked': True}


def exe_version_resource(version,original_filename='TransComic.exe'):
    from transcomic.release import version_outputs
    if original_filename not in ('TransComic.exe','TransComic-UpdateHelper.exe'):raise ValueError('Unapproved executable metadata name')
    info = version_outputs(version)
    return "VSVersionInfo(ffi=FixedFileInfo(filevers={0}, prodvers={0}, mask=0x3f, flags=0x0, OS=0x40004, fileType=0x1, subtype=0x0, date=(0,0)), kids=[StringFileInfo([StringTable('040904B0', [StringStruct('FileVersion', '{1}'), StringStruct('ProductVersion', '{1}'), StringStruct('ProductName', 'TransComic'), StringStruct('OriginalFilename', '{2}')])]), VarFileInfo([VarStruct('Translation', [1033, 1200])])])".format(info['exe_tuple'], version,original_filename)
