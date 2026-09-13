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
from doc2md.text_utils import detect_language, fix_punct_spacing, is_all_caps, title_case

# Puntuación que cierra una frase/título: si un título termina en uno de estos
# NO se fusiona con el título siguiente (son unidades distintas a propósito).
_HEADING_SENTENCE_END = (".", ":", ";", "?", "!")
# Título numerado ("1. Logro a evaluar", "4.1. Categoría Nacional"): un título
# que empieza así es una unidad completa por sí misma y nunca se fusiona con el
# título vecino, aunque compartan nivel y ninguno cierre con puntuación.
_NUMBERED_HEADING = re.compile(r"^\d+[.)]\s")


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
    return fix_punct_spacing(raw)


def _heading_text(text: str, level: int, config: Config, lang: str = "es") -> str:
    """Pule el texto de un título: Title Case (si viene all-caps) y sin `:` final.

    El título de nivel 1 (el titular del documento, p. ej. "SÍLABO") se deja tal
    cual: es el nombre del documento y suele quererse verbatim. `lang` (§Ronda 6)
    elige las reglas de Title Case español o inglés.
    """
    if config.heading_strip_trailing_colon:
        text = text.rstrip().removesuffix(":").rstrip()
    if config.titlecase_headings and level > 1:
        text = title_case(text, lang)
    return text


def _map_text_block(
    block: Block, config: Config, lang: str = "es"
) -> tuple[list[Element], str | None, str | None]:
    """Traduce un bloque de texto a elementos neutrales.

    Reproduce la lógica de `render._render_text_block`: los títulos se emiten por
    línea; las viñetas consecutivas se agrupan en una lista; el resto forma
    párrafos unidos (con negrita solo si el párrafo es una sola línea en negrita).

    Devuelve además `(leading_heading_raw, trailing_heading_raw)`: el texto RAW
    (antes de `_heading_text`) del primer/último título del bloque, o `None` si
    el primer/último elemento no es un título. `_map_page` los usa para decidir
    si el título líder de un bloque es la continuación visual del título final
    del bloque anterior (§Ronda 6, 5.1) — un título grande partido en varias
    líneas puede quedar en bloques distintos por el hueco vertical entre líneas.
    """
    elements: list[Element] = []
    para: list[Line] = []
    items: list[list[str]] = []   # cada ítem de lista = sus líneas (viñeta + continuación)
    # Texto RAW del último título emitido hasta ahora; se pone a None en cuanto
    # se intercala CUALQUIER contenido que no sea título (párrafo o lista), para
    # no fusionar títulos separados por cuerpo de texto.
    trailing_heading_raw: str | None = None
    leading_heading_raw: str | None = None

    def flush_para() -> None:
        nonlocal trailing_heading_raw
        if para:
            text = _join_lines_raw([l.text for l in para], config)
            strong = config.mark_bold and len(para) == 1 and para[0].bold
            elements.append(Paragraph(text=text, strong=strong))
            para.clear()
            trailing_heading_raw = None

    def flush_list() -> None:
        nonlocal trailing_heading_raw
        if items:
            elements.append(ListBlock(items=[_join_lines_raw(it, config) for it in items]))
            items.clear()
            trailing_heading_raw = None

    for line in block.lines:
        t = line.text.strip()
        if not t:
            continue
        if config.detect_headings and line.heading_level > 0:
            flush_para(); flush_list()
            heading_text = _heading_text(t, line.heading_level, config, lang)
            can_merge = (
                config.merge_consecutive_headings
                and elements and isinstance(elements[-1], Heading)
                and elements[-1].level == line.heading_level
                and trailing_heading_raw is not None
                and not trailing_heading_raw.endswith(_HEADING_SENTENCE_END)
                and not _NUMBERED_HEADING.match(trailing_heading_raw)
                and not _NUMBERED_HEADING.match(t)
            )
            if can_merge:
                elements[-1] = Heading(
                    level=line.heading_level,
                    text=f"{elements[-1].text} {heading_text}".strip(),
                )
            else:
                elements.append(Heading(level=line.heading_level, text=heading_text))
                if len(elements) == 1:
                    leading_heading_raw = t
            trailing_heading_raw = t
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
    return elements, leading_heading_raw, trailing_heading_raw


