"""Tests de los lectores DOCX / PPTX / XLSX (Fase 1).

Las fixtures se generan al vuelo (ver conftest.py) porque no hay originales
reales de estos formatos en el repo.
"""

from __future__ import annotations

from doc2md import convert
from doc2md.config import Config


# --------------------------------------------------------------------------- #
# DOCX
# --------------------------------------------------------------------------- #

def test_docx_headings(docx_bytes):
    md = convert(docx_bytes, Config(), filename="doc.docx")
    assert "# Título Principal" in md
    assert "## Sección Uno" in md


def test_docx_paragraph_and_bold(docx_bytes):
    md = convert(docx_bytes, Config(), filename="doc.docx")
    assert "Este es un párrafo normal de introducción." in md
    assert "**Etiqueta importante**" in md


def test_docx_list(docx_bytes):
    md = convert(docx_bytes, Config(), filename="doc.docx")
    assert "- Primer ítem" in md
    assert "- Segundo ítem" in md


def test_docx_inline_bold_italic(docx_bytes):
    """Negrita y cursiva PARCIALES dentro de un párrafo (no todo el párrafo)."""
    md = convert(docx_bytes, Config(), filename="doc.docx")
    assert "Texto con **negrita** y *cursiva*." in md


def test_docx_hyperlink(docx_bytes):
    """Los hipervínculos se conservan como [texto](url) (antes se perdían)."""
    md = convert(docx_bytes, Config(), filename="doc.docx")
    assert "[nuestra web](https://example.com/x)" in md


def test_docx_numbered_list(docx_bytes):
    """Una lista con estilo 'List Number' se emite con marcador numerado."""
    md = convert(docx_bytes, Config(), filename="doc.docx")
    assert "1. Paso uno" in md
    assert "1. Paso dos" in md


def test_docx_table(docx_bytes):
    md = convert(docx_bytes, Config(), filename="doc.docx")
    assert "| A | B | C |" in md
    assert "| 1 | 2 | 3 |" in md


# --------------------------------------------------------------------------- #
# PPTX
# --------------------------------------------------------------------------- #

def test_pptx_title_as_heading(pptx_bytes):
    md = convert(pptx_bytes, Config(), filename="pres.pptx")
    assert "# Diapositiva de Prueba" in md


def test_pptx_bullets_and_notes(pptx_bytes):
    md = convert(pptx_bytes, Config(), filename="pres.pptx")
    assert "- Punto uno" in md
    assert "- Punto dos" in md
    # Notas del orador como bloque aparte.
    assert "Notas" in md
    assert "Nota del orador." in md


def test_pptx_table(pptx_bytes):
    md = convert(pptx_bytes, Config(), filename="pres.pptx")
    assert "| Col1 | Col2 |" in md
    assert "| x | y |" in md


def test_pptx_title_not_duplicated(pptx_bytes):
    """El título de la diapositiva sale UNA vez (como #), no repetido como párrafo.

    Regresión: python-pptx devuelve un wrapper distinto en cada acceso, así que
    comparar el shape del título con `is` fallaba y lo emitía dos veces.
    """
    md = convert(pptx_bytes, Config(), filename="pres.pptx")
    assert md.count("Diapositiva de Prueba") == 1
    assert "# Diapositiva de Prueba" in md


# --------------------------------------------------------------------------- #
# XLSX
# --------------------------------------------------------------------------- #

def test_xlsx_sheets_as_sections(xlsx_bytes):
    md = convert(xlsx_bytes, Config(), filename="libro.xlsx")
    assert "# Ventas" in md
    assert "# Resumen" in md


def test_xlsx_table_columns(xlsx_bytes):
    md = convert(xlsx_bytes, Config(), filename="libro.xlsx")
    assert "| Producto | Cantidad | Precio |" in md
    assert "| Manzana | 10 | 5 |" in md


def test_xlsx_row_limit():
    """El tope de filas recorta hojas enormes."""
    from openpyxl import Workbook
    import io

    wb = Workbook()
    ws = wb.active
    for i in range(50):
        ws.append([f"fila{i}", i])
    buf = io.BytesIO()
    wb.save(buf)

    md = convert(buf.getvalue(), Config(xlsx_max_rows=10), filename="big.xlsx")
    assert "fila9" in md
    assert "fila20" not in md


def test_xlsx_wide_sheet_truncated():
    """Una hoja muy ancha (tipo Gantt) se recorta a xlsx_max_cols con aviso."""
    from openpyxl import Workbook
    import io

    wb = Workbook()
    ws = wb.active
    ws.append([f"c{i}" for i in range(200)])   # 200 columnas de datos
    ws.append([str(i) for i in range(200)])
    buf = io.BytesIO()
    wb.save(buf)

    md = convert(buf.getvalue(), Config(xlsx_max_cols=20), filename="gantt.xlsx")
    assert "recortada a 20 de 200 columnas" in md
    # La cabecera de la tabla queda en 20 columnas (20 celdas + 2 bordes vacíos).
    header = next(l for l in md.splitlines() if l.startswith("| c0 "))
    assert header.count("|") == 21


def test_xlsx_empty_columns_dropped():
    """Las columnas totalmente vacías intercaladas se descartan."""
    from openpyxl import Workbook
    import io

    wb = Workbook()
    ws = wb.active
    ws.append(["A", None, None, "B"])     # dos columnas vacías en medio
    ws.append(["1", None, None, "2"])
    buf = io.BytesIO()
    wb.save(buf)

    md = convert(buf.getvalue(), Config(), filename="huecos.xlsx")
    assert "| A | B |" in md
    assert "| 1 | 2 |" in md
