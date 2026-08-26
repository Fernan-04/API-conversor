"""Lector PDF: implementa el puerto `DocumentReader`.

Orquesta el pipeline heurístico (`extract` -> `clean` -> `assign_headings`) y
traduce el resultado (`Block`/`Line`, con coordenadas) a la estructura neutral
`Document` del dominio.

La clasificación título/viñeta/párrafo y la des-hifenización —que en pdf2md
vivían en `render._render_text_block`— se hacen AQUÍ, al construir el `Document`,
con texto RAW (sin escapar). El renderer del dominio solo escapa y envuelve, de
modo que la salida Markdown es idéntica a la de pdf2md.
"""

from __future__ import annotations

import io
import re
import sys

from doc2md.adapters.outbound.pdf.clean import clean_document
from doc2md.adapters.outbound.pdf.extract import (
    Block,
    Line,
    assign_headings,
    extract_document,
)
from doc2md.adapters.outbound._signatures import ensure_signature
from doc2md.config import Config
from doc2md.domain.errors import (
    ConversionError,
    CorruptFileError,
    PasswordProtectedError,
)
from doc2md.domain.models import Document, Element, Heading, ListBlock, Paragraph, Table
from doc2md.text_utils import title_case_es


def _looks_password_protected(exc: Exception) -> bool:
    name = type(exc).__name__.lower()
    msg = str(exc).lower()
    return "password" in name or "password" in msg or "encrypt" in msg


def _bullet_rest(text: str, config: Config) -> str | None:
    """Si la línea empieza por un marcador de viñeta + espacio, devuelve el resto."""
    for m in config.bullet_markers:
        if text.startswith(m) and text[len(m):len(m) + 1] == " ":
            rest = text[len(m):].strip()
            if rest:
                return rest
    return None


def _join_lines_raw(texts: list[str], config: Config) -> str:
    """Une textos de líneas con des-hifenización (§6.7), SIN escapar.

    El escapado lo aplica el renderer del dominio; esto solo produce el texto
    unido tal como lo hacía `render._dehyphenate_join` antes de escapar.
    """
    raw = ""
    for i, t in enumerate(texts):
        t = t.strip()
        if i == 0:
            raw = t
        elif not config.join_lines:
            raw += "\n" + t
        elif raw.endswith("-") and t[:1].islower():
            raw = raw[:-1] + t          # quitar el guion de corte de palabra
        else:
            raw += " " + t
    return raw


def _heading_text(text: str, level: int, config: Config) -> str:
    """Pule el texto de un título: Title Case (si viene all-caps) y sin `:` final.

    El título de nivel 1 (el titular del documento, p. ej. "SÍLABO") se deja tal
    cual: es el nombre del documento y suele quererse verbatim.
    """
    if config.heading_strip_trailing_colon:
        text = text.rstrip().removesuffix(":").rstrip()
    if config.titlecase_headings and level > 1:
        text = title_case_es(text)
    return text


def _map_text_block(block: Block, config: Config) -> list[Element]:
    """Traduce un bloque de texto a elementos neutrales.

    Reproduce la lógica de `render._render_text_block`: los títulos se emiten por
    línea; las viñetas consecutivas se agrupan en una lista; el resto forma
    párrafos unidos (con negrita solo si el párrafo es una sola línea en negrita).
    """
    elements: list[Element] = []
    para: list[Line] = []
    items: list[list[str]] = []   # cada ítem de lista = sus líneas (viñeta + continuación)

    def flush_para() -> None:
        if para:
            text = _join_lines_raw([l.text for l in para], config)
            strong = config.mark_bold and len(para) == 1 and para[0].bold
            elements.append(Paragraph(text=text, strong=strong))
            para.clear()

    def flush_list() -> None:
        if items:
            elements.append(ListBlock(items=[_join_lines_raw(it, config) for it in items]))
            items.clear()

    for line in block.lines:
        t = line.text.strip()
        if not t:
            continue
        if config.detect_headings and line.heading_level > 0:
            flush_para(); flush_list()
            elements.append(Heading(
                level=line.heading_level,
                text=_heading_text(t, line.heading_level, config),
            ))
            continue
        rest = _bullet_rest(t, config)
        if rest is not None:
            flush_para()
            items.append([rest])                 # nueva viñeta
            continue
        if items and not para:
            items[-1].append(t)                  # continuación de la viñeta actual
            continue
        flush_list()
        para.append(line)

    flush_para(); flush_list()
    return elements


