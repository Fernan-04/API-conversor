"""Extracción y estructuración PDF -> bloques (Fases 1-2).

Convierte cada página en una lista ordenada de `Block` (texto o tabla):

  1. `find_tables()` -> filtro de maquetación (`tables.select_tables`).
  2. `extract_words()` -> se descartan las palabras cuyo centro cae dentro de una
     tabla ACEPTADA (§5d, evita duplicar contenido).
  3. Las palabras restantes se agrupan en `Line` (por coordenada vertical) y las
     líneas en párrafos (por hueco vertical).
  4. Párrafos y tablas se ordenan por coordenada `top`.

`Block`/`Line` son estructuras INTERNAS de este adaptador (llevan coordenadas y
tamaños de fuente, propios de PDF). `reader.py` las traduce a la estructura
neutral `Document` del dominio.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from statistics import median

import pdfplumber

from doc2md.adapters.outbound.pdf import ocr as ocr_mod
from doc2md.adapters.outbound.pdf.tables import (
    Bbox,
    merge_tables_across_pages,
    select_tables,
)
from doc2md.config import Config
from doc2md.domain.errors import FileTooLargeError
from doc2md.text_utils import normalize_unicode, strip_pua


@dataclass
class Line:
    text: str
    size: float      # mediana del tamaño de fuente de la línea
    bold: bool       # mayoría de palabras con fontname de negrita
    top: float       # coordenada Y (para ordenar)
    x0: float        # coordenada X inicial (para detectar indentación)
    heading_level: int = 0  # 0 = no es título; 1..N = nivel de #, se fija en Fase 2


@dataclass
class Block:
    kind: str                                # "text" | "table"
    top: float
    lines: list[Line] = field(default_factory=list)
    rows: list[list[str]] = field(default_factory=list)


def _inside(cx: float, cy: float, bbox: Bbox) -> bool:
    return bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]


def _group_lines(words: list[dict], config: Config) -> list[Line]:
    """Agrupa palabras en líneas por coordenada vertical."""
    if not words:
        return []
    enriched = []
    for w in words:
        cy = (w["top"] + w["bottom"]) / 2
        enriched.append((cy, w))
    enriched.sort(key=lambda t: (t[0], t[1]["x0"]))

    # Tolerancia vertical adaptativa: media palabra de alto.
    heights = [w["bottom"] - w["top"] for _, w in enriched]
    tol = max(2.0, 0.4 * median(heights))

    groups: list[list[dict]] = []
    cur: list[dict] = []
    cur_cy: float | None = None
    for cy, w in enriched:
        if cur_cy is None or abs(cy - cur_cy) <= tol:
            cur.append(w)
            cur_cy = cy if cur_cy is None else cur_cy
        else:
            groups.append(cur)
            cur = [w]
            cur_cy = cy
    if cur:
        groups.append(cur)

    lines: list[Line] = []
    for g in groups:
        g.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in g)
        sizes = [float(w.get("size", 0) or 0) for w in g]
        bold_words = sum(1 for w in g if config.is_bold_font(str(w.get("fontname", ""))))
        lines.append(Line(
            text=text,
            size=median(sizes) if sizes else 0.0,
            bold=(bold_words / len(g)) >= config.bold_line_ratio,
            top=min(w["top"] for w in g),
            x0=min(w["x0"] for w in g),
        ))
    return lines


def _group_paragraphs(lines: list[Line]) -> list[Block]:
    """Divide una secuencia de líneas en párrafos por hueco vertical."""
    if not lines:
        return []
    lines = sorted(lines, key=lambda l: l.top)
    gaps = [lines[i + 1].top - lines[i].top for i in range(len(lines) - 1)]
    med = median(gaps) if gaps else 0.0
    threshold = med * 1.6 if med > 0 else float("inf")

    blocks: list[Block] = []
    cur: list[Line] = [lines[0]]
    for i in range(1, len(lines)):
        if lines[i].top - lines[i - 1].top > threshold:
            blocks.append(Block(kind="text", top=cur[0].top, lines=cur))
            cur = [lines[i]]
        else:
            cur.append(lines[i])
    blocks.append(Block(kind="text", top=cur[0].top, lines=cur))
    return blocks


def extract_document(
    source, config: Config
) -> tuple[list[list[Block]], int, int, list[str]]:
    """Extrae el documento como lista de páginas, cada una lista de `Block`.

    `source` puede ser una ruta o un objeto file-like (`io.BytesIO`) — así el
    adaptador procesa desde bytes en memoria sin tocar disco (§8.3).

    Devuelve (paginas, n_paginas, paginas_con_texto, log_lines).
    """
    pages_out: list[list[Block]] = []
    log: list[str] = []
    pages_with_text = 0

    with pdfplumber.open(source) as pdf:
        n_pages = len(pdf.pages)
        if n_pages > config.pdf_max_pages:
            raise FileTooLargeError(
                f"El PDF tiene {n_pages} páginas; el máximo permitido es "
                f"{config.pdf_max_pages}.",
                detail=f"pages={n_pages} > {config.pdf_max_pages}",
            )
        for page in pdf.pages:
            accepted = []
            if config.extract_tables:
                accepted = select_tables(page.find_tables(), page, config, log.append)

            words = page.extract_words(
                extra_attrs=["size", "fontname"], keep_blank_chars=False
            )
            kept: list[dict] = []
            for w in words:
                cx = (w["x0"] + w["x1"]) / 2
                cy = (w["top"] + w["bottom"]) / 2
                if any(_inside(cx, cy, t.bbox) for t in accepted):
                    continue
                text = normalize_unicode(strip_pua(w["text"], config))
                if not text.strip():
                    continue
                w["text"] = text
                kept.append(w)

            lines = _group_lines(kept, config)
            blocks: list[Block] = _group_paragraphs(lines)
            for t in accepted:
                blocks.append(Block(kind="table", top=t.top, rows=t.rows))
            blocks.sort(key=lambda b: b.top)

            # OCR de páginas sin capa de texto (§2, solo si se pidió y está disponible).
            if not lines and not accepted and config.ocr and ocr_mod.available():
                blocks = _ocr_blocks(page, config, log.append)

            if lines or accepted or blocks:
                pages_with_text += 1
            pages_out.append(blocks)

    merge_tables_across_pages(pages_out, config, log.append)
    return pages_out, n_pages, pages_with_text, log


def _ocr_blocks(page, config: Config, log) -> list[Block]:
    """Convierte una página escaneada en un bloque de texto vía OCR (best-effort)."""
    try:
        text = ocr_mod.ocr_page(page, config)
    except Exception as exc:  # noqa: BLE001 — el OCR nunca debe romper el lote
        log(f"[ocr] p{page.page_number} falló: {exc}")
        return []
    lines = [
        Line(text=normalize_unicode(strip_pua(t, config)), size=0.0, bold=False,
             top=float(i), x0=0.0)
        for i, t in enumerate(text.splitlines())
        if t.strip()
    ]
    if config.verbose and lines:
        log(f"[ocr] p{page.page_number}: {len(lines)} líneas reconocidas")
    return _group_paragraphs(lines) if lines else []


def assign_headings(pages: list[list[Block]], config: Config) -> None:
    """Marca `heading_level` en las líneas de texto (§6.4).

    El cuerpo de texto es el tamaño de fuente MODAL del documento. Los tamaños
    distintos >= `body * heading_size_ratio` se ordenan de mayor a menor y los
    primeros `heading_max_levels` se mapean a #, ##, ###, ####.

    Refuerzo: una línea corta, en negrita, con señal fuerte de título (numerada
    tipo `2. ...` o terminada en `:`) y sin punto final se trata como título del
    nivel más profundo. La señal fuerte evita marcar como título cualquier
    etiqueta en negrita suelta dentro de un párrafo.
    """
    if not config.detect_headings:
        return

    text_lines = [
        line
        for page in pages
        for block in page
        if block.kind == "text"
        for line in block.lines
        if line.text.strip()
    ]
    if not text_lines:
        return

    sizes = Counter(round(line.size, 1) for line in text_lines)
    body = sizes.most_common(1)[0][0]
    bigger = sorted(
        {s for s in sizes if s >= body * config.heading_size_ratio}, reverse=True
    )
    level_of = {s: i + 1 for i, s in enumerate(bigger[:config.heading_max_levels])}
    reinforce_level = min(len(level_of) + 1, config.heading_max_levels)

    for page in pages:
        for block in page:
            if block.kind != "text":
                continue
            for line in block.lines:
                level = level_of.get(round(line.size, 1), 0)
                if level == 0 and _is_reinforced_heading(line, config):
                    level = reinforce_level
                line.heading_level = level


_NUMBERED = re.compile(r"^\d+[.)]\s")


def _is_reinforced_heading(line: "Line", config: Config) -> bool:
    t = line.text.strip()
    if not line.bold or not (0 < len(t) <= config.heading_short_line_max_len):
        return False
    if t.endswith("."):
        return False
    return bool(_NUMBERED.match(t)) or t.endswith(":")
