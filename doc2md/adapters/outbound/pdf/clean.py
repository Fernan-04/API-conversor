"""Limpieza a nivel de documento PDF (§6.2, §6.3).

Opera sobre las páginas ya estructuradas (listas de bloques de `extract.py`):
elimina cabeceras/pies repetidos y fragmentos basura de URLs partidas. Se llama
antes de detectar títulos.

La normalización Unicode y el descarte de glifos PUA se movieron a
`doc2md.text_utils` (son útiles para todos los formatos, no solo PDF).
"""

from __future__ import annotations

import re
from collections import Counter
from typing import TYPE_CHECKING

from doc2md.config import Config

if TYPE_CHECKING:
    from doc2md.adapters.outbound.pdf.extract import Block, Line


def _norm_key(text: str) -> str:
    """Clave normalizada para detectar líneas repetidas: minúsculas y dígitos
    colapsados, para que `Página 1/8` y `Página 2/8` coincidan."""
    return re.sub(r"\d+", "#", text.lower()).strip()


def _text_lines(page: list["Block"]) -> list["Line"]:
    lines = [line for block in page if block.kind == "text" for line in block.lines]
    return sorted(lines, key=lambda l: l.top)


def _remove_repeated(pages: list[list["Block"]], config: Config) -> None:
    """Elimina cabeceras/pies que se repiten en >= repeated_page_ratio páginas."""
    n = len(pages)
    counter: Counter[str] = Counter()
    for page in pages:
        lines = _text_lines(page)
        head = lines[: config.repeated_head_lines]
        tail = lines[-config.repeated_tail_lines:] if lines else []
        keys = {_norm_key(l.text) for l in head + tail if l.text.strip()}
        for key in keys:
            counter[key] += 1

    threshold = n * config.repeated_page_ratio
    repeated = {key for key, count in counter.items() if key and count >= threshold}
    if not repeated:
        return
    for page in pages:
        for block in page:
            if block.kind == "text":
                block.lines = [l for l in block.lines if _norm_key(l.text) not in repeated]


def _is_junk(line: "Line", config: Config) -> bool:
    """Fragmentos basura de URLs partidas: líneas muy cortas que no son viñetas."""
    t = line.text.strip()
    if len(t) > config.junk_line_max_len:
        return False
    return not any(t.startswith(m + " ") or t == m for m in config.bullet_markers)


def clean_document(pages: list[list["Block"]], config: Config) -> None:
    """Aplica la limpieza de documento in-place y descarta bloques vacíos."""
    if config.remove_repeated and len(pages) >= config.repeated_min_pages:
        _remove_repeated(pages, config)

    for page in pages:
        for block in page:
            if block.kind == "text":
                block.lines = [l for l in block.lines if not _is_junk(l, config)]
        page[:] = [b for b in page if b.kind != "text" or b.lines]
