# TransComic — Windows distribution, source and replacement information

TransComic 1.1.0, 17 October 2026. This document accompanies the
component licenses in `ThirdParty/notices` and the actual source archives in
`ThirdParty/sources`. `manifest.json` records every delivered file's SHA-256;
`source-provenance.json` records the resolved upstream commits and URLs.
There is no promise to supply source later: the source media accompanies this
Installer and its public corresponding-source asset.

## Shared libraries and your rights

TransComic uses community PySide6/shiboken/Qt 6.11.1 under LGPLv3, FFmpeg 7.1.3
under LGPLv2.1-or-later and its incorporated licenses, SoundFile's libsndfile
1.2.2 under LGPLv2.1-or-later, and lameenc 1.9.0 under LGPLv3-or-later.
Each component retains its own copyright, license and warranty disclaimer.
These libraries are not endorsed by their authors for this application.

You may inspect, modify, rebuild, replace and redistribute these libraries
under their licenses. Reverse engineering of TransComic for debugging your
modifications to LGPL libraries is permitted. No application condition limits
those rights. TransComic's other source is not relicensed by this notice.

The application is packaged as a directory. Close TransComic, copy the install
directory to a writable test directory and retain a backup. Replace matching
ABI-compatible DLLs/PYD modules under `_internal/PySide6`,
`_internal/_soundfile_data`, or `_internal/lameenc*.pyd`. Keep filenames, module
layout, x64 architecture and CPython ABI. Launch `TransComic.exe` from the copy.
No signature whitelist, encrypted library archive or application checksum
gate rejects modified GUI/audio libraries. An application update can replace
installed libraries; keep your modified copy separately. This is a developer
replacement procedure, not a requirement for ordinary use.

Qt source archives include qtbase, qtdeclarative, qtmultimedia, qtsvg and
qtshadertools; PySide/shiboken source and Qt's provisioning/build scripts are
provided too. Use their included CMake/build instructions with MSVC x64 and
matching configuration; build shared libraries. PySide's source contains its
binding generator and build scripts. The original FFmpeg binary reports
7.1.3 and its configuration is saved in the source media. It enables shared
libraries, disables static linking, and does not enable GPL/nonfree codecs.
Qt's pinned `coin/provisioning/common/windows/install-ffmpeg.ps1` and shared
configuration are included in the qt5 archive. FFmpeg's zlib source is provided.

lameenc's pinned CMakeLists, LAME source and patch script are supplied. Its
Windows build links LAME into the replaceable extension; rebuilding the entire
extension from the supplied source permits changes to that static portion.
SoundFile source, its pinned binary-builder repository, libsndfile and codec
sources/build information accompany it. Preserve notices when redistributing.
Certifi's unmodified MPL source is also supplied.

## Independent TTS worker

The frozen GUI does not bundle/import phonemizer, eSpeak, Kokoro or ONNX Runtime.
It starts the existing separately installed CPython worker and exchanges text,
configuration and PCM audio through the documented JSON/stdio protocol in
`worker/managed_worker.py` (protocol 2, at most two lanes). No GUI internals or
shared Python objects cross that process boundary.

The eight engine/worker source files and `windows_bootstrap.py` delivered in `worker/` are supplied under
GPL-3.0-or-later for this independent TTS worker. This grant applies to these
worker copies, including their local adaptations; it does not change the
license of the TransComic GUI, translation code or updater. The complete worker
source, artifact catalog, upstream phonemizer source and buildable eSpeak
source/build scripts are delivered here. GPL texts are included in the notices
and eSpeak/phonemizer sources. The sources are not obfuscated.

The eSpeak DLL matches the loader v0.1.0 Windows artifact byte-for-byte, and all
364 data files match that release's data artifact. The release's eSpeak source
commit is `685480238072018edfc0e4f3d85e131c278c2ccf`; the loader build scripts
and wrapper MIT source are supplied separately. Use that loader's build.sh /
CMake workflow with that eSpeak source rather than upstream main.

For an independent worker installation, unpack the verified official embedded
Python, place the catalog's wheels under `python/Lib/site-packages`, use the
catalog's `_pth` configuration, and put these source files under
`worker/transcomic/tts` (`managed_worker.py` is the entry point one level above).
Empty `__init__.py` files define the packages. On Windows run the supplied
`windows_bootstrap.py` with the worker entry path as its argument, from the
runtime root, using the embedded interpreter's `-I -B` flags. It qualifies import
paths for Windows DLL loading and uses relative eSpeak/MeCab data paths, without
changing installed package files. Additional arguments may identify directories
containing compatible Microsoft C++ runtime DLLs. The frozen application passes
its `_internal` and `_internal/PySide6` directories: the embedded Python ZIP
does not contain all C++ DLLs required by ORT. Handles remain alive in the worker;
neither System32 nor PATH is modified. These are the existing, unmodified CRT
files already shipped with the application, not a new system installation.
The ordinary application prepares
this automatically; its runtime manager requires original pinned files for
the normal safety-checked cache. For your modified worker, use a separate copy
and the protocol directly; the GPL source may be run independently and modified
without the GUI's integrity policy. No activation key or signing key is needed.

## Automatically downloaded components

The Installer contains no model weights, voices, embedded TTS interpreter,
eSpeak binary, ORT binary or NVIDIA CUDA/cuDNN DLLs. The one-click setup downloads
the exact pinned official artifacts into the user's data directory. Existing
SHA-256, size, traversal and real-probe checks remain enabled. Upstream wheel
metadata, licenses and notices are retained when extracting the runtime.

Model and voice assets: Apache-2.0, onnx-community/Kokoro-82M-v1.0-ONNX revision
1939ad2a8e416c0acfeecc08a694d14ef25f2231. Kokoro wrapper: MIT. ORT: MIT and its
third-party notices. These licenses do not replace phonemizer/eSpeak's GPL.

The optional NVIDIA pack is downloaded directly from NVIDIA's PyPI uploads,
not redistributed as a stand-alone TransComic DLL bundle. Its components remain
under NVIDIA's terms, not GPL. They are optional for user-side GPU execution;
CPU execution remains available. Before downloading/using NVIDIA software,
review and agree to the CUDA 12.9.1 and cuDNN 9.27 terms supplied in `notices`:
https://docs.nvidia.com/cuda/archive/12.9.1/eula/index.html
https://docs.nvidia.com/deeplearning/cudnn/backend/v9.27.0/reference/eula.html
No NVIDIA driver or Toolkit is installed. No NVIDIA trademark sponsorship is
claimed. The application does not relicense proprietary NVIDIA components.

Windows Python is obtained from python.org with its original PSF license and
Microsoft additional conditions. The original Windows `PC/crtlicense.txt` is
included here. Microsoft code is unmodified, runs only on Windows, retains
notices and is not used in a malicious, deceptive or unlawful program. These
restrictions apply to Microsoft distributable code, not to the open source
components. Distributors and end users must observe those conditions. No DLL
is copied from a download mirror, System32 or a developer's CUDA installation.

## Build and preservation

Only the isolated CPU build interpreter is used. Its exact package inventory
and the installed payload are recorded by BUILD_LOCAL. CUDA development pins
are unchanged. Runtime/model/voice/history/settings/audio are outside the
application directory. Installer replacement does not remove those directories.
This source media contains no user database, API key, imported document or audio.
