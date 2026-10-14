"""Conservative, position-preserving DOCX text-unit mapping.

The original OOXML package is kept as the template. Only word/document.xml is
rewritten; tables, drawings, relationships and media remain in place.
"""
from __future__ import annotations

import io
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from docx import Document
from lxml import etree

from .documents import preserve_edge_space, translatable


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
A = "http://schemas.openxmlformats.org/drawingml/2006/main"
XML = "http://www.w3.org/XML/1998/namespace"


def q(namespace: str, local: str) -> str:
    return f"{{{namespace}}}{local}"


TEXT = q(W, "t")
PARAGRAPH = q(W, "p")
DELIMITERS = {q(W, local) for local in ("br", "cr", "tab", "drawing", "pict", "object", "sym")}
UNSUPPORTED = {q(W, local) for local in (
    "txbxContent", "fldChar", "instrText", "fldSimple", "sdt", "ins", "del",
    "delText", "hyperlink", "altChunk", "ruby", "commentRangeStart",
    "commentRangeEnd", "commentReference", "footnoteReference", "endnoteReference",
)} | {q(M, "oMath"), q(M, "oMathPara"), q(MC, "AlternateContent")}
STRUCTURAL_TAGS = {q(W, local) for local in ("p", "tbl", "tr", "tc", "br", "cr", "tab", "drawing", "pict", "object", "sym")}


class UnsafeDocx(ValueError):
    """The document contains text structures this mapper cannot translate safely."""


@dataclass(frozen=True)
class DocxUnit:
    locator: str
    text: str


@dataclass(frozen=True)
class ImportedDocx:
    raw: bytes
    units: tuple[DocxUnit, ...]


@dataclass
class _Segment:
    text_nodes: list[etree._Element]
    delimiter: etree._Element | None

    @property
    def text(self) -> str:
        return "".join(node.text or "" for node in self.text_nodes)


def _xml(data: bytes) -> etree._Element:
    parser = etree.XMLParser(resolve_entities=False, no_network=True, remove_blank_text=False, huge_tree=False)
    return etree.fromstring(data, parser=parser)


def _segments(paragraph: etree._Element) -> list[_Segment]:
    result: list[_Segment] = []
    current: list[etree._Element] = []
    for element in paragraph.iter():
        if element.tag == TEXT:
            if "\n" in (element.text or "") or "\r" in (element.text or ""):
                raise UnsafeDocx("DOCX chứa ký tự xuống dòng trực tiếp trong w:t")
            current.append(element)
        elif element.tag in DELIMITERS:
            result.append(_Segment(current, element))
            current = []
    result.append(_Segment(current, None))
    return result


def _paragraphs(root: etree._Element) -> list[etree._Element]:
    body = root.find(q(W, "body"))
    if body is None:
        raise UnsafeDocx("DOCX không có phần thân tài liệu Word")
    return list(body.iter(PARAGRAPH))


def _validate_parts(archive: zipfile.ZipFile, root: etree._Element) -> None:
    names = archive.namelist()
    if len(names) != len(set(names)):
        raise UnsafeDocx("DOCX có tên phần ZIP trùng nhau")
    for element in root.iter():
        if element.tag in UNSUPPORTED:
            raise UnsafeDocx(f"DOCX chứa cấu trúc Word chưa hỗ trợ: {etree.QName(element).localname}")
        if element.tag == q(A, "t"):
            raise UnsafeDocx("DOCX chứa chữ trong shape/drawing chưa hỗ trợ")
    for name in names:
        lower = name.lower()
        if not lower.startswith("word/") or not lower.endswith(".xml") or lower == "word/document.xml":
            continue
        part = _xml(archive.read(name))
        if any(element.tag in {TEXT, q(W, "instrText"), q(W, "delText"), q(A, "t")} and (element.text or "").strip()
               for element in part.iter()):
            raise UnsafeDocx(f"DOCX chứa chữ ở phần chưa hỗ trợ: {name}")


def _read_root(raw: bytes) -> etree._Element:
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            if "word/document.xml" not in archive.namelist() or "[Content_Types].xml" not in archive.namelist():
                raise UnsafeDocx("Tệp không phải DOCX hợp lệ")
            if sum(info.file_size for info in archive.infolist()) > 512 * 1024 * 1024:
                raise UnsafeDocx("DOCX quá lớn để xử lý an toàn")
            if archive.testzip() is not None:
                raise UnsafeDocx("DOCX có phần ZIP bị lỗi")
            root = _xml(archive.read("word/document.xml"))
            _validate_parts(archive, root)
            return root
    except (zipfile.BadZipFile, etree.XMLSyntaxError) as exc:
        raise UnsafeDocx(f"Không đọc được cấu trúc DOCX: {type(exc).__name__}") from exc