# Un campo "N.N Etiqueta: valor". El valor es perezoso: llega hasta el siguiente
# marcador numérico "N.N" o el fin del texto.
_KV_ITEM = re.compile(
    r"(\d+(?:\.\d+)+)\.?\s*([^:]+?):\s*(.+?)(?=\s+\d+(?:\.\d+)+\.?\s|\Z)"
)


def _kv_to_table(text: str, config: Config) -> Table | None:
    """Convierte un párrafo de campos "N.N Etiqueta: valor" en una tabla 2-col.

    Devuelve `None` si el texto no es claramente un bloque clave-valor (pocos
    pares o no cubre casi todo el párrafo), para no tocar prosa normal.
    """
    if not config.kv_to_table:
        return None
    matches = [
        m for m in _KV_ITEM.finditer(text)
        if len(m.group(2).strip()) <= config.kv_label_max_len
    ]
    if len(matches) < config.kv_min_pairs:
        return None
    covered = sum(m.end() - m.start() for m in matches)
    if covered / max(len(text), 1) < config.kv_min_coverage:
        return None
    rows = [["Campo", "Detalle"]]
    for m in matches:
        num, label, value = m.group(1), m.group(2).strip(), m.group(3).strip()
        rows.append([f"{num} {label}", value])
    return Table(rows=rows)


# Corta un temario corrido: fin de oración (".", ")" o "?") seguido de mayúscula,
# o un marcador de guion antes de mayúscula.
_TEMARIO_SPLIT = re.compile(
    r"(?<=[.?])\s+(?=[A-ZÁÉÍÓÚÑ])|\s+[-–]\s*(?=[A-ZÁÉÍÓÚÑ])"
)


def _temario_to_list(text: str, config: Config) -> ListBlock | None:
    """Parte un párrafo de temario en viñetas. `None` si no salen >= 2 ítems."""
    if not config.temario_to_bullets:
        return None
    items = [s.strip(" -–") for s in _TEMARIO_SPLIT.split(text)]
    items = [s for s in items if s]
    if len(items) < 2:
        return None
    return ListBlock(items=items)


def _map_page(page: list[Block], config: Config) -> list[Element]:
    elements: list[Element] = []
    triggers = config.bullet_trigger_headings
    prev_heading = ""
    for block in page:
        if block.kind == "table":
            elements.append(Table(rows=block.rows))
            prev_heading = ""
            continue
        for el in _map_text_block(block, config):
            if isinstance(el, Heading):
                prev_heading = el.text.strip().lower()
                elements.append(el)
                continue
            if isinstance(el, Paragraph):
                if prev_heading in triggers:
                    lst = _temario_to_list(el.text, config)
                    if lst is not None:
                        elements.append(lst)
                        prev_heading = ""
                        continue
                table = _kv_to_table(el.text, config)
                if table is not None:
                    elements.append(table)
                    prev_heading = ""
                    continue
            prev_heading = ""
            elements.append(el)
    return elements


class PdfReader:
    """Adaptador de lectura PDF (puerto `DocumentReader`)."""

    def read(self, data: bytes, filename: str, config: Config) -> Document:
        ensure_signature(data, ".pdf")   # el contenido debe empezar por %PDF
        try:
            pages, n_pages, pages_with_text, log = extract_document(
                io.BytesIO(data), config
            )
        except ConversionError:
            # Errores ya tipificados (p. ej. límite de páginas): se propagan tal
            # cual, sin re-envolverlos en un CorruptFileError genérico.
            raise
        except Exception as exc:  # noqa: BLE001 — se traduce a error tipificado
            if _looks_password_protected(exc):
                raise PasswordProtectedError(detail=str(exc)) from exc
            raise CorruptFileError(detail=str(exc)) from exc

        clean_document(pages, config)      # §6.2/§6.3: cabeceras repetidas y basura
        assign_headings(pages, config)     # §6.4: títulos por tamaño de fuente

        if config.verbose:
            for line in log:
                print(line, file=sys.stderr)
        if pages_with_text == 0 and not config.ocr:
            print(
                f"[aviso] {filename}: sin capa de texto (¿escaneado?). "
                f"Prueba con --ocr.",
                file=sys.stderr,
            )
        elif config.verbose:
            print(
                f"[ok] {filename}: {pages_with_text}/{n_pages} páginas con texto",
                file=sys.stderr,
            )

        return Document(sections=[_map_page(page, config) for page in pages])
