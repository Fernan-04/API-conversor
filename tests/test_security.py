"""Tests del endurecimiento de seguridad inspirado en el análisis de markitdown:

  - guarda anti zip-bomb (OOXML) ;
  - validación por firma (magic bytes) ;
  - saneo del nombre en Content-Disposition ;
  - API key opcional ;
  - límite de nº de archivos por petición.
"""

from __future__ import annotations

import io
import zipfile

import pytest
from fastapi.testclient import TestClient

from doc2md.adapters.inbound import http as http_mod
from doc2md.adapters.inbound.http import _content_disposition, _safe_stem, app
from doc2md.adapters.outbound._signatures import ensure_signature
from doc2md.adapters.outbound._zip_guard import ensure_safe_zip
from doc2md.config import Config
from doc2md.domain.errors import CorruptFileError, FileTooLargeError

client = TestClient(app)


# --------------------------------------------------------------------------- #
# Guarda anti zip-bomb
# --------------------------------------------------------------------------- #

def _zip_with(entries: list[tuple[str, bytes]], compression=zipfile.ZIP_DEFLATED) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression) as zf:
        for name, content in entries:
            zf.writestr(name, content)
    return buf.getvalue()


def test_zip_guard_entry_count():
    data = _zip_with([(f"f{i}.txt", b"x") for i in range(5)])
    with pytest.raises(FileTooLargeError):
        ensure_safe_zip(data, Config(zip_max_entries=3))


def test_zip_guard_uncompressed_size():
    data = _zip_with([("big.bin", b"A" * 5000)], compression=zipfile.ZIP_STORED)
    with pytest.raises(FileTooLargeError):
        ensure_safe_zip(data, Config(zip_max_uncompressed_bytes=1000))


def test_zip_guard_ratio():
    # 8 MB de un patrón muy compresible -> ratio altísimo, comprimido > 4 KB.
    data = _zip_with([("z.bin", b"ABCD" * (2 * 1024 * 1024))])
    with pytest.raises(FileTooLargeError):
        ensure_safe_zip(data, Config(zip_max_ratio=5,
                                     zip_max_uncompressed_bytes=10**9))


def test_zip_guard_passes_normal(docx_bytes):
    # Un DOCX real generado por la fixture NO debe dispararse.
    ensure_safe_zip(docx_bytes, Config())


def test_zip_guard_bad_zip():
    with pytest.raises(CorruptFileError):
        ensure_safe_zip(b"no soy un zip", Config())


# --------------------------------------------------------------------------- #
# Firma (magic bytes)
# --------------------------------------------------------------------------- #

def test_signature_mismatch_raises():
    with pytest.raises(CorruptFileError):
        ensure_signature(b"<html>no soy pdf</html>", ".pdf")


def test_signature_ok_pdf():
    ensure_signature(b"%PDF-1.7\n...", ".pdf")   # no lanza


def test_signature_text_skipped():
    ensure_signature(b"cualquier cosa", ".txt")  # texto: sin firma, no lanza


# --------------------------------------------------------------------------- #
# Saneo de Content-Disposition
# --------------------------------------------------------------------------- #

def test_safe_stem_strips_dangerous_chars():
    assert _safe_stem('a"b\r\n\\c/d') == "abcd"
    assert _safe_stem("   ...   ") == "documento"


def test_content_disposition_no_header_injection():
    header = _content_disposition('mal\r\nSet-Cookie: x.pdf', ".md")
    assert "\r" not in header and "\n" not in header
    assert 'filename="' in header


# --------------------------------------------------------------------------- #
# API key opcional
# --------------------------------------------------------------------------- #

def test_api_key_enforced(monkeypatch):
    monkeypatch.setattr(http_mod, "API_KEY", "secreto")
    c = TestClient(http_mod.app)
    files = {"files": ("d.txt", b"hola", "text/plain")}

    r = c.post("/convert", files=files)
    assert r.status_code == 401
    assert r.json()["code"] == "INFRA_UNAUTHORIZED"

    r = c.post("/convert", files=files, headers={"X-API-Key": "secreto"})
    assert r.status_code == 200

    r = c.post("/convert", files=files, headers={"X-API-Key": "malo"})
    assert r.status_code == 401


def test_api_key_disabled_by_default():
    # Sin API_KEY configurada (estado normal), /convert sigue abierto.
    r = client.post("/convert", files={"files": ("d.txt", b"hola", "text/plain")})
    assert r.status_code == 200


def test_health_open_without_key(monkeypatch):
    monkeypatch.setattr(http_mod, "API_KEY", "secreto")
    c = TestClient(http_mod.app)
    assert c.get("/health").status_code == 200


# --------------------------------------------------------------------------- #
# Límite de nº de archivos
# --------------------------------------------------------------------------- #

def test_too_many_files():
    files = [("files", (f"f{i}.txt", b"hola", "text/plain")) for i in range(21)]
    r = client.post("/convert", files=files)
    assert r.status_code == 413
    assert r.json()["code"] == "INFRA_TOO_MANY_FILES"
