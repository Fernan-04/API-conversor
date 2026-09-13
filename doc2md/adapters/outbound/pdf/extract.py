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
import time
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


@dataclass
class _OcrBudget:
    """Presupuesto de tiempo TOTAL de OCR compartido entre páginas de un mismo
    documento (§Ronda 6). Mutable a propósito: cada imagen OCR-eada descuenta
    su tiempo real; al llegar a 0, el resto del documento se trata como si no
    hubiera Tesseract disponible (aviso en vez de gasto de tiempo)."""
    remaining: float

    def exhausted(self) -> bool:
        return self.remaining <= 0


def _has_duplicate_chars(page, tolerance: float) -> bool:
    """Detector barato (O(n)) de si la página tiene glifos duplicados.

    `page.dedupe_chars()` de pdfplumber es correcto pero caro: su paso final
    reordena con `sorted(deduped, key=chars.index)`, y `list.index()` es O(n),
    así que el conjunto sale O(n²) — en una página con cientos de caracteres
    esto duplica (o más) el tiempo de conversión, incluso en páginas SIN
    ningún glifo duplicado. Como la inmensa mayoría de páginas no tienen este
    problema, se hace primero este chequeo O(n) con un `set` (agrupando por
    posición redondeada a `tolerance`, una aproximación barata del clustering
    real que hace pdfplumber) y solo se paga el costo de `dedupe_chars()` en
    las páginas que de verdad lo necesitan.
    """
    seen: set[tuple[str, int, int]] = set()
    tol = tolerance or 1.0
    for c in page.chars:
        key = (c["text"], round(c["x0"] / tol), round(c["top"] / tol))
        if key in seen:
            return True
        seen.add(key)
    return False


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
    ocr_budget = _OcrBudget(remaining=config.ocr_total_budget_seconds)

    with pdfplumber.open(source) as pdf:
        n_pages = len(pdf.pages)
        if n_pages > config.pdf_max_pages:
            raise FileTooLargeError(
                f"El PDF tiene {n_pages} páginas; el máximo permitido es "
                f"{config.pdf_max_pages}.",
                detail=f"pages={n_pages} > {config.pdf_max_pages}",
            )
        for page in pdf.pages:
            if config.dedupe_chars and _has_duplicate_chars(page, config.dedupe_tolerance):
                page = page.dedupe_chars(tolerance=config.dedupe_tolerance)
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
            else:
                # OCR de imágenes grandes sin texto real encima (§Ronda 6): una
                # infografía o portada exportada como imagen no debe perderse
                # solo porque el resto de la página SÍ tiene texto normal.
                blocks.extend(_ocr_big_images(page, kept, config, log.append, ocr_budget))
                blocks.sort(key=lambda b: b.top)

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


def _image_bbox(im: dict) -> Bbox:
    return (im["x0"], im["top"], im["x1"], im["bottom"])


