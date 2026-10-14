import codecs
from pathlib import Path

import pytest

from transcomic.documents import EncodingChoiceRequired, atomic_export, decode_txt, render_export, split_lines, translatable


@pytest.mark.parametrize("raw,encoding", [
    ("Xin chào\r\nHello\nHalo".encode(), "utf-8"),
    (codecs.BOM_UTF8 + "Tiếng Việt\n".encode(), "utf-8-sig"),
    ("日本語\r\n".encode("utf-16"), "utf-16"),
])
def test_import_roundtrip(raw, encoding):
    doc = decode_txt(raw)
    assert doc.encoding == encoding
    assert "".join(x.text + x.ending for x in doc.lines).encode(encoding) == raw


def test_mixed_newlines_and_edges():
    lines = split_lines(" \tHello\t \r\n\r\n...\nHalo")
    assert [(x.text, x.ending) for x in lines] == [(" \tHello\t ", "\r\n"), ("", "\r\n"), ("...", "\n"), ("Halo", "")]
    assert [translatable(x.text) for x in lines] == [True, False, False, True]
    rows = [dict(source=x.text, ending=x.ending, translation="Xin chào" if i == 0 else None, state="done" if i == 0 else "pending") for i, x in enumerate(lines)]
    content, missing = render_export(rows)
    assert content.decode() == " \tXin chào\t \r\n\r\n...\nHalo"
    assert missing == 1


def test_empty_and_many_lines():
    assert decode_txt(b"").lines == ()
    text = "á\r\n" * 3000
    assert len(split_lines(text)) == 3000
    assert "".join(x.text + x.ending for x in split_lines(text)) == text


def test_stale_translation_is_not_exported():
    content, missing = render_export([dict(source="New source", ending="", translation="Old translation", state="stale")])
    assert content == b"New source" and missing == 1


def test_uncertain_encoding_requires_choice():
    with pytest.raises(EncodingChoiceRequired):
        decode_txt(b"\xe9")
    assert decode_txt(b"\xe9", "cp1252").lines[0].text == "é"
    with pytest.raises(UnicodeDecodeError):
        decode_txt(b"\xe9", "utf-8")


def test_export_atomic_no_implicit_overwrite(tmp_path: Path):
    target = tmp_path / "out.txt"
    atomic_export(target, b"first")
    with pytest.raises(FileExistsError):
        atomic_export(target, b"second")
    assert target.read_bytes() == b"first"
    atomic_export(target, b"second", True)
    assert target.read_bytes() == b"second"
