from __future__ import annotations

import io
import sys
import zipfile

import pytest

from rapport_api.security import AuditInputError, decode_uploaded_text
from rapport_auditor.document import InvalidDocxError, extract_docx_text
from rapport_auditor import audit, revise


W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def _docx(body: str) -> bytes:
    return _docx_xml(f'<w:document xmlns:w="{W}"><w:body>{body}<w:sectPr/></w:body></w:document>')


def _docx_xml(xml: str | bytes) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("word/document.xml", xml)
    return output.getvalue()


def _paragraph(text: str) -> str:
    return f"<w:p>{text}</w:p>"


def _run(text: str) -> str:
    return f"<w:r><w:t>{text}</w:t></w:r>"


def _decode(raw: bytes, *, max_chars: int = 250_000, max_bytes: int = 1_000_000, max_lines: int = 10_000):
    return decode_uploaded_text(
        filename="draft.docx",
        mimetype="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        raw=raw,
        max_chars=max_chars,
        max_bytes=max_bytes,
        max_lines=max_lines,
    )


def test_docx_extracts_body_paragraphs_and_table_cells_in_reading_order():
    raw = _docx(
        _paragraph(_run("Résumé fictif"))
        + '<w:tbl><w:tr><w:tc>'
        + _paragraph(_run("This chapter presents") + "<w:r><w:tab/></w:r>" + _run("a method."))
        + "</w:tc><w:tc>"
        + _paragraph(_run("Deuxième cellule."))
        + "</w:tc></w:tr></w:tbl>"
        + _paragraph(_run("Final paragraph") + "<w:r><w:br/></w:r>" + _run("second line."))
    )

    document = _decode(raw)

    assert document.source_format == "docx"
    assert document.text == "Résumé fictif\nThis chapter presents\ta method.\tDeuxième cellule.\nFinal paragraph\nsecond line."


def test_docx_extracts_inserted_wording_but_skips_deleted_tracked_text():
    document = _decode(
        _docx(
            _paragraph(
                '<w:del><w:r><w:delText>deleted wording</w:delText></w:r></w:del>'
                '<w:ins><w:r><w:t>current wording</w:t></w:r></w:ins>'
            )
        )
    )

    assert document.text == "current wording"


@pytest.mark.parametrize(
    ("limits", "expected_code"),
    [
        ({"max_chars": 4}, "input_too_large"),
        ({"max_lines": 1}, "too_many_lines"),
    ],
)
def test_docx_extracted_text_uses_existing_limits(limits, expected_code):
    raw = _docx(_paragraph(_run("Résumé")) + _paragraph(_run("Second line")))

    with pytest.raises(AuditInputError) as error:
        _decode(raw, **limits)

    assert error.value.code == expected_code


def test_docx_mime_must_match_and_malformed_zip_gets_specific_error():
    with pytest.raises(AuditInputError) as mime_error:
        decode_uploaded_text(
            filename="draft.docx",
            mimetype="text/plain",
            raw=_docx(_paragraph(_run("Synthetic text"))),
            max_chars=250_000,
            max_bytes=1_000_000,
            max_lines=10_000,
        )
    assert mime_error.value.code == "mismatched_file_type"

    with pytest.raises(AuditInputError) as invalid_error:
        _decode(b"PK\x03\x04not a zip archive")
    assert invalid_error.value.code == "invalid_docx"


def test_docx_missing_body_and_dtd_are_rejected():
    with pytest.raises(InvalidDocxError):
        extract_docx_text(_docx_xml(f'<w:document xmlns:w="{W}"><w:sectPr/></w:document>'))
    with pytest.raises(InvalidDocxError):
        dtd = (
            f'<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE w:document '
            f'[<!ENTITY x "expanded">]><w:document xmlns:w="{W}"><w:body>'
            '<w:p><w:r><w:t>&x;</w:t></w:r></w:p></w:body></w:document>'
        ).encode("utf-16")
        extract_docx_text(
            _docx_xml(dtd)
        )


@pytest.mark.parametrize("encoding", ["wat", "UTF-32"])
def test_docx_unknown_or_unsupported_xml_encoding_is_rejected(encoding):
    xml = (
        f'<?xml version="1.0" encoding="{encoding}"?>'
        f'<w:document xmlns:w="{W}"><w:body><w:p/></w:body></w:document>'
    ).encode("ascii")

    with pytest.raises(InvalidDocxError):
        extract_docx_text(_docx_xml(xml))


def test_docx_extracted_utf8_bytes_limit_is_enforced():
    raw = _docx(_paragraph(_run("é" * 20_000)))
    assert len(raw) < 1_000

    with pytest.raises(AuditInputError) as error:
        _decode(raw, max_bytes=1_000)

    assert error.value.code == "input_too_large"


def test_docx_cli_previews_extracted_text_and_refuses_write(monkeypatch, tmp_path, capsys):
    path = tmp_path / "draft.docx"
    raw = _docx(_paragraph(_run("This chapter presents a fictional method.")))
    path.write_bytes(raw)

    monkeypatch.setattr(sys, "argv", ["revise", str(path)])
    assert revise.main() == 0
    assert "This chapter describes a fictional method." in capsys.readouterr().out

    monkeypatch.setattr(sys, "argv", ["revise", str(path), "--write"])
    with pytest.raises(SystemExit) as error:
        revise.main()
    assert error.value.code == 2
    assert path.read_bytes() == raw


def test_audit_cli_reads_docx_as_plain_text(monkeypatch, tmp_path, capsys):
    path = tmp_path / "draft.docx"
    path.write_bytes(_docx(_paragraph(_run("This chapter presents a fictional method."))))

    monkeypatch.setattr(sys, "argv", ["audit", str(path)])
    assert audit.main() == 0
    output = capsys.readouterr().out
    assert str(path) in output
    assert "Words: 6" in output