def inspect_docx(raw: bytes) -> ImportedDocx:
    root = _read_root(raw)
    try:
        Document(io.BytesIO(raw))
    except Exception as exc:
        raise UnsafeDocx(f"Thư viện Word không mở được DOCX: {type(exc).__name__}") from exc
    units: list[DocxUnit] = []
    for paragraph_index, paragraph in enumerate(_paragraphs(root)):
        for segment_index, segment in enumerate(_segments(paragraph)):
            units.append(DocxUnit(f"{paragraph_index}:{segment_index}", segment.text))
    return ImportedDocx(raw, tuple(units))


def import_docx(path: str | Path) -> ImportedDocx:
    return inspect_docx(Path(path).read_bytes())


def _set_segment(paragraph: etree._Element, segment: _Segment, value: str) -> None:
    if "\r" in value or "\n" in value:
        raise UnsafeDocx("Một đơn vị DOCX không được chứa xuống dòng mới")
    if any((ord(char) < 32 and char != "\t") or 0xD800 <= ord(char) <= 0xDFFF or ord(char) in (0xFFFE, 0xFFFF) for char in value):
        raise UnsafeDocx("Bản dịch chứa ký tự không hợp lệ trong XML Word")
    if segment.text_nodes:
        first = segment.text_nodes[0]
        first.text = value
        if value.startswith((" ", "\t")) or value.endswith((" ", "\t")):
            first.set(q(XML, "space"), "preserve")
        else:
            first.attrib.pop(q(XML, "space"), None)
        for node in segment.text_nodes[1:]:
            node.text = ""
    elif value:
        if segment.delimiter is not None:
            parent = segment.delimiter.getparent()
            node = etree.Element(TEXT)
            node.text = value
            if value.startswith((" ", "\t")) or value.endswith((" ", "\t")):
                node.set(q(XML, "space"), "preserve")
            if parent.tag == q(W, "r"):
                parent.insert(parent.index(segment.delimiter), node)
            else:
                run = etree.Element(q(W, "r"))
                run.append(node)
                parent.insert(parent.index(segment.delimiter), run)
        else:
            run = etree.SubElement(paragraph, q(W, "r"))
            node = etree.SubElement(run, TEXT)
            node.text = value
            if value.startswith((" ", "\t")) or value.endswith((" ", "\t")):
                node.set(q(XML, "space"), "preserve")


def _signature(root: etree._Element) -> tuple[tuple[str, int], ...]:
    counts = {tag: 0 for tag in STRUCTURAL_TAGS}
    for element in root.iter():
        if element.tag in counts:
            counts[element.tag] += 1
    return tuple(sorted(counts.items()))


def render_docx(snapshot: bytes, rows: list[dict]) -> tuple[bytes, int]:
    from .status import usable
    root = _read_root(snapshot)
    before = _signature(root)
    paragraphs = _paragraphs(root)
    mapped = {}
    for row in rows:
        locator = row.get("locator")
        if not isinstance(locator, str) or locator in mapped or not re.fullmatch(r"\d+:\d+", locator):
            raise UnsafeDocx("Ánh xạ vị trí DOCX thiếu hoặc trùng")
        mapped[locator] = row
    expected = sum(len(_segments(paragraph)) for paragraph in paragraphs)
    if len(mapped) != expected:
        raise UnsafeDocx("Số đơn vị DOCX không khớp snapshot")
    missing = 0
    for paragraph_index, paragraph in enumerate(paragraphs):
        for segment_index, segment in enumerate(_segments(paragraph)):
            locator = f"{paragraph_index}:{segment_index}"
            row = mapped.get(locator)
            if row is None:
                raise UnsafeDocx(f"Thiếu vị trí DOCX: {locator}")
            source = row["source"]
            if not translatable(source):
                value = source
            elif usable(row):
                value = preserve_edge_space(source, row["translation"])
            else:
                value = source
                missing += 1
            if value != segment.text:
                _set_segment(paragraph, segment, value)
    if _signature(root) != before:
        raise UnsafeDocx("Cấu trúc đoạn/bảng/hình/ngắt dòng đã thay đổi; chặn xuất")
    xml_bytes = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(snapshot)) as source_zip, zipfile.ZipFile(output, "w") as target_zip:
        for info in source_zip.infolist():
            target_zip.writestr(info, xml_bytes if info.filename == "word/document.xml" else source_zip.read(info.filename))
    result = output.getvalue()
    try:
        Document(io.BytesIO(result))
    except Exception as exc:
        raise UnsafeDocx(f"DOCX xuất ra không mở lại được: {type(exc).__name__}") from exc
    if _signature(_read_root(result)) != before:
        raise UnsafeDocx("Kiểm tra sau xuất phát hiện thay đổi cấu trúc DOCX")
    return result, missing
