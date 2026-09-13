"""Lector de HTML pegado desde el portapapeles: implementa el puerto
`DocumentReader` (§Ronda 6, "Pegar texto").

Sin dependencias externas (solo `html.parser` de la stdlib): cuando el usuario
copia texto con formato desde una web, Google Docs, Notion o Word y lo pega en
el cuadro de texto del frontend, el navegador adjunta también el HTML del
portapapeles (`clipboardData.getData("text/html")`). El frontend lo envía como
si fuera un archivo `.html`/`.htm` y este lector reconstruye la estructura:

  - `h1`-`h6` -> `Heading`.
  - `p`/`div`/similares SIN hijos de bloque -> `Paragraph` con `spans` (negrita/
    cursiva/enlaces inline). Un `div`/`p` que SÍ envuelve otros bloques (Google
    Docs envuelve todo el documento en un solo `<div>`/`<b>`) se trata como
    contenedor transparente: se recorren sus hijos, no su texto plano.
  - `ul`/`ol` (con anidación) -> `ListBlock` con `rich_items`.
  - `table` -> `Table` (texto plano por celda; primera fila = cabecera).
  - `pre`/`code` de bloque -> `Raw` como bloque de código Markdown.
  - `blockquote` -> `Raw` con `> ` (se aplana el formato inline interno).
  - `br` -> espacio; `img[alt]` -> `[Imagen: alt]`.
  - `script`/`style`/`head`/`meta`/`svg`/`iframe`/`form`/controles de formulario
    se ignoran por completo (nunca se ejecuta nada, solo se lee texto).

Detecta correctamente la trampa de Google Docs: el envoltorio
`<b style="font-weight:normal" id="docs-internal-guid-...">` NO cuenta como
negrita (el `style` explícito manda sobre la etiqueta `<b>`).

Limitación aceptada: Google Docs no siempre emite `<h1>`-`<h6>` reales para sus
estilos de título (usa `<span>` con tamaño de fuente grande); en ese caso el
texto se conserva como párrafo normal (sin pérdida de contenido, solo sin
promoción automática a título).
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from doc2md.config import Config
from doc2md.domain.errors import CorruptFileError
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
from doc2md.text_utils import (
    detect_language,
    fix_punct_spacing,
    is_all_caps,
    normalize_unicode,
    strip_pua,
    title_case,
)

_VOID_TAGS = frozenset(
    "br hr img meta link input source col area base embed wbr".split()
)
_IGNORED_TAGS = frozenset(
    "script style head meta link svg iframe form button input select "
    "textarea noscript object canvas".split()
)
_HEADING_LEVEL = {f"h{i}": i for i in range(1, 7)}
_BLOCK_LEVEL = frozenset(
    "p div section article header footer main aside ul ol table blockquote "
    "pre hr h1 h2 h3 h4 h5 h6 tr thead tbody tfoot li figure figcaption".split()
)
_INLINE_CONTAINER_TAGS = frozenset(
    "p div span section article header footer main aside body html font "
    "figcaption label".split()
)


class _Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag: str, attrs: list[tuple[str, str | None]]):
        self.tag = tag
        self.attrs = {k: (v or "") for k, v in attrs}
        self.children: list["_Node | str"] = []


class _TreeBuilder(HTMLParser):
    """Construye un árbol tolerante a HTML mal formado, ignorando tags peligrosos
    o irrelevantes (nunca se ejecuta nada: es solo texto)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", [])
        self._stack: list[_Node] = [self.root]
        self._skip_depth = 0
        self._skip_tag: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth += 1
            return
        if tag in _IGNORED_TAGS:
            self._skip_depth = 1
            self._skip_tag = tag
            return
        node = _Node(tag, attrs)
        self._stack[-1].children.append(node)
        if tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if self._skip_depth:
            return
        self._stack[-1].children.append(_Node(tag, attrs))

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._skip_depth:
            if tag == self._skip_tag:
                self._skip_depth -= 1
            return
        for i in range(len(self._stack) - 1, 0, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                return

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._stack[-1].children.append(data)


_WS_RE = re.compile(r"[ \t\r\n\f]+")
_BOLD_STYLE_RE = re.compile(r"font-weight\s*:\s*(bold|[5-9]\d\d)")


def _collapse_ws(text: str) -> str:
    """Colapsa saltos/tabs/espacios repetidos a UNO solo, SIN recortar los
    extremos (un espacio al borde de un nodo es el separador con el vecino)."""
    return _WS_RE.sub(" ", text) if text else text


def _clean_fragment(text: str, config: Config) -> str:
    text = normalize_unicode(strip_pua(text, config))
    text = _collapse_ws(text)
    return fix_punct_spacing(text)


def _is_bold(node: "_Node") -> bool:
    """El `style` explícito manda sobre la etiqueta (trampa de Google Docs:
    `<b style="font-weight:normal">` envuelve TODO el documento y no es negrita)."""
    style = node.attrs.get("style", "").lower()
    if "font-weight" in style:
        if "normal" in style or re.search(r"font-weight\s*:\s*[1-4]\d\d\b", style):
            return False
        return bool(_BOLD_STYLE_RE.search(style))
    return node.tag in ("b", "strong")


def _is_italic(node: "_Node") -> bool:
    style = node.attrs.get("style", "").lower()
    if "font-style" in style:
        return "italic" in style
    return node.tag in ("i", "em")


def _spans_from_nodes(
    nodes: list["_Node | str"], config: Config,
    bold: bool = False, italic: bool = False, link: str | None = None,
) -> list[Span]:
    out: list[Span] = []
    for child in nodes:
        if isinstance(child, str):
            text = _clean_fragment(child, config)
            if text:
                out.append(Span(text=text, bold=bold, italic=italic, link=link))
            continue
        tag = child.tag
        if tag == "br":
            out.append(Span(text=" "))
            continue
        if tag == "img":
            alt = _clean_fragment(child.attrs.get("alt", ""), config).strip()
            if alt:
                out.append(Span(text=f"[Imagen: {alt}]"))
            continue
        if tag in _IGNORED_TAGS:
            continue
        cb = bold or _is_bold(child)
        ci = italic or _is_italic(child)
        clink = link
        if tag == "a":
            href = child.attrs.get("href", "").strip()
            if href and not href.lower().startswith(("javascript:", "#")):
                clink = href
        out.extend(_spans_from_nodes(child.children, config, cb, ci, clink))
    return out


def _spans_to_bare(spans: list[Span]) -> str:
    """Texto plano de unos spans, sin sintaxis Markdown (para títulos/celdas de
    tabla: `Heading`/`Table` no llevan formato inline en el modelo de dominio)."""
    return "".join(s.text for s in spans).strip()


def _has_block_child(node: "_Node") -> bool:
    return any(not isinstance(c, str) and c.tag in _BLOCK_LEVEL for c in node.children)


def _find_rows(node: "_Node") -> list["_Node"]:
    rows: list[_Node] = []
    for c in node.children:
        if isinstance(c, str):
            continue
        if c.tag == "tr":
            rows.append(c)
        elif c.tag in ("thead", "tbody", "tfoot"):
            rows.extend(_find_rows(c))
    return rows


def _convert_table(node: "_Node", config: Config) -> Table | None:
    rows: list[list[str]] = []
    for tr in _find_rows(node):
        cells = [
            _spans_to_bare(_spans_from_nodes(c.children, config))
            for c in tr.children
            if not isinstance(c, str) and c.tag in ("td", "th")
        ]
        if cells:
            rows.append(cells)
    return Table(rows=rows) if rows else None


def _convert_list(node: "_Node", config: Config, ordered: bool, level: int) -> list[ListItem]:
    items: list[ListItem] = []
    for child in node.children:
        if isinstance(child, str) or child.tag != "li":
            continue
        own: list[_Node | str] = []
        nested: list[_Node] = []
        for c in child.children:
            if not isinstance(c, str) and c.tag in ("ul", "ol"):
                nested.append(c)
            else:
                own.append(c)
        spans = _spans_from_nodes(own, config)
        if any(s.text.strip() for s in spans):
            items.append(ListItem(spans=spans, level=level, ordered=ordered))
        for nl in nested:
            items.extend(_convert_list(nl, config, ordered=(nl.tag == "ol"), level=level + 1))
    return items


def _node_plain_text(node: "_Node") -> str:
    parts: list[str] = []
    for c in node.children:
        parts.append(c if isinstance(c, str) else _node_plain_text(c))
    return "".join(parts)


def _heading_text(text: str, config: Config, lang: str) -> str:
    """Title Case si el título viene EN MAYÚSCULAS (igual criterio que el
    lector PDF); un HTML pegado no tiene el concepto de "bloque de título de
    portada", así que aquí se aplica a TODOS los niveles."""
    if config.titlecase_headings and is_all_caps(text):
        return title_case(text, lang)
    return text


def _convert_children(
    nodes: list["_Node | str"], config: Config, lang: str = "es"
) -> list[Element]:
    elements: list[Element] = []
    for node in nodes:
        if isinstance(node, str):
            text = _clean_fragment(node, config).strip()
            if text:
                elements.append(Paragraph(text=text))
            continue
        tag = node.tag
        if tag in _IGNORED_TAGS or (tag in _VOID_TAGS and tag not in ("hr", "img")):
            continue
        if tag == "img":
            alt = _clean_fragment(node.attrs.get("alt", ""), config).strip()
            if alt:
                elements.append(Paragraph(text=f"[Imagen: {alt}]"))
            continue
        if tag in _HEADING_LEVEL:
            text = _spans_to_bare(_spans_from_nodes(node.children, config))
            if text:
                elements.append(Heading(
                    level=_HEADING_LEVEL[tag], text=_heading_text(text, config, lang)
                ))
            continue
        if tag in ("ul", "ol"):
            items = _convert_list(node, config, ordered=(tag == "ol"), level=0)
            if items:
                elements.append(ListBlock(items=[], rich_items=items))
            continue
        if tag == "table":
            table = _convert_table(node, config)
            if table is not None:
                elements.append(table)
            continue
        if tag == "blockquote":
            text = _clean_fragment(_node_plain_text(node), config).strip()
            if text:
                elements.append(Raw(text="> " + text.replace("\n", "\n> ")))
            continue
        if tag == "pre":
            code = _node_plain_text(node).strip("\n")
            if code.strip():
                elements.append(Raw(text=f"```\n{code}\n```"))
            continue
        if tag == "hr":
            elements.append(Raw(text="---"))
            continue
        if tag in _INLINE_CONTAINER_TAGS or tag not in _BLOCK_LEVEL:
            # Contenedor transparente (div/span/etc. o un tag desconocido): si
            # envuelve OTROS bloques, se recorren sus hijos; si es hoja de
            # texto inline, se emite como un único párrafo con formato.
            if _has_block_child(node):
                elements.extend(_convert_children(node.children, config, lang))
            else:
                spans = _spans_from_nodes(node.children, config)
                if any(s.text.strip() for s in spans):
                    elements.append(Paragraph(spans=spans, text=_spans_to_bare(spans)))
            continue
        # Cualquier otro bloque no contemplado: recorrer hijos igualmente.
        elements.extend(_convert_children(node.children, config, lang))
    return elements


def _decode(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


class HtmlReader:
    """Adaptador de lectura de HTML pegado (puerto `DocumentReader`)."""

    def read(self, data: bytes, filename: str, config: Config) -> Document:
        try:
            html = _decode(data)
        except Exception as exc:  # noqa: BLE001 — se traduce a error tipificado
            raise CorruptFileError(detail=str(exc)) from exc

        builder = _TreeBuilder()
        try:
            builder.feed(html)
            builder.close()
        except Exception as exc:  # noqa: BLE001 — HTML mal formado: no debe tumbar la API
            raise CorruptFileError(detail=str(exc)) from exc

        lang = detect_language(_node_plain_text(builder.root))
        elements = _convert_children(builder.root.children, config, lang)
        sections = [elements] if elements else []
        return Document(sections=sections, language=lang)
