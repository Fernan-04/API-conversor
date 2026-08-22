"""Detección y filtrado de tablas (§5) — el corazón del proyecto.

Distingue tablas de DATOS reales de tablas de MAQUETACIÓN. La decisión se toma
en tres capas + un detector extra:

  a) descartar contenedores anidados (bbox A contiene a B, B no a A -> A es marco);
  b) `tidy_rows`: limpiar filas/columnas vacías antes de evaluar;
  c) heurísticas de "¿es tabla real?" con umbrales de `Config`
     (el discriminador limpio en estos PDFs es el nº de columnas);
  d) detector de listas de viñetas mal detectadas como tabla de 2 columnas.

Todos los umbrales viven en `Config`. `--verbose` imprime, por cada candidata,
sus métricas reales (filas×cols, fill, altura/página, concentración) y qué
umbral la descartó, para poder recalibrar sin tocar código.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from doc2md.config import Config
from doc2md.text_utils import normalize_unicode, strip_pua

_NUM = re.compile(r"^\d+([.,]\d+)?$")
_DASHES = re.compile(r"^-{2,}$")

Bbox = tuple[float, float, float, float]  # (x0, top, x1, bottom)


@dataclass
class AcceptedTable:
    bbox: Bbox
    rows: list[list[str]]
    top: float


def contains_bbox(a: Bbox, b: Bbox) -> bool:
    """True si el bbox `a` contiene por completo a `b`."""
    return a[0] <= b[0] and a[1] <= b[1] and a[2] >= b[2] and a[3] >= b[3]


def _clean_cell(cell: str | None, config: Config) -> str:
    if not cell:
        return ""
    text = normalize_unicode(strip_pua(cell, config)).replace("\n", " ")
    return " ".join(text.split())


def tidy_rows(rows: list[list], config: Config) -> list[list[str]]:
    """Limpia celdas, descarta filas totalmente vacías y columnas vacías (§5b)."""
    clean = [[_clean_cell(c, config) for c in row] for row in rows]
    clean = [row for row in clean if any(row)]
    if not clean:
        return []
    ncol = max(len(row) for row in clean)
    clean = [row + [""] * (ncol - len(row)) for row in clean]
    keep = [i for i in range(ncol) if any(row[i] for row in clean)]
    return [[row[i] for i in keep] for row in clean]


def _fill_ratio(rows: list[list[str]]) -> float:
    cells = [c for row in rows for c in row]
    return sum(1 for c in cells if c) / len(cells) if cells else 0.0


def _cell_concentration(rows: list[list[str]]) -> float:
    """Fracción del texto total que acapara la celda más grande."""
    texts = [c for row in rows for c in row if c]
    total = sum(len(c) for c in texts)
    if not total:
        return 0.0
    return max(len(c) for c in texts) / total


def is_bullet_list(rows: list[list[str]], config: Config) -> bool:
    """True si esto es en realidad una lista de viñetas, no una tabla.

    Caso APF1 p1/p2: tabla de <=2 columnas donde una columna está vacía en la
    mayoría de las filas y la otra empieza por un marcador de viñeta.
    """
    if not rows:
        return False
    ncol = len(rows[0])
    if ncol == 0 or ncol > config.bullet_table_max_cols:
        return False
    n = len(rows)
    empty_frac = [sum(1 for row in rows if not row[i]) / n for i in range(ncol)]
    if max(empty_frac) < config.bullet_empty_col_ratio:
        return False
    data_col = min(range(ncol), key=lambda i: empty_frac[i])
    cells = [row[data_col] for row in rows if row[data_col]]
    if not cells:
        return False
    starts = sum(1 for c in cells if c.lstrip()[:1] in config.bullet_markers)
    return starts / len(cells) >= 0.5


# --------------------------------------------------------------------------- #
# Pulido de tablas ("tabla limpia"). Cada función es un umbral configurable.
# --------------------------------------------------------------------------- #

def _join_cell_words(cell: str, config: Config) -> str:
    """(1) Re-une palabras partidas por salto de columna dentro de la celda."""
    if not cell:
        return cell
    valid_end = set(config.cell_word_valid_endings)
    out: list[str] = []
    for tok in cell.split(" "):
        if (out and tok and len(tok) <= config.cell_join_max_frag
                and tok.isalpha() and tok.islower()
                and len(out[-1]) >= config.cell_join_min_stem
                and out[-1][-1].isalpha() and out[-1][-1].islower()
                and out[-1][-1] not in valid_end):
            out[-1] = out[-1] + tok
        else:
            out.append(tok)
    return " ".join(out)


def _is_score_row(row: list[str], config: Config) -> bool:
    """(2) Fila huérfana de puntajes: primeras N celdas vacías, resto numérico."""
    lead = config.score_row_empty_leading
    if len(row) <= lead or any(row[:lead]):
        return False
    rest = [c for c in row[lead:] if c]
    return bool(rest) and all(_NUM.match(c) for c in rest)


def _is_separator_row(row: list[str]) -> bool:
    """(3) Fila compuesta solo de guiones (separador colado por corte de página)."""
    cells = [c for c in row if c]
    return bool(cells) and all(_DASHES.match(c) for c in cells)


def polish_rows(rows: list[list[str]], config: Config,
                log: Callable[[str], None], tag: str) -> list[list[str]]:
    """Aplica (1) unión de palabras, (2) fusión de puntajes y (3) quita separadores."""
    if not config.polish_tables:
        return rows
    rows = [[_join_cell_words(c, config) for c in row] for row in rows]

    result: list[list[str]] = []
    merged_scores = 0
    for row in rows:
        if config.drop_separator_rows and _is_separator_row(row):
            continue
        if config.merge_score_rows and result and _is_score_row(row, config):
            prev = result[-1]
            for i, c in enumerate(row):
                if c and i < len(prev):
                    prev[i] = (prev[i] + " " + c).strip() if prev[i] else c
            merged_scores += 1
            continue
        result.append(list(row))
    if merged_scores:
        log(f"[tabla] {tag} -> {merged_scores} fila(s) de puntajes fusionada(s)")
    return result


def merge_tables_across_pages(pages: list[list], config: Config,
                              log: Callable[[str], None]) -> None:
    """(4) Une tablas partidas entre páginas (misma nº de columnas, continuación)."""
    if not config.merge_tables_across_pages:
        return
    running = None          # Block de tabla que aún puede extenderse
    running_header: list[str] | None = None

    for pi, blocks in enumerate(pages):
        if (running is not None and blocks and blocks[0].kind == "table"
                and running.rows and blocks[0].rows
                and len(running.rows[0]) == len(blocks[0].rows[0])):
            cand = blocks[0]
            add = cand.rows
            if (config.merge_drop_repeated_header and running_header
                    and cand.rows[0] == running_header):
                add = cand.rows[1:]
                log(f"[tabla] p{pi + 1}: cabecera repetida eliminada al unir")
            running.rows.extend(add)
            running.rows = polish_rows(running.rows, config, log, f"unida@p{pi + 1}")
            log(f"[tabla] p{pi + 1}: tabla unida a la de la página anterior")
            blocks.pop(0)

        if blocks and blocks[-1].kind == "table":
            running = blocks[-1]
            running_header = running.rows[0] if running.rows else None
        elif blocks:
            running = None
            running_header = None
        # Si la página quedó vacía (su única tabla se unió), se mantiene `running`.


def select_tables(
    tables: list,
    page,
    config: Config,
    log: Callable[[str], None],
) -> list[AcceptedTable]:
    """Filtra las tablas candidatas de una página y devuelve las aceptadas.

    `log` recibe una línea por candidata (para --verbose).
    """
    bboxes: list[Bbox] = [t.bbox for t in tables]
    page_h = float(page.height) or 1.0
    accepted: list[AcceptedTable] = []

    for idx, table in enumerate(tables):
        bbox: Bbox = table.bbox
        rows = tidy_rows(table.extract(), config)
        nrow = len(rows)
        ncol = len(rows[0]) if rows else 0
        fill = _fill_ratio(rows)
        conc = _cell_concentration(rows)
        hratio = (bbox[3] - bbox[1]) / page_h
        tag = (f"p{page.page_number} T{idx} {nrow}x{ncol} "
               f"fill={fill:.2f} alt={hratio:.2f}x conc={conc:.2f}")

        # (a) contenedor de maquetación.
        if config.table_drop_containers and any(
            j != idx
            and contains_bbox(bbox, bboxes[j])
            and not contains_bbox(bboxes[j], bbox)
            for j in range(len(bboxes))
        ):
            log(f"[tabla] {tag} -> descartada (contenedor de maquetación)")
            continue

        # (c/d) heurísticas de tabla real.
        if nrow < config.table_min_rows:
            log(f"[tabla] {tag} -> descartada (filas {nrow} < min {config.table_min_rows})")
            continue
        if is_bullet_list(rows, config):
            log(f"[tabla] {tag} -> descartada (lista de viñetas, va como texto)")
            continue
        if ncol < config.table_min_cols:
            log(f"[tabla] {tag} -> descartada (columnas {ncol} < min {config.table_min_cols})")
            continue
        if conc > config.table_max_cell_concentration:
            log(f"[tabla] {tag} -> descartada (una celda concentra {conc:.2f} del texto)")
            continue

        rows = polish_rows(rows, config, log, tag)
        log(f"[tabla] {tag} -> ACEPTADA")
        accepted.append(AcceptedTable(bbox=bbox, rows=rows, top=bbox[1]))

    return accepted
