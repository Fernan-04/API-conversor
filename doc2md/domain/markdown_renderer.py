"""Renderer de la estructura neutral a Markdown (§8.1, salida).

Puro: opera sobre `Document`/`Element`, no sabe nada de PDF/Word/Excel. Toda la
sintaxis Markdown (escapado, tablas, viñetas, títulos) vive aquí.

Este módulo hereda las reglas del antiguo `render.py` de pdf2md; la clasificación
de líneas (título/viñeta/párrafo) y la des-hifenización ahora las hace cada
lector al construir el `Document`, de modo que aquí solo se escapa y se envuelve.
La salida para PDF es idéntica a la de pdf2md (lo verifica `tests/test_pdf.py`).
"""

from __future__ import annotations

import re

from doc2md.config import Config
from doc2md.domain.models import (
    Document,
    Element,
    Heading,
    ListBlock,
    Paragraph,
    Table,
)

# Escapado conservador (§6.8): solo los caracteres que rompen Markdown en línea.
# Deliberadamente NO se escapan ()[]{}+# porque en prosa española generan mucho
# ruido (`\(general\)`) sin aportar seguridad; se documenta en el README.
_ESCAPE = ("\\", "`", "*", "_")


def _escape(text: str) -> str:
    for ch in _ESCAPE:
        text = text.replace(ch, "\\" + ch)
    return text


def _escape_cell(text: str) -> str:
    # En celdas: sin saltos de línea y con `|` escapado (§6.8).
    return text.replace("\n", " ").replace("|", "\\|")


def _render_table(rows: list[list[str]]) -> str:
    if not rows:
        return ""
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    header = rows[0]
    out = [
        "| " + " | ".join(_escape_cell(c) for c in header) + " |",
        "| " + " | ".join(["---"] * ncol) + " |",
    ]
    for r in rows[1:]:
        out.append("| " + " | ".join(_escape_cell(c) for c in r) + " |")
    return "\n".join(out)


def _render_element(el: Element, config: Config) -> str:
    if isinstance(el, Heading):
        text = el.text.strip()
        if not text:
            return ""
        return "#" * el.level + " " + _escape(text)
    if isinstance(el, Paragraph):
        text = _escape(el.text)
        if config.mark_bold and el.strong and text:
            text = f"**{text}**"
        return text
    if isinstance(el, ListBlock):
        return "\n".join("- " + _escape(item) for item in el.items if item)
    if isinstance(el, Table):
        return _render_table(el.rows)
    return ""


class MarkdownRendererImpl:
    """Implementación del puerto `MarkdownRenderer`."""

    def render(self, document: Document, config: Config) -> str:
        parts: list[str] = []
        last = len(document.sections) - 1
        for si, elements in enumerate(document.sections):
            if config.page_markers:
                parts.append(f"<!-- pagina {si + 1} -->")
            for el in elements:
                rendered = _render_element(el, config)
                if rendered:
                    parts.append(rendered)
            if config.page_break and si < last:
                parts.append("---")

        md = "\n\n".join(parts)
        md = re.sub(r"\n{3,}", "\n\n", md)   # colapsar saltos múltiples (§6.3)
        return md.strip() + "\n"


# Instancia por defecto reutilizable (el renderer no tiene estado).
DEFAULT_RENDERER = MarkdownRendererImpl()


def render_markdown(document: Document, config: Config) -> str:
    """Atajo funcional sobre el renderer por defecto."""
    return DEFAULT_RENDERER.render(document, config)
