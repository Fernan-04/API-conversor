"""Tests del pulido de "diseño IA" (§A-D del plan).

Cubren las transformaciones puras nuevas sin depender de PDFs concretos: reparación
de glifos cid, Title Case español, jerarquía del bloque de título, clave-valor ->
tabla, temario -> viñetas, autolink de URLs y puntajes **(N)**.
"""

from __future__ import annotations

from doc2md.config import Config
from doc2md.text_utils import (
    detect_language,
    fix_punct_spacing,
    normalize_unicode,
    title_case_en,
    title_case_es,
)
from doc2md.domain.markdown_renderer import render_markdown
from doc2md.domain.models import Document, Heading, ListBlock, Paragraph
from doc2md.adapters.outbound.pdf.reader import (
    _drop_furniture_label,
    _kv_to_table,
    _temario_to_list,
)
from doc2md.adapters.outbound.pdf.tables import (
    _append_scores,
    merge_tables_across_pages,
)
from doc2md.adapters.outbound.pdf.extract import Block


# --------------------------------------------------------------------------- #
# §E — glifos cid
# --------------------------------------------------------------------------- #

def test_cid_repair_maps_latin1():
    assert normalize_unicode("espec(cid:237)ficos") == "específicos"


def test_cid_repair_drops_control_codes():
    assert normalize_unicode("a(cid:0)b") == "ab"


# --------------------------------------------------------------------------- #
# §A2 — Title Case español
# --------------------------------------------------------------------------- #

def test_titlecase_uppercase_heading():
    assert title_case_es("FUNDAMENTACIÓN") == "Fundamentación"
    assert title_case_es("AVANCE DE PROYECTO FINAL 1") == "Avance de Proyecto Final 1"


def test_titlecase_keeps_acronyms_and_numbers():
    assert title_case_es("MODELO UML") == "Modelo UML"
    assert title_case_es("EVALUACIÓN PC2") == "Evaluación PC2"


def test_titlecase_leaves_mixed_case_untouched():
    s = "Análisis y diseño de sistemas de información"
    assert title_case_es(s) == s


# --------------------------------------------------------------------------- #
# §B4 — clave-valor -> tabla
# --------------------------------------------------------------------------- #

def test_kv_block_becomes_table():
    text = ("1.1 Carrera: Ingeniería de Software 1.2 Créditos: 4 "
            "1.3 Horas semanales: 4")
    table = _kv_to_table(text, Config())
    assert table is not None
    assert table.rows[0] == ["Campo", "Detalle"]
    assert ["1.1 Carrera", "Ingeniería de Software"] in table.rows
    assert ["1.2 Créditos", "4"] in table.rows


def test_kv_ignores_normal_prose():
    text = ("Este curso le permitirá al estudiante desarrollar habilidades. "
            "En primer lugar, establecer el diagnóstico situacional.")
    assert _kv_to_table(text, Config()) is None


# --------------------------------------------------------------------------- #
# §B5 — temario -> viñetas
# --------------------------------------------------------------------------- #

def test_temario_splits_on_sentences_and_dashes():
    text = ("Definición de sistemas, ciclo de vida. Modelos de desarrollo: "
            "Cascada, RUP. -Especificación de Requerimientos -Matriz")
    lst = _temario_to_list(text, Config())
    assert lst is not None
    assert lst.items[0].startswith("Definición de sistemas")
    assert "Especificación de Requerimientos" in lst.items
    assert "Matriz" in lst.items


def test_temario_single_item_stays_none():
    assert _temario_to_list("Un solo tema sin separadores claros", Config()) is None


# --------------------------------------------------------------------------- #
# §D8 — autolink de URLs
# --------------------------------------------------------------------------- #

def test_autolink_biblioteca_url():
    doc = Document(sections=[[Paragraph(
        text="Referencia. https://tubiblioteca.utp.edu.pe/opac?id=1"
    )]])
    md = render_markdown(doc, Config())
    assert "[Ver en biblioteca](https://tubiblioteca.utp.edu.pe/opac?id=1)" in md


def test_autolink_generic_url_uses_host():
    doc = Document(sections=[[Paragraph(text="Ver https://example.com/x")]])
    md = render_markdown(doc, Config())
    assert "[example.com](https://example.com/x)" in md


def test_autolink_off_keeps_plain_url():
    doc = Document(sections=[[Paragraph(text="Ver https://example.com/x")]])
    md = render_markdown(doc, Config(autolink_urls=False))
    assert "https://example.com/x" in md and "](http" not in md


# --------------------------------------------------------------------------- #
# §C — puntajes de rúbrica
# --------------------------------------------------------------------------- #

def test_append_scores_formats_bold_parens():
    row = ["Criterio", "Def", "nivel A", "nivel B"]
    _append_scores(row, ["5", "3"], Config())
    assert row == ["Criterio", "Def", "nivel A **(5)**", "nivel B **(3)**"]


