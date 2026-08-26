"""Tests del lector PDF y regresión del motor (§9).

Guardián principal: la salida del PDF real `verbos-objetivos.pdf` no debe cambiar
tras el refactor a arquitectura hexagonal. Los tests de calibración del filtro de
tablas usan los dos PDFs opuestos del SPEC (§13.2) y se saltan si no están.
"""

from __future__ import annotations

import re
import socket
from pathlib import Path

import pdfplumber
import pytest

from conftest import (
    APF1,
    RUBRICA,
    VERBOS,
    VERBOS_EXPECTED,
    requires_apf1,
    requires_rubrica,
)

from doc2md import convert
from doc2md.adapters.inbound import cli
from doc2md.adapters.outbound.pdf.extract import extract_document
from doc2md.adapters.outbound.pdf.tables import select_tables
from doc2md.config import Config
from doc2md.text_utils import normalize_unicode


def _words(text: str) -> set[str]:
    # `normalize_unicode` repara los glifos `(cid:NNN)` a su carácter real, igual
    # que el pipeline, para comparar palabras reales contra reales (no el ruido).
    return set(re.findall(r"\w+", normalize_unicode(text).lower()))


def _pdf_words(path: Path) -> set[str]:
    with pdfplumber.open(str(path)) as pdf:
        return _words("\n".join(pg.extract_text() or "" for pg in pdf.pages))


# --------------------------------------------------------------------------- #
# Regresión: la salida no cambió con el refactor
# --------------------------------------------------------------------------- #

def test_output_matches_baseline():
    """La conversión del PDF real es idéntica al .md de referencia en markdown/."""
    baseline = VERBOS_EXPECTED.read_text(encoding="utf-8")
    assert convert(VERBOS, Config()) == baseline


def test_real_table_kept_verbos():
    """La tabla real de verbos (varias columnas) se conserva."""
    md = convert(VERBOS, Config())
    assert "| --- |" in md            # se emitió al menos una tabla
    assert "Analizar" in md


# --------------------------------------------------------------------------- #
# Garantía central: sin perder contenido (§9)
# --------------------------------------------------------------------------- #

def test_no_content_loss():
    """El conjunto de palabras del PDF está (casi por completo) en el .md."""
    cfg = Config(remove_repeated=False)
    md = convert(VERBOS, cfg)
    pdf_words = _pdf_words(VERBOS)
    missing = pdf_words - _words(md)
    assert len(missing) / len(pdf_words) <= 0.01, sorted(missing)


def test_no_network(monkeypatch):
    """La conversión se completa aunque crear sockets falle (sin red, §1)."""
    def boom(*_a, **_k):
        raise OSError("red deshabilitada en el test")

    monkeypatch.setattr(socket, "socket", boom)
    md = convert(VERBOS, Config())
    assert len(md) > 100


# --------------------------------------------------------------------------- #
# Lote y protección de archivos (§7, §8)
# --------------------------------------------------------------------------- #

def test_batch_continues_on_error(tmp_path):
    (tmp_path / "verbos.pdf").write_bytes(VERBOS.read_bytes())
    (tmp_path / "roto.pdf").write_bytes(b"esto no es un pdf")
    out = tmp_path / "out"

    code = cli.main([str(tmp_path), "-o", str(out)])
    assert code == 0                               # un archivo roto no aborta el lote
    assert (out / "verbos.md").exists()


def test_no_overwrite_by_default(tmp_path):
    (tmp_path / "verbos.pdf").write_bytes(VERBOS.read_bytes())
    out = tmp_path / "out"

    cli.main([str(tmp_path), "-o", str(out)])
    md_file = out / "verbos.md"
    md_file.write_text("EDICION MANUAL", encoding="utf-8")

    cli.main([str(tmp_path), "-o", str(out)])      # sin --overwrite
    assert md_file.read_text(encoding="utf-8") == "EDICION MANUAL"

    cli.main([str(tmp_path), "-o", str(out), "--overwrite"])
    assert md_file.read_text(encoding="utf-8") != "EDICION MANUAL"


# --------------------------------------------------------------------------- #
# Calibración del filtro de tablas (§5) — requiere los PDFs opuestos del SPEC
# --------------------------------------------------------------------------- #

@requires_rubrica
def test_layout_table_discarded():
    """La página HTML impresa NO produce una tabla gigante de una celda."""
    with pdfplumber.open(str(RUBRICA)) as pdf:
        page = pdf.pages[0]
        accepted = select_tables(page.find_tables(), page, Config(), lambda _m: None)
    assert len(accepted) == 1                      # el contenedor fue descartado
    assert len(accepted[0].rows[0]) >= 5           # la rúbrica conserva sus columnas

    md = convert(RUBRICA, Config())
    assert "| Criterio | Completo | En proceso 2 | En proceso 1 | Inicial |" in md


@requires_apf1
def test_real_table_kept_apf1():
    """La tabla de datos real de 6 columnas de APF1 se conserva."""
    with pdfplumber.open(str(APF1)) as pdf:
        page = pdf.pages[4]
        accepted = select_tables(page.find_tables(), page, Config(), lambda _m: None)
    assert len(accepted) == 1
    assert len(accepted[0].rows[0]) == 6
    assert accepted[0].rows[0][0] == "Criterio"


@requires_apf1
def test_apf1_single_clean_table():
    """APF1 sale como UNA tabla de 6 columnas, sin filas huérfanas ni separadores."""
    md = convert(APF1, Config())
    rows = []
    for line in md.splitlines():
        if line.startswith("|"):
            rows.append([c.strip() for c in line.strip().strip("|").split(" | ")])
    separators = [r for r in rows if all(c == "---" for c in r)]
    assert len(separators) == 1
    assert all(len(r) == 6 for r in rows), [len(r) for r in rows]
    assert "Planteamiento de alternativas" in md
