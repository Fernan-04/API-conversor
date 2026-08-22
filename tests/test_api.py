"""Tests de la API HTTP (Fase 2) con FastAPI TestClient.

Verifican el contrato de la API: .md en el cuerpo para un archivo, .zip para
varios, errores tipificados con su `code`, y el límite de tamaño. La garantía de
cero persistencia es estructural (todo en memoria); aquí se comprueba el
comportamiento observable.
"""

from __future__ import annotations

import io
import zipfile

from fastapi.testclient import TestClient

from conftest import VERBOS

from doc2md.adapters.inbound.http import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_convert_single_returns_markdown():
    with open(VERBOS, "rb") as f:
        r = client.post("/convert", files={"files": ("verbos.pdf", f, "application/pdf")})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert 'filename="verbos.md"' in r.headers["content-disposition"]
    assert "| --- |" in r.text


def test_convert_multiple_returns_zip(docx_bytes):
    files = [
        ("files", ("verbos.pdf", VERBOS.read_bytes(), "application/pdf")),
        ("files", ("doc.docx", docx_bytes,
                   "application/vnd.openxmlformats-officedocument.wordprocessingml.document")),
    ]
    r = client.post("/convert", files=files)
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(io.BytesIO(r.content))
    assert set(zf.namelist()) == {"verbos.md", "doc.md"}
    assert "# Título Principal" in zf.read("doc.md").decode("utf-8")


def test_convert_unsupported_format():
    r = client.post("/convert", files={"files": ("archivo.xyz", b"hola", "application/octet-stream")})
    assert r.status_code == 400
    assert r.json()["code"] == "INFRA_UNSUPPORTED_FORMAT"


def test_convert_corrupt_file():
    r = client.post("/convert", files={"files": ("roto.pdf", b"no es pdf", "application/pdf")})
    assert r.status_code == 422
    body = r.json()
    assert body["code"] == "INFRA_CORRUPT_FILE"
    assert body["layer"] == "infrastructure"


def test_convert_file_too_large():
    big = b"%PDF-1.4\n" + b"0" * (26 * 1024 * 1024)  # > 25 MB
    r = client.post("/convert", files={"files": ("grande.pdf", big, "application/pdf")})
    assert r.status_code == 413
    assert r.json()["code"] == "INFRA_FILE_TOO_LARGE"
