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
class Span:
    """Un fragmento de texto inline con formato (§B, DOCX rico).

    Permite negrita/cursiva parcial e hipervínculos DENTRO de un párrafo o ítem,
    que el texto plano no puede representar. `link` = URL si el fragmento es un
    enlace. El texto va RAW (sin escapar); el renderer escapa y envuelve.
    """
    text: str
    bold: bool = False
    italic: bool = False
    link: str | None = None


@dataclass
class Paragraph:
    """Un párrafo de texto ya unido. `strong` marca negrita de línea/etiqueta.

    Si `spans` no es None, el renderer usa los spans (texto con formato inline) en
    vez de `text`; así un lector rico (DOCX) puede conservar negrita/cursiva/enlaces
    parciales, mientras los lectores simples siguen usando solo `text`.
    """
    text: str = ""
    strong: bool = False
    spans: "list[Span] | None" = None


@dataclass
class ListItem:
    """Un ítem de lista rico: spans + nivel de anidación + si es numerado."""
    spans: list[Span]
    level: int = 0
    ordered: bool = False


@dataclass
class ListBlock:
    """Una lista de viñetas. Cada ítem es texto ya unido y des-hifenizado.

    `rich_items` (opcional) lleva ítems con formato inline, anidación y numeración;
    si está presente tiene prioridad sobre `items`.
    """
    items: list[str]
    rich_items: "list[ListItem] | None" = None


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
