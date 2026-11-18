"""Inspect direct children of an Automation folder without opening documents."""
from dataclasses import dataclass
from pathlib import Path

from ..capcut.media import IMAGES, natural_key, probe
from .repository import source_key
from .validation import check_current


WORD = '.docx'
DOCUMENTS = frozenset((WORD, '.txt'))


@dataclass(frozen=True)
class FolderImages:
    images: tuple[str, ...]
    words: tuple[str, ...]
    invalid: tuple[str, ...]
    duplicates: int


def word_notice(count):
    return f'⚠ {count} file Word · chỉ nhập ảnh' if count >= 2 else ''


def word_names(folder, cancelled=None):
    names = []
    for entry in Path(folder).iterdir():
        check_current(cancelled)
        if entry.suffix.lower() == WORD and entry.is_file():
            names.append(entry.name)
    return tuple(sorted(names, key=natural_key))


def scan_folder(folder, *, cancelled=None, progress=None):
    folder = Path(folder)
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

    images, invalid, seen = [], [], set()
    duplicates = 0
    for index, path in enumerate(sorted(candidates, key=lambda p: natural_key(p.name)), 1):
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
        if progress and (index == len(candidates) or index % 25 == 0):
            progress(index, len(candidates))
    return FolderImages(tuple(images), tuple(p.name for p in sorted(words, key=lambda p: natural_key(p.name))),
                        tuple(invalid), duplicates)
