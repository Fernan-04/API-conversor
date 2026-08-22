"""Estructura intermedia neutral del documento (§8.1).

Cualquier lector de formato (PDF/DOCX/PPTX/XLSX) traduce su entrada a un
`Document`, y el renderer traduce el `Document` a Markdown. Así, agregar un
formato nuevo (EPUB, HTML...) es escribir un lector más, sin tocar el renderer.

Los elementos llevan texto **RAW** (sin escapar): el escapado de Markdown es
responsabilidad del renderer, no del lector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Union


@dataclass
class Heading:
    """Un título. `level` 1..N se mapea a #, ##, ###..."""
    level: int
    text: str


@dataclass
class Paragraph:
    """Un párrafo de texto ya unido. `strong` marca negrita de línea/etiqueta."""
    text: str
    strong: bool = False


@dataclass
class ListBlock:
    """Una lista de viñetas. Cada ítem es texto ya unido y des-hifenizado."""
    items: list[str]


@dataclass
class Table:
    """Una tabla de datos. `rows[0]` se trata como cabecera al renderizar."""
    rows: list[list[str]]


@dataclass
class Raw:
    """Markdown ya formado que se emite VERBATIM (sin escapar).

    Para orígenes que ya son Markdown (`.md`): escapar `*`/`_`/`` ` `` los
    corromperría. El resto de elementos llevan texto sin escapar y el renderer
    los escapa; `Raw` es la excepción explícita y controlada.
    """
    text: str


Element = Union[Heading, Paragraph, ListBlock, Table, Raw]


@dataclass
class Document:
    """Un documento como lista de secciones; cada sección es una lista ordenada
    de elementos.

    Una "sección" representa una frontera natural del origen: página (PDF),
    diapositiva (PPTX) u hoja (XLSX). DOCX produce una sola sección. El renderer
    usa estas fronteras para `--page-markers` / `--page-break`.
    """
    sections: list[list[Element]] = field(default_factory=list)
