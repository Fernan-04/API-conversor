"""Tests de la jerarquía de errores tipificados (§8.2)."""

from __future__ import annotations

import pytest

from doc2md import convert
from doc2md.adapters.outbound import router
from doc2md.config import Config
from doc2md.domain.errors import (
    CorruptFileError,
    InfrastructureError,
    UnsupportedFormatError,
)


def test_unsupported_format():
    with pytest.raises(UnsupportedFormatError) as exc:
        convert(b"cualquier cosa", Config(), filename="archivo.xyz")
    assert exc.value.code == "INFRA_UNSUPPORTED_FORMAT"
    assert exc.value.layer == "infrastructure"
    assert exc.value.http_status == 400


def test_corrupt_pdf():
    with pytest.raises(CorruptFileError) as exc:
        convert(b"esto no es un pdf", Config(), filename="roto.pdf")
    assert exc.value.code == "INFRA_CORRUPT_FILE"
    assert isinstance(exc.value, InfrastructureError)
    assert exc.value.http_status == 422


def test_corrupt_docx():
    with pytest.raises(CorruptFileError):
        convert(b"no es un docx", Config(), filename="roto.docx")


def test_bytes_without_filename():
    with pytest.raises(ValueError):
        convert(b"datos", Config())


def test_router_lists_supported():
    exts = router.supported_extensions()
    assert set(exts) == {
        ".pdf", ".docx", ".pptx", ".xlsx", ".txt", ".md", ".csv", ".tsv",
    }