def test_orphan_score_row_recovered_across_pages():
    prev = Block(kind="table", top=0.0, rows=[
        ["Criterio", "Def", "nivel A", "nivel B"],
        ["Fila", "d", "descripción A", "descripción B"],
    ])
    orphan = Block(kind="table", top=0.0, rows=[["", "", "5", "3"]])
    pages = [[prev], [orphan]]
    merge_tables_across_pages(pages, Config(), lambda _m: None)
    # Los puntajes huérfanos se anexan a la última fila de la tabla anterior.
    assert pages[0][0].rows[-1] == ["Fila", "d", "descripción A **(5)**", "descripción B **(3)**"]


# --------------------------------------------------------------------------- #
# §Ronda 6 — espaciado de puntuación
# --------------------------------------------------------------------------- #

def test_fix_punct_spacing_removes_space_before_close():
    assert fix_punct_spacing("aprendizaje , creatividad") == "aprendizaje, creatividad"
    assert fix_punct_spacing("Empower Youth SV .") == "Empower Youth SV."
    assert fix_punct_spacing("¿Cómo estás ?") == "¿Cómo estás?"


def test_fix_punct_spacing_removes_space_after_open():
    assert fix_punct_spacing("texto ( aclaración) fin") == "texto (aclaración) fin"


def test_fix_punct_spacing_leaves_normal_text_untouched():
    s = "Un párrafo normal, sin espacios raros. Punto final."
    assert fix_punct_spacing(s) == s


# --------------------------------------------------------------------------- #
# §Ronda 6 — detección de idioma
# --------------------------------------------------------------------------- #

def test_detect_language_spanish():
    text = ("El Hackatón Internacional de Innovación Educativa Juvenil 2026 "
            "es una experiencia virtual de aprendizaje para jóvenes de El "
            "Salvador y de otros países que podrán desarrollar soluciones.")
    assert detect_language(text) == "es"


def test_detect_language_english():
    text = ("This syllabus describes the course objectives and the topics "
            "that will be covered during the semester, along with the "
            "assessment criteria that students should be aware of.")
    assert detect_language(text) == "en"


def test_detect_language_defaults_to_spanish_on_short_text():
    assert detect_language("Hi") == "es"


# --------------------------------------------------------------------------- #
# §Ronda 6 — Title Case en inglés
# --------------------------------------------------------------------------- #

def test_titlecase_en_uppercase_heading():
    assert title_case_en("COURSE OBJECTIVES") == "Course Objectives"
    assert title_case_en("OVERVIEW OF THE PROJECT") == "Overview of the Project"


def test_titlecase_en_keeps_first_and_last_capitalized():
    # "of"/"the" van en minúscula EN MEDIO, pero la última palabra siempre
    # se capitaliza aunque sea una palabra menor.
    assert title_case_en("A GUIDE TO THE FUTURE OF") == "A Guide to the Future Of"


def test_titlecase_en_leaves_mixed_case_untouched():
    s = "Introduction to Systems Analysis"
    assert title_case_en(s) == s


# --------------------------------------------------------------------------- #
# §Ronda 6 — tabla clave-valor bilingüe
# --------------------------------------------------------------------------- #

def test_kv_table_header_in_english():
    text = ("1.1 Career: Software Engineering 1.2 Credits: 4 "
            "1.3 Weekly hours: 4")
    table = _kv_to_table(text, Config(), lang="en")
    assert table is not None
    assert table.rows[0] == ["Field", "Detail"]


# --------------------------------------------------------------------------- #
# §Ronda 6 — autolink bilingüe (vía Document.language)
# --------------------------------------------------------------------------- #

def test_autolink_biblioteca_url_in_english_document():
    doc = Document(
        sections=[[Paragraph(text="Reference. https://tubiblioteca.utp.edu.pe/opac?id=1")]],
        language="en",
    )
    md = render_markdown(doc, Config())
    assert "[View in library](https://tubiblioteca.utp.edu.pe/opac?id=1)" in md


# --------------------------------------------------------------------------- #
# §Ronda 6, 5.1 — fusión de títulos partidos en varias líneas
# --------------------------------------------------------------------------- #

def test_furniture_label_dropped_before_heading():
    elements = [Paragraph(text="COVER"), Heading(level=2, text="Título real")]
    out = _drop_furniture_label(elements, Config())
    assert out == [Heading(level=2, text="Título real")]


def test_furniture_label_kept_when_not_all_caps():
    """Un párrafo corto en minúscula/mixto NUNCA se trata como decoración
    (evita comerse contenido real como "Bibliografía")."""
    elements = [Paragraph(text="Bibliografía"), Heading(level=2, text="Otro título")]
    out = _drop_furniture_label(elements, Config())
    assert out == elements


def test_furniture_label_kept_when_ends_in_period():
    elements = [Paragraph(text="AVISO."), Heading(level=2, text="Título")]
    out = _drop_furniture_label(elements, Config())
    assert out == elements