# Un campo "N.N Etiqueta: valor". El valor es perezoso: llega hasta el siguiente
# marcador numérico "N.N" o el fin del texto.
_KV_ITEM = re.compile(
    r"(\d+(?:\.\d+)+)\.?\s*([^:]+?):\s*(.+?)(?=\s+\d+(?:\.\d+)+\.?\s|\Z)"
)


def _kv_to_table(text: str, config: Config, lang: str = "es") -> Table | None:
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
    header = list(config.kv_table_headers.get(lang, config.kv_table_headers["es"]))
    rows = [header]
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


def _drop_furniture_label(elements: list[Element], config: Config) -> list[Element]:
    """Quita la etiqueta "eyebrow" que antecede al título real de la página
    (§Ronda 6, task 8): el primer elemento, si es un párrafo MUY corto, en
    MAYÚSCULAS (como "COVER", "BASES", "N°7") y sin punto final, seguido
    inmediatamente de un título, se descarta. Exigir mayúsculas evita comerse
    un párrafo corto legítimo en minúscula/mixto (p. ej. "Bibliografía") que
    simplemente antecede a otro título por casualidad de maquetación.
    """
    if not config.remove_furniture or len(elements) < 2:
        return elements
    first = elements[0]
    if (
        isinstance(first, Paragraph) and first.spans is None
        and 0 < len(first.text.split()) <= config.furniture_max_words
        and not first.text.rstrip().endswith(".")
        and is_all_caps(first.text)
        and isinstance(elements[1], Heading)
    ):
        return elements[1:]
    return elements


def _map_page(page: list[Block], config: Config, lang: str = "es") -> list[Element]:
    elements: list[Element] = []
    triggers = config.bullet_trigger_headings
    prev_heading = ""
    # Texto RAW del último título del bloque anterior, para fusionar títulos
    # partidos en varias líneas AUNQUE hayan caído en bloques distintos por el
    # hueco vertical entre líneas de un titular grande (§Ronda 6, 5.1). Una
    # tabla, o cualquier bloque que no termine en título, corta la cadena.
    prev_heading_raw: str | None = None
    for block in page:
        if block.kind == "table":
            elements.append(Table(rows=block.rows))
            prev_heading = ""
            prev_heading_raw = None
            continue
        block_elements, leading_raw, trailing_raw = _map_text_block(block, config, lang)
        if not block_elements:
            continue
        if (
            config.merge_consecutive_headings
            and prev_heading_raw is not None
            and leading_raw is not None
            and elements and isinstance(elements[-1], Heading)
            and isinstance(block_elements[0], Heading)
            and elements[-1].level == block_elements[0].level
            and not prev_heading_raw.endswith(_HEADING_SENTENCE_END)
            and not _NUMBERED_HEADING.match(prev_heading_raw)
            and not _NUMBERED_HEADING.match(leading_raw)
        ):
            elements[-1] = Heading(
                level=elements[-1].level,
                text=f"{elements[-1].text} {block_elements[0].text}".strip(),
            )
            block_elements = block_elements[1:]
        prev_heading_raw = trailing_raw
        for el in block_elements:
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
                table = _kv_to_table(el.text, config, lang)
                if table is not None:
                    elements.append(table)
                    prev_heading = ""
                    continue
            prev_heading = ""
            elements.append(el)
    elements = _drop_furniture_label(elements, config)
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

        lang = detect_language(_collect_text(pages))
        return Document(
            sections=[_map_page(page, config, lang) for page in pages],
            language=lang,
        )


def _collect_text(pages: list[list[Block]]) -> str:
    """Junta el texto de todas las líneas del documento para `detect_language`."""
    return " ".join(
        line.text
        for page in pages
        for block in page
        if block.kind == "text"
        for line in block.lines
    )
