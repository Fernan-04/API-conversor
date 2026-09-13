"""Test de calidad sobre un PDF de diseño real (§Ronda 6, banco de calibración).

`hackaton-2026.pdf` es un documento maquetado (Canva-style) con: títulos
decorativos "negrita falsa" (glifos duplicados), un título de portada partido
en 4 líneas visuales, tablas de 2 columnas, y una página cuyo contenido
(Art. 7) es una imagen a página completa SIN capa de texto. Sirve para
verificar de punta a punta las correcciones de precisión de la Ronda 6.

Se salta si `pdfs/hackaton-2026.pdf` no está en el repo local (no se
versiona, pesa ~6 MB); ver `conftest.requires_hackaton`.
"""

from __future__ import annotations

import re

import pdfplumber
import pytest

from conftest import HACKATON, HACKATON_REFERENCE, requires_hackaton

from doc2md import convert
from doc2md.adapters.outbound.pdf import ocr as ocr_mod
from doc2md.config import Config
from doc2md.text_utils import normalize_unicode


def _words(text: str) -> set[str]:
    return set(re.findall(r"\w+", normalize_unicode(text).lower()))


def _pdf_words(path) -> set[str]:
    # `dedupe_chars` (igual que el pipeline): sin esto, la "negrita falsa" de
    # este PDF deja glifos duplicados en el texto crudo ("aarrttiiffiicciiaall"
    # en vez de "artificial"), que no son palabras reales y no deben contar
    # como "perdidas" cuando el pipeline las arregla correctamente.
    with pdfplumber.open(str(path)) as pdf:
        return _words("\n".join(
            pg.dedupe_chars(tolerance=1).extract_text() or "" for pg in pdf.pages
        ))


@pytest.fixture(scope="module")
def hackaton_md() -> str:
    return convert(HACKATON, Config())


@requires_hackaton
def test_no_duplicated_words_from_fake_bold(hackaton_md):
    """La "negrita falsa" (glifos dibujados dos veces) no debe dejar palabras
    duplicadas tipo "Hackatón Hackatón" (arreglado por `dedupe_chars`)."""
    assert not re.search(r"\b(\w{3,})\s+\1\b", hackaton_md, re.IGNORECASE)


@requires_hackaton
def test_no_space_before_punctuation(hackaton_md):
    assert " ," not in hackaton_md
    assert " ." not in hackaton_md


@requires_hackaton
def test_cover_title_is_a_single_heading(hackaton_md):
    """El título de portada, partido en 4 líneas visuales en el PDF, debe salir
    como UN solo título (no 4 fragmentos en niveles distintos)."""
    assert "## Hackatón Internacional de Innovación Educativa Juvenil 2026" in hackaton_md
    # Ningún fragmento suelto del título como línea de título independiente.
    assert not re.search(r"^#+ Internacional de\s*$", hackaton_md, re.MULTILINE)
    assert not re.search(r"^#+ Juvenil 2026\s*$", hackaton_md, re.MULTILINE)


@requires_hackaton
def test_clean_data_tables_kept(hackaton_md):
    """Las tablas de 2 columnas (antes descartadas por `table_min_cols`) deben
    conservarse vía la vía alterna de "tabla de datos limpia"."""
    assert "| Puntaje |" in hackaton_md
    assert "| Fase | Fecha |" in hackaton_md
    assert "| TOTAL | 100 puntos |" in hackaton_md


@requires_hackaton
def test_decorative_tab_labels_removed(hackaton_md):
    """Las etiquetas de pestaña/portada ("COVER", "N°7"...) no deben aparecer
    como línea propia; un párrafo legítimo como "Bibliografía" no se toca
    (cubierto en test_polish.py con un caso sintético)."""
    assert not re.search(r"^COVER\s*$", hackaton_md, re.MULTILINE)
    assert not re.search(r"^N°\d+\s*$", hackaton_md, re.MULTILINE)


@requires_hackaton
def test_missing_image_page_never_lost_silently(hackaton_md):
    """La página 11 (Art. 7, imagen a página completa) nunca desaparece en
    silencio: o se recupera su texto por OCR, o se inserta un aviso visible."""
    has_ocr_text = "formativo" in hackaton_md.lower() and "27" in hackaton_md
    has_placeholder = "no se pudo extraer" in hackaton_md
    assert has_ocr_text or has_placeholder, (
        "La página de la imagen del Art. 7 desapareció sin aviso ni OCR"
    )
    if not ocr_mod.available():
        assert "página 11" in hackaton_md


@requires_hackaton
def test_word_coverage_against_source_pdf(hackaton_md):
    """El word-set del PDF real (capa de texto) está casi completo en el .md.

    No exige el 100%: el texto de la imagen del Art. 7 no forma parte de la
    capa de texto del PDF (por eso no cuenta aquí; lo cubre el test de arriba).
    """
    pdf_words = _pdf_words(HACKATON)
    missing = pdf_words - _words(hackaton_md)
    assert len(missing) / len(pdf_words) <= 0.02, sorted(missing)[:30]


@requires_hackaton
def test_close_to_ai_reference_design(hackaton_md):
    """La salida heurística cubre la mayoría del vocabulario que produjo una
    IA (`Mejorar/CLAUDE`) al convertir el mismo PDF — sin usar IA."""
    if not HACKATON_REFERENCE.exists():
        pytest.skip("falta la referencia versionada hackaton-2026.claude-reference.md")
    reference_words = _words(HACKATON_REFERENCE.read_text(encoding="utf-8"))
    missing = reference_words - _words(hackaton_md)
    assert len(missing) / len(reference_words) <= 0.15, sorted(missing)[:40]
