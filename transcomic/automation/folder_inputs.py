"""Inspect direct children of an Automation folder without opening documents."""
from dataclasses import asdict, dataclass, field
from pathlib import Path
from threading import Event
from uuid import uuid4

from ..capcut.media import IMAGES, natural_key, probe
from .repository import file_hash, source_key
from .validation import check_current, image_stamp


WORD = '.docx'
DOCUMENTS = frozenset((WORD, '.txt'))


@dataclass(frozen=True)
class FolderImages:
    images: tuple[str, ...]
    words: tuple[str, ...]
    invalid: tuple[str, ...]
    duplicates: int
    manifest: tuple[dict, ...] = ()
    stamp: tuple = ()

    @property
    def error(self):
        messages = []
        if self.invalid:
            messages.append(f'{len(self.invalid)} ảnh lỗi: ' + ', '.join(self.invalid[:5]))
        if self.duplicates:
            messages.append(f'{self.duplicates} đường dẫn ảnh trùng')
        return ' · '.join(messages)


@dataclass(eq=False)
class FolderDraft:
    workset: str
    path: Path
    id: str = field(default_factory=lambda: str(uuid4()))
    cancelled: Event = field(default_factory=Event)
    scan: FolderImages | None = None
    busy: bool = True
    state: str = 'folder_queued'
    status: str = 'Chờ quét'
    error: str = ''

    def row(self):
        count = len(self.scan.words) if self.scan else 0
        name = (f'⚠ {count} file Word' if count >= 2 else 'Chờ Word') if self.state == 'waiting_word' else self.path.name
        error = self.error or (self.scan.error if self.scan else '')
        if self.scan and not self.scan.images and not error:
            error = 'Không tìm thấy ảnh hợp lệ.'
        return dict(id=self.id, workset_id=self.workset, document_id=None, position=0,
                    path=str(self.path), translated=0, translation_total=0, waves=0,
                    data=dict(state=self.state, pending_name=name, scan_status=self.status,
                              image_folder=str(self.path), image_count=len(self.scan.images) if self.scan else 0,
                              image_word_count=count, error=error))


def word_notice(count):
    return f'⚠ {count} file Word' if count >= 2 else ''


def word_names(folder, cancelled=None):
    names = []
    for entry in Path(folder).iterdir():
        check_current(cancelled)
        if entry.suffix.lower() == WORD and entry.is_file():
            names.append(entry.name)
    return tuple(sorted(names, key=natural_key))


def scan_folder(folder, *, cancelled=None, progress=None, inspection=False):
    folder = Path(folder)
    stamp = image_stamp(folder, cancelled) if inspection else ()
    candidates = []
    words = []
    for entry in folder.iterdir():
        check_current(cancelled)
        suffix = entry.suffix.lower()
        if suffix not in IMAGES and suffix != WORD:
            continue
        if not entry.is_file():
            continue
        (words if suffix == WORD else candidates).append(entry)

    images, manifest, invalid, seen = [], [], [], set()
    duplicates = 0
    candidates.sort(key=lambda p: natural_key(p.name))
    for index, path in enumerate(candidates, 1):
        check_current(cancelled)
        key = source_key(path)
        if key in seen:
            duplicates += 1
        else:
            seen.add(key)
            media = probe(path, True)
            if media.error:
                invalid.append(path.name)
            else:
                images.append(media.path)
                if inspection:
                    manifest.append({**asdict(media), 'sha256': file_hash(path)})
        if progress and (index == len(candidates) or index % 25 == 0):
            progress(index, len(candidates))
    if inspection and stamp != image_stamp(folder, cancelled):
        raise ValueError('Ảnh trong thư mục đã thay đổi khi quét. Hãy thử lại.')
    return FolderImages(tuple(images), tuple(p.name for p in sorted(words, key=lambda p: natural_key(p.name))),
                        tuple(invalid), duplicates, tuple(manifest), stamp)
