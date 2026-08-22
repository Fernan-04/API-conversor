"""Lector DOCX: implementa el puerto `DocumentReader` (Fase 1).

Usa `python-docx`. Recorre el cuerpo del documento en orden para intercalar
párrafos y tablas correctamente. Mapea:

  - estilo `Heading N` / `Title`  -> `Heading`
  - estilos de lista / numeración -> `ListBlock`
  - resto de párrafos            -> `Paragraph` (`strong` si todo va en negrita)
  - tablas (`<w:tbl>`)           -> `Table`

Un DOCX produce una sola sección.
"""

from __future__ import annotations

import io
import re

from doc2md.config import Config
from doc2md.domain.errors import CorruptFileError
from doc2md.domain.models import Document, Element, Heading, ListBlock, Paragraph, Table
from doc2md.text_utils import clean_text

_HEADING_NUM = re.compile(r"(\d+)")


def _heading_level(style_name: str, config: Config) -> int | None:
    """Nivel de título a partir del nombre de estilo, o None si no es título."""
    name = (style_name or "").strip().lower()
    if name in ("title", "título", "subtitle", "subtítulo"):
        return 1
    if name.startswith("heading") or name.startswith("título"):
        m = _HEADING_NUM.search(name)
        level = int(m.group(1)) if m else 1
        return max(1, min(level, config.heading_max_levels))
    return None


def _is_list_paragraph(paragraph) -> bool:
    """True si el párrafo pertenece a una lista (por estilo o por numeración)."""
    style = (paragraph.style.name or "").lower() if paragraph.style else ""
    if "list" in style or "lista" in style:
        return True
    p_pr = paragraph._p.pPr
    return p_pr is not None and p_pr.numPr is not None


def _paragraph_is_bold(paragraph) -> bool:
    runs = [r for r in paragraph.runs if r.text and r.text.strip()]
    return bool(runs) and all(r.bold for r in runs)


def _iter_block_items(document):
    """Itera párrafos y tablas del cuerpo EN ORDEN de aparición."""
    from docx.oxml.ns import qn
    from docx.table import Table as DocxTable
    from docx.text.paragraph import Paragraph as DocxParagraph

    body = document.element.body
    for child in body.iterchildren():
        if child.tag == qn("w:p"):
            yield DocxParagraph(child, document)
        elif child.tag == qn("w:tbl"):
            yield DocxTable(child, document)


def _table_rows(table, config: Config) -> list[list[str]]:
    rows: list[list[str]] = []
    for row in table.rows:
        rows.append([clean_text(cell.text, config) for cell in row.cells])
    return rows


class DocxReader:
    """Adaptador de lectura DOCX (puerto `DocumentReader`)."""

    def read(self, data: bytes, filename: str, config: Config) -> Document:
        try:
            from docx import Document as DocxDocument
            from docx.table import Table as DocxTable

            doc = DocxDocument(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise CorruptFileError(detail=str(exc)) from exc

        elements: list[Element] = []
        pending_list: list[str] = []

        def flush_list() -> None:
            if pending_list:
                elements.append(ListBlock(items=list(pending_list)))
                pending_list.clear()

        for item in _iter_block_items(doc):
            if isinstance(item, DocxTable):
                flush_list()
                rows = _table_rows(item, config)
                if rows:
                    elements.append(Table(rows=rows))
                continue

            # Es un párrafo.
            text = clean_text(item.text, config).strip()
            if not text:
                continue
            level = _heading_level(item.style.name if item.style else "", config)
            if level is not None:
                flush_list()
                elements.append(Heading(level=level, text=text))
            elif _is_list_paragraph(item):
                pending_list.append(text)
            else:
                flush_list()
                elements.append(Paragraph(text=text, strong=_paragraph_is_bold(item)))

        flush_list()
        return Document(sections=[elements])