def _ocr_big_images(
    page, kept_words: list[dict], config: Config, log,
    budget: "_OcrBudget | None" = None,
) -> list[Block]:
    """OCR de imágenes grandes sin texto real encima (§Ronda 6).

    Muchas portadas/infografías se exportan como una imagen a página completa
    (o casi) sin ninguna capa de texto sobre ella: sin esto, esa página se
    pierde por completo. Se ignoran imágenes pequeñas (`ocr_image_min_area_ratio`)
    y las que ya tienen texto real superpuesto (evita duplicar un título vector
    dibujado encima de un fondo decorativo). Si Tesseract no está disponible —o
    si `budget` (compartido entre páginas) ya se agotó, ver `Config.
    ocr_total_budget_seconds`— se inserta un aviso VISIBLE en el propio
    Markdown en vez de perder el contenido en silencio o dejar que el OCR se
    coma la petición entera (medido en producción: causaba 502 en Render).
    """
    if not config.ocr_images or not getattr(page, "images", None):
        return []
    page_area = float(page.width or 0) * float(page.height or 0)
    if page_area <= 0:
        return []
    blocks: list[Block] = []
    done = 0
    for im in page.images:
        if done >= config.ocr_max_images:
            break
        bbox = _image_bbox(im)
        area = max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1])
        if area / page_area < config.ocr_image_min_area_ratio:
            continue
        overlapping_real_text = sum(
            1 for w in kept_words
            if _inside((w["x0"] + w["x1"]) / 2, (w["top"] + w["bottom"]) / 2, bbox)
        )
        if overlapping_real_text > 5:
            continue   # ya hay texto real sobre esta imagen: no duplicar
        budget_exhausted = budget is not None and budget.exhausted()
        if not ocr_mod.available() or budget_exhausted:
            if area / page_area < config.ocr_placeholder_min_area_ratio:
                continue   # sin OCR no se sabe si es foto decorativa o texto: sin ruido
            done += 1
            reason = (
                "presupuesto de tiempo de OCR agotado" if budget_exhausted
                else "instala Tesseract para activar el OCR"
            )
            # Texto plano (sin sintaxis Markdown): el renderer escapa los
            # párrafos normales y un "*" literal saldría como "\*" (negrita
            # rota), no en cursiva.
            blocks.append(Block(kind="text", top=bbox[1], lines=[Line(
                text=f"[Imagen en la página {page.page_number}: su contenido "
                     f"no se pudo extraer — {reason}]",
                size=0.0, bold=False, top=bbox[1], x0=bbox[0],
            )]))
            log(f"[ocr] p{page.page_number}: imagen grande sin OCR ({reason}, "
                f"aviso insertado, ratio área={area / page_area:.2f})")
            continue
        done += 1
        started = time.perf_counter()
        try:
            texts = ocr_mod.ocr_image_region(page, bbox, config)
        except Exception as exc:  # noqa: BLE001 — el OCR nunca debe romper el lote
            log(f"[ocr] p{page.page_number}: OCR de imagen falló: {exc}")
            continue
        finally:
            if budget is not None:
                budget.remaining -= time.perf_counter() - started
        cleaned = [
            c for t in texts
            if (c := normalize_unicode(strip_pua(t, config)).strip())
        ]
        if not cleaned:
            continue
        log(f"[ocr] p{page.page_number}: {len(cleaned)} línea(s) reconocidas en imagen "
            f"(ratio área={area / page_area:.2f})")
        blocks.append(Block(kind="text", top=bbox[1], lines=[
            Line(text=c, size=0.0, bold=False, top=bbox[1], x0=bbox[0])
            for c in cleaned
        ]))
    return blocks


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

    if config.heading_demote_title_block:
        _demote_title_block(pages, config)


def _demote_title_block(pages: list[list[Block]], config: Config) -> None:
    """Degrada el bloque de título del inicio (§A1).

    Muchos documentos abren con varias líneas grandes seguidas (título, subtítulo,
    fecha/código) que caen todas en el mismo nivel de encabezado y se emiten como
    `#` repetidos. Si al principio del documento hay >=2 títulos consecutivos del
    mismo nivel (antes de cualquier texto de cuerpo o de un título de otro nivel),
    se renumeran a niveles descendentes: #, ##, ###...
    """
    if not pages:
        return
    prefix: list[Line] = []
    first_level: int | None = None
    for block in pages[0]:
        if block.kind != "text":
            break
        for line in block.lines:
            if not line.text.strip():
                continue
            if line.heading_level <= 0:
                first_level = -1                       # texto de cuerpo: corta
                break
            if first_level is None:
                first_level = line.heading_level
            if line.heading_level != first_level:
                break                                  # cambia de nivel: corta
            prefix.append(line)
        else:
            continue
        break

    if len(prefix) < 2:
        return
    for i, line in enumerate(prefix):
        line.heading_level = min(first_level + i, config.heading_max_levels)


_NUMBERED = re.compile(r"^\d+[.)]\s")


def _is_reinforced_heading(line: "Line", config: Config) -> bool:
    t = line.text.strip()
    if not line.bold or not (0 < len(t) <= config.heading_short_line_max_len):
        return False
    if t.endswith("."):
        return False
    return bool(_NUMBERED.match(t)) or t.endswith(":")
