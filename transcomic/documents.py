"""Lossless TXT import and export rules."""
from __future__ import annotations

import codecs
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path

from charset_normalizer import from_bytes


class EncodingChoiceRequired(ValueError):
    """A legacy encoding needs explicit user confirmation."""

    def __init__(self, suggestion: str | None = None):
        self.suggestion = suggestion
        super().__init__(f"Confirm text encoding (suggested: {suggestion or 'unknown'})")


@dataclass(frozen=True)
class TextLine:
    text: str
    ending: str


@dataclass(frozen=True)
class ImportedText:
    lines: tuple[TextLine, ...]
    encoding: str
    raw: bytes


def split_lines(text: str) -> tuple[TextLine, ...]:
    if not text:
        return ()
    parts = re.findall(r"([^\r\n]*)(\r\n|\r|\n|$)", text)
    return tuple(TextLine(body, ending) for body, ending in parts if body or ending)


def decode_txt(raw: bytes, encoding: str | None = None) -> ImportedText:
    if encoding is None:
        if raw.startswith(codecs.BOM_UTF8):
            encoding = "utf-8-sig"
        elif raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
            encoding = "utf-16"
        else:
            if b"\x00" in raw:
                even = raw[0::2].count(0)
                odd = raw[1::2].count(0)
                raise EncodingChoiceRequired("utf-16-le" if odd > even else "utf-16-be")
            try:
                raw.decode("utf-8", errors="strict")
                encoding = "utf-8"
            except UnicodeDecodeError:
                suggestion = from_bytes(raw).best()
                raise EncodingChoiceRequired(suggestion.encoding if suggestion else None)
    text = raw.decode(encoding, errors="strict")
    if "\ufffd" in text:
        raise ValueError("Decoded text contains replacement characters")
    return ImportedText(split_lines(text), encoding, raw)


def import_txt(path: str | Path, encoding: str | None = None) -> ImportedText:
    return decode_txt(Path(path).read_bytes(), encoding)


def translatable(text: str) -> bool:
    return bool(re.search(r"[^\W\d_]", text, flags=re.UNICODE))


def preserve_edge_space(source: str, translated: str) -> str:
    leading = re.match(r"^[ \t]*", source).group()
    trailing = re.search(r"[ \t]*$", source).group()
    return leading + translated.strip(" \t") + trailing


def render_export(lines: list[dict]) -> tuple[bytes, int]:
    from .status import usable
    missing = 0
    pieces = []
    for line in lines:
        if any('\r' in (line.get(field) or '') or '\n' in (line.get(field) or '') for field in ('source','translation')):
            raise ValueError('A TXT unit cannot contain embedded physical line breaks')
        src = line["source"]
        if not translatable(src):
            value = src
        elif usable(line):
            value = preserve_edge_space(src, line["translation"])
        else:
            missing += 1
            value = src
        pieces.append(value + line["ending"])
    return "".join(pieces).encode("utf-8"), missing


def atomic_export(path: str | Path, content: bytes, overwrite: bool = False) -> None:
    target = Path(path)
    if target.exists() and not overwrite:
        raise FileExistsError(target)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=target.parent, prefix=f".{target.name}.", suffix=".tmp", delete=False) as output:
            temporary = Path(output.name)
            output.write(content)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
