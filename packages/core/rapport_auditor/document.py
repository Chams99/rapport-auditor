"""Bounded text extraction for supported document containers."""

from __future__ import annotations

from pathlib import Path
from xml.parsers import expat
import io
import zipfile
import zlib
from xml.etree import ElementTree


DOCX_XML_LIMIT = 8_000_000
DOCX_ENTRY_LIMIT = 10_000
DOCX_FILE_LIMIT = 1_000_000
_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


class InvalidDocxError(ValueError):
    """The input is not a readable Word document with a main body part."""


def read_docx_file(path: str | Path, *, max_bytes: int = DOCX_FILE_LIMIT) -> str:
    """Read and extract a DOCX with the same compressed-file cap as uploads."""
    try:
        source_path = Path(path)
        if source_path.stat().st_size > max_bytes:
            raise InvalidDocxError("document file is too large")
        with source_path.open("rb") as source:
            raw = source.read(max_bytes + 1)
        if len(raw) > max_bytes:
            raise InvalidDocxError("document file is too large")
    except OSError as exc:
        raise InvalidDocxError("document file could not be read") from exc
    return extract_docx_text(raw)


def extract_docx_text(raw: bytes) -> str:
    """Extract body paragraphs and table cells in document order as plain text.

    Paragraphs and table rows become lines; cells are separated by tabs.
    Formatting, headers, footers, comments, and footnotes are not extracted.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > DOCX_ENTRY_LIMIT:
                raise InvalidDocxError("document contains too many ZIP entries")
            if sum(item.filename == "[Content_Types].xml" for item in entries) != 1:
                raise InvalidDocxError("package content types are missing or duplicated")
            matches = [item for item in entries if item.filename == "word/document.xml"]
            if len(matches) != 1:
                raise InvalidDocxError("document body is missing or duplicated")
            info = matches[0]
            if info.flag_bits & 1:
                raise InvalidDocxError("encrypted documents are not supported")
            if info.file_size > DOCX_XML_LIMIT:
                raise InvalidDocxError("document body is too large")
            with archive.open(info) as source:
                xml = source.read(DOCX_XML_LIMIT + 1)
                if len(xml) > DOCX_XML_LIMIT or source.read(1):
                    raise InvalidDocxError("document body is too large")
    except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, RuntimeError, EOFError, NotImplementedError, zlib.error) as exc:
        raise InvalidDocxError from exc

    parser = expat.ParserCreate()

    def reject_declaration(*_args: object) -> None:
        raise InvalidDocxError("document body contains a DTD or entity declaration")

    parser.StartDoctypeDeclHandler = reject_declaration
    parser.EntityDeclHandler = reject_declaration
    parser.ExternalEntityRefHandler = lambda *_args: 0
    try:
        parser.Parse(xml, True)
        root = ElementTree.fromstring(xml)
    except InvalidDocxError:
        raise
    except (expat.ExpatError, ElementTree.ParseError, LookupError, ValueError) as exc:
        raise InvalidDocxError from exc

    body = root.find(f"{_W}body")
    if body is None:
        raise InvalidDocxError("document body is missing")

    def paragraph_text(paragraph: ElementTree.Element) -> str:
        parts: list[str] = []

        def collect(node: ElementTree.Element) -> None:
            if node.tag in {f"{_W}del", f"{_W}moveFrom"}:
                return
            if node.tag == f"{_W}t":
                parts.append(node.text or "")
            elif node.tag == f"{_W}tab":
                parts.append("\t")
            elif node.tag in {f"{_W}br", f"{_W}cr"}:
                parts.append("\n")

            for child in node:
                collect(child)

        collect(paragraph)
        return "".join(parts)

    def cell_text(cell: ElementTree.Element) -> str:
        blocks = []
        for child in cell:
            if child.tag == f"{_W}p":
                blocks.append(paragraph_text(child))
            elif child.tag == f"{_W}tbl":
                blocks.append(table_text(child))
        return "\n".join(blocks)

    def table_text(table: ElementTree.Element) -> str:
        rows = []
        for row in table.findall(f"{_W}tr"):
            rows.append("\t".join(cell_text(cell) for cell in row.findall(f"{_W}tc")))
        return "\n".join(rows)

    blocks = []
    for child in body:
        if child.tag == f"{_W}p":
            blocks.append(paragraph_text(child))
        elif child.tag == f"{_W}tbl":
            blocks.append(table_text(child))
    return "\n".join(blocks)
