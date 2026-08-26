"""Lector DOCX: implementa el puerto `DocumentReader` (Fase 1).

Usa `python-docx`. Recorre el cuerpo del documento en orden para intercalar
párrafos y tablas correctamente. Mapea:

  - estilo `Heading N` / `Title`  -> `Heading`
  - estilos de lista / numeración -> `ListBlock` (con nivel de anidación y, si es
    numerada, marcador `1.`)
  - resto de párrafos            -> `Paragraph` con `spans` (formato inline)
  - tablas (`<w:tbl>`)           -> `Table`

**Texto rico (§B):** el texto de cada párrafo/ítem se construye como `Span`s que
conservan negrita/cursiva **parciales** e **hipervínculos** (`[texto](url)`), que
el texto plano perdía. Los lectores simples siguen usando `text`; este emite
`spans`/`rich_items` y el renderer los formatea.

Un DOCX produce una sola sección.
"""

from __future__ import annotations

import io
import re

from doc2md.adapters.outbound._zip_guard import ensure_safe_zip
from doc2md.config import Config
from doc2md.domain.errors import CorruptFileError
from doc2md.domain.models import (
    Document,
    Element,
    Heading,
    ListBlock,
    ListItem,
    Paragraph,
    Span,
    Table,
)
from doc2md.text_utils import clean_text, normalize_unicode, strip_pua

_HEADING_NUM = re.compile(r"(\d+)")
_WS = re.compile(r"[\t\n\r ]+")


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


def _span_clean(text: str, config: Config) -> str:
    """Normaliza un fragmento SIN colapsar los espacios de los bordes.

    A diferencia de `clean_text`, conserva un espacio inicial/final (el que separa
    dos runs, p. ej. "hola " + "mundo"), para no pegar palabras entre spans.
    """
    if not text:
        return ""
    return _WS.sub(" ", normalize_unicode(strip_pua(text, config)))


def _spans_from_runs(run_elements, paragraph, config: Config,
                     link: str | None) -> list[Span]:
    from docx.text.run import Run

    spans: list[Span] = []
    for r in run_elements:
        run = Run(r, paragraph)
        text = _span_clean(run.text, config)
        if not text:
            continue
        spans.append(Span(
            text=text,
            bold=bool(run.bold),
            italic=bool(run.italic),
            link=link,
        ))
    return spans


def _paragraph_spans(paragraph, config: Config) -> list[Span]:
    """Construye los spans de un párrafo, en orden, incluyendo hipervínculos."""
    from docx.oxml.ns import qn
    from docx.text.run import Run

    spans: list[Span] = []
    for child in paragraph._p.iterchildren():
        if child.tag == qn("w:r"):
            spans.extend(_spans_from_runs([child], paragraph, config, None))
        elif child.tag == qn("w:hyperlink"):
            url = None
            rid = child.get(qn("r:id"))
            if rid:
                rel = paragraph.part.rels.get(rid)
                if rel is not None and rel.is_external:
                    url = rel.target_ref
            runs = child.findall(qn("w:r"))
            if url:
                # Todo el texto del hipervínculo va como un solo span con enlace.
                text = "".join(
                    _span_clean(Run(r, paragraph).text, config)
                    for r in runs
                ).strip()
                if text:
                    spans.append(Span(text=text, link=url))
            else:
                spans.extend(_spans_from_runs(runs, paragraph, config, None))
    return spans


def _num_pr(paragraph):
    """Devuelve el `numPr` del párrafo, buscándolo también en el estilo.

    Los estilos "List Number"/"List Bullet" definen la numeración en el ESTILO, no
    en el párrafo, así que hay que subir por la cadena de estilos si el párrafo no
    la trae inline.
    """
    p_pr = paragraph._p.pPr
    if p_pr is not None and p_pr.numPr is not None:
        return p_pr.numPr
    style = paragraph.style
    while style is not None:
        try:
            s_pr = style.element.pPr
        except AttributeError:
            s_pr = None
        if s_pr is not None and s_pr.numPr is not None:
            return s_pr.numPr
        style = getattr(style, "base_style", None)
    return None


def _list_level(paragraph) -> int:
    """Nivel de anidación de la lista (ilvl), 0 si no consta."""
    num_pr = _num_pr(paragraph)
    try:
        ilvl = num_pr.ilvl
        return int(ilvl.val) if ilvl is not None and ilvl.val is not None else 0
    except AttributeError:
        return 0


def _numbering_formats(document) -> dict[tuple[int, int], str]:
    """Mapa (numId, ilvl) -> numFmt (best-effort) leyendo la parte de numeración.

    Devuelve {} si el documento no tiene numeración o algo falla: en ese caso las
    listas se tratan como viñetas.
    """
    from docx.oxml.ns import qn

    try:
        numbering = document.part.numbering_part.element
    except (AttributeError, KeyError, NotImplementedError):
        return {}

    abstract_fmt: dict[str, dict[int, str]] = {}
    for anum in numbering.findall(qn("w:abstractNum")):
        aid = anum.get(qn("w:abstractNumId"))
        levels: dict[int, str] = {}
        for lvl in anum.findall(qn("w:lvl")):
            ilvl = lvl.get(qn("w:ilvl"))
            numfmt = lvl.find(qn("w:numFmt"))
            if ilvl is not None and numfmt is not None:
                levels[int(ilvl)] = numfmt.get(qn("w:val")) or ""
        abstract_fmt[aid] = levels

    result: dict[tuple[int, int], str] = {}
    for num in numbering.findall(qn("w:num")):
        num_id = num.get(qn("w:numId"))
        anum_ref = num.find(qn("w:abstractNumId"))
        if num_id is None or anum_ref is None:
            continue
        aid = anum_ref.get(qn("w:val"))
        for ilvl, fmt in abstract_fmt.get(aid, {}).items():
            result[(int(num_id), ilvl)] = fmt
    return result


def _list_ordered(paragraph, fmts: dict[tuple[int, int], str]) -> bool:
    """True si el ítem es de una lista numerada (numFmt != bullet/none)."""
    if not fmts:
        return False
    num_pr = _num_pr(paragraph)
    try:
        num_id = int(num_pr.numId.val)
    except AttributeError:
        return False
    fmt = fmts.get((num_id, _list_level(paragraph)), "")
    return bool(fmt) and fmt not in ("bullet", "none")


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
        ensure_safe_zip(data, config)   # guarda anti zip-bomb (DOCX es zip+XML)
        try:
            from docx import Document as DocxDocument
            from docx.table import Table as DocxTable

            doc = DocxDocument(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise CorruptFileError(detail=str(exc)) from exc

        fmts = _numbering_formats(doc)
        elements: list[Element] = []
        pending: list[ListItem] = []

        def flush_list() -> None:
            if pending:
                items = ["".join(s.text for s in it.spans).strip() for it in pending]
                elements.append(ListBlock(items=items, rich_items=list(pending)))
                pending.clear()

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
                spans = _paragraph_spans(item, config) or [Span(text=text)]
                li = ListItem(
                    spans=spans,
                    level=_list_level(item),
                    ordered=_list_ordered(item, fmts),
                )
                # Un cambio de tipo (viñeta <-> numerada) cierra la lista actual,
                # para no mezclar ambos marcadores en un mismo bloque.
                if pending and pending[-1].ordered != li.ordered:
                    flush_list()
                pending.append(li)
            else:
                flush_list()
                spans = _paragraph_spans(item, config) or [Span(text=text)]
                elements.append(Paragraph(text=text, spans=spans))

        flush_list()
        return Document(sections=[elements])
