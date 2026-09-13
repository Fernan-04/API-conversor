"""Tests del lector de HTML pegado (§Ronda 6, "Pegar texto").

Cubre el HTML que el navegador adjunta al portapapeles al copiar desde una
web, Google Docs, Notion o Word: títulos, negrita/cursiva/enlaces inline,
listas anidadas, tablas, bloques de código y la trampa de Google Docs
(`<b style="font-weight:normal">` envolviendo todo el documento).
"""

from __future__ import annotations

from doc2md import convert
from doc2md.config import Config


def _convert(html: str) -> str:
    return convert(html.encode("utf-8"), Config(), filename="pegado.html")


# --------------------------------------------------------------------------- #
# Estructura básica: títulos, párrafos, listas, tabla
# --------------------------------------------------------------------------- #

def test_headings_by_level():
    md = _convert("<h1>Título</h1><h2>Subtítulo</h2><p>Texto normal.</p>")
    assert "# Título" in md
    assert "## Subtítulo" in md
    assert "Texto normal." in md


def test_bold_italic_inline():
    md = _convert("<p>Texto con <b>negrita</b> y <i>cursiva</i>.</p>")
    assert "**negrita**" in md
    assert "*cursiva*" in md


def test_link_becomes_markdown_link():
    md = _convert('<p>Visita <a href="https://example.com">nuestra web</a>.</p>')
    assert "[nuestra web](https://example.com)" in md


def test_link_with_hash_href_ignored():
    """Un enlace ancla (#section) o javascript: no debe convertirse en link."""
    md = _convert('<p>Ver <a href="#top">arriba</a> o <a href="javascript:void(0)">aquí</a>.</p>')
    assert "](#" not in md and "](javascript" not in md
    assert "arriba" in md and "aquí" in md


def test_nested_lists():
    html = (
        "<ul><li>Uno</li><li>Dos"
        "<ul><li>Dos-A</li><li>Dos-B</li></ul>"
        "</li><li>Tres</li></ul>"
    )
    md = _convert(html)
    assert "- Uno" in md
    assert "- Dos" in md
    assert "  - Dos-A" in md
    assert "  - Dos-B" in md
    assert "- Tres" in md


def test_ordered_list():
    md = _convert("<ol><li>Primero</li><li>Segundo</li></ol>")
    assert md.count("1. Primero") == 1
    assert "1. Segundo" in md


def test_table_with_header():
    html = (
        "<table><tr><th>Fase</th><th>Fecha</th></tr>"
        "<tr><td>Inicio</td><td>2026-01-01</td></tr></table>"
    )
    md = _convert(html)
    assert "| Fase | Fecha |" in md
    assert "| Inicio | 2026-01-01 |" in md


def test_table_wrapped_in_tbody_thead():
    html = (
        "<table><thead><tr><th>A</th><th>B</th></tr></thead>"
        "<tbody><tr><td>1</td><td>2</td></tr></tbody></table>"
    )
    md = _convert(html)
    assert "| A | B |" in md
    assert "| 1 | 2 |" in md


def test_code_block():
    md = _convert("<pre>def f():\n    return 1</pre>")
    assert "```" in md
    assert "def f():" in md


def test_blockquote():
    md = _convert("<blockquote>Una cita célebre.</blockquote>")
    assert "> Una cita célebre." in md


def test_image_alt_text_preserved():
    md = _convert('<p>Mira <img src="x.png" alt="un diagrama"> esto.</p>')
    assert "[Imagen: un diagrama]" in md


def test_scripts_and_styles_are_stripped():
    html = "<p>Texto real</p><script>alert('x')</script><style>.a{color:red}</style>"
    md = _convert(html)
    assert "Texto real" in md
    assert "alert" not in md and "color:red" not in md


# --------------------------------------------------------------------------- #
# Contenedores: div con bloques anidados vs. div de texto plano
# --------------------------------------------------------------------------- #

def test_div_wrapping_multiple_blocks_is_transparent():
    html = "<div><h2>Sección</h2><p>Párrafo dentro del div.</p></div>"
    md = _convert(html)
    assert "## Sección" in md
    assert "Párrafo dentro del div." in md


def test_div_with_only_inline_text_becomes_paragraph():
    md = _convert("<div>Solo texto <b>en negrita</b> dentro de un div.</div>")
    assert "**en negrita**" in md


# --------------------------------------------------------------------------- #
# Trampa de Google Docs: <b style="font-weight:normal"> envuelve TODO
# --------------------------------------------------------------------------- #

def test_google_docs_wrapper_is_not_treated_as_bold():
    html = (
        '<b style="font-weight:normal;" id="docs-internal-guid-abc123">'
        "<p><span>Texto normal, no en negrita.</span></p>"
        '<p><span style="font-weight:700">Esto sí es negrita.</span></p>'
        "</b>"
    )
    md = _convert(html)
    assert "**Texto normal" not in md
    assert "**Esto sí es negrita.**" in md


# --------------------------------------------------------------------------- #
# Idioma del documento (autolink bilingüe vía Document.language)
# --------------------------------------------------------------------------- #

def test_english_document_detected_and_titlecased():
    html = (
        "<h1>THIS SYLLABUS DESCRIBES THE COURSE</h1>"
        "<p>This course covers the topics that students should learn during "
        "the semester, along with the assessment criteria used by the "
        "instructor to evaluate their progress and understanding.</p>"
    )
    md = _convert(html)
    # Title Case en inglés: "the"/"of" en minúscula en medio del título.
    assert "# This Syllabus Describes the Course" in md


def test_spanish_document_stays_default():
    html = (
        "<h1>ESTE ES UN DOCUMENTO EN ESPAÑOL</h1>"
        "<p>Este curso cubre los temas que los estudiantes deben aprender "
        "durante el semestre, junto con los criterios de evaluación que el "
        "profesor usa para valorar su progreso y comprensión del curso.</p>"
    )
    md = _convert(html)
    assert "# Este Es un Documento en Español" in md
