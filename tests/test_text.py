"""Tests de los lectores nuevos: texto plano / Markdown y CSV / TSV."""

from __future__ import annotations

from doc2md import convert
from doc2md.config import Config


# --------------------------------------------------------------------------- #
# TXT
# --------------------------------------------------------------------------- #

def test_txt_paragraphs():
    src = b"Primer parrafo de prueba.\n\nSegundo parrafo distinto."
    md = convert(src, Config(), filename="nota.txt")
    assert "Primer parrafo de prueba." in md
    assert "Segundo parrafo distinto." in md
    # Dos párrafos separados por línea en blanco.
    assert md.strip().count("\n\n") >= 1


def test_txt_escapes_markdown_chars():
    """En .txt los caracteres Markdown son literales: se escapan."""
    md = convert(b"esto *no* es negrita", Config(), filename="nota.txt")
    assert r"\*no\*" in md


# --------------------------------------------------------------------------- #
# MD (passthrough verbatim)
# --------------------------------------------------------------------------- #

def test_md_passthrough_not_escaped():
    """Un .md ya es Markdown: NO se escapa (bloque Raw)."""
    src = b"# Titulo\n\nUn **parrafo** con *enfasis* y `codigo`."
    md = convert(src, Config(), filename="doc.md")
    assert "# Titulo" in md
    assert "**parrafo**" in md
    assert "*enfasis*" in md
    assert "`codigo`" in md
    assert "\\*" not in md  # no hay escapado


# --------------------------------------------------------------------------- #
# CSV / TSV
# --------------------------------------------------------------------------- #

def test_csv_becomes_table():
    src = b"Nombre,Edad\nAna,30\nLuis,25\n"
    md = convert(src, Config(), filename="datos.csv")
    assert "| Nombre | Edad |" in md
    assert "| --- | --- |" in md
    assert "| Ana | 30 |" in md


def test_tsv_tab_delimiter():
    src = b"Col1\tCol2\nx\ty\n"
    md = convert(src, Config(), filename="datos.tsv")
    assert "| Col1 | Col2 |" in md
    assert "| x | y |" in md


def test_csv_row_limit():
    rows = ["a,b"] + [f"{i},{i}" for i in range(50)]
    src = ("\n".join(rows)).encode("utf-8")
    md = convert(src, Config(xlsx_max_rows=10), filename="big.csv")
    assert "| 8 | 8 |" in md
    assert "| 40 | 40 |" not in md


def test_csv_pipe_escaped_in_cell():
    src = b"col\na|b\n"
    md = convert(src, Config(), filename="p.csv")
    assert r"a\|b" in md
