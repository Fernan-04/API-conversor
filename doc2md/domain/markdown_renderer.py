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
    ListItem,
    Paragraph,
    Raw,
    Span,
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


# URL suelta (http/https). Se corta en espacio o paréntesis de cierre.
_URL_RE = re.compile(r"https?://[^\s)]+")


def _url_label(url: str) -> str:
    host = re.sub(r"^https?://", "", url).split("/", 1)[0]
    return "Ver en biblioteca" if "biblioteca" in host.lower() else host


def _render_inline(text: str, config: Config) -> str:
    """Escapa el texto y, si procede, convierte URLs sueltas en enlaces Markdown.

    El autolinking se hace ANTES de escapar cada tramo, porque `_escape` rompería
    los `_` de la URL. La URL va sin escapar dentro de `[etiqueta](url)`.
    """
    if not config.autolink_urls or "http" not in text:
        return _escape(text)
    out: list[str] = []
    last = 0
    for m in _URL_RE.finditer(text):
        raw = m.group(0)
        url = raw.rstrip(".,;:)]")           # puntuación final que no es de la URL
        trailing = raw[len(url):]
        out.append(_escape(text[last:m.start()]))
        out.append(f"[{_url_label(url)}]({url})")
        out.append(_escape(trailing))
        last = m.end()
    out.append(_escape(text[last:]))
    return "".join(out)


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


def _render_span(span: Span, config: Config) -> str:
    """Renderiza un span inline: escapa el texto y aplica enlace/negrita/cursiva.

    Los marcadores (`**`, `*`) se colocan alrededor del texto SIN los espacios de
    los bordes (`**hola **` es inválido en Markdown), reponiéndolos por fuera.
    """
    if span.link:
        label = _escape(span.text.strip()) or span.link
        return f"[{label}]({span.link})"
    text = span.text
    lead = text[: len(text) - len(text.lstrip())]
    trail = text[len(text.rstrip()):]
    core = _escape(text.strip())
    if core:
        if span.bold and span.italic:
            core = f"***{core}***"
        elif span.bold:
            core = f"**{core}**"
        elif span.italic:
            core = f"*{core}*"
    return f"{lead}{core}{trail}"


def _render_spans(spans: "list[Span]", config: Config) -> str:
    return "".join(_render_span(s, config) for s in spans).strip()


def _render_list_items(items: "list[ListItem]", config: Config) -> str:
    """Renderiza ítems ricos con anidación (sangría de 2 espacios por nivel) y
    marcador `1.` si son numerados, `-` si son viñetas."""
    lines: list[str] = []
    for it in items:
        body = _render_spans(it.spans, config)
        if not body:
            continue
        marker = "1." if it.ordered else "-"
        lines.append("  " * max(it.level, 0) + f"{marker} " + body)
    return "\n".join(lines)


def _render_element(el: Element, config: Config) -> str:
    if isinstance(el, Heading):
        text = el.text.strip()
        if not text:
            return ""
        return "#" * el.level + " " + _escape(text)
    if isinstance(el, Paragraph):
        if el.spans is not None:
            return _render_spans(el.spans, config)   # negrita/cursiva/enlaces ya en los spans
        text = _render_inline(el.text, config)
        if config.mark_bold and el.strong and text:
            text = f"**{text}**"
        return text
    if isinstance(el, ListBlock):
        if el.rich_items is not None:
            return _render_list_items(el.rich_items, config)
        return "\n".join("- " + _render_inline(item, config) for item in el.items if item)
    if isinstance(el, Table):
        return _render_table(el.rows)
    if isinstance(el, Raw):
        # Verbatim: el origen ya es Markdown. Solo se normaliza el fin de línea.
        return el.text.strip("\n")
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
