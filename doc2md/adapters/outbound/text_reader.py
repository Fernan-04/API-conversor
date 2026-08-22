"""Lector de texto plano y Markdown: implementa el puerto `DocumentReader`.

Sin dependencias externas (solo stdlib), así que no añade superficie de ataque:

  - `.md`  -> se emite VERBATIM como un bloque `Raw` (ya es Markdown; escaparlo lo
              corromperría). El renderer solo normaliza el fin de línea.
  - `.txt` -> se parte en párrafos por líneas en blanco; cada bloque es un
              `Paragraph` (que el renderer sí escapa, porque es texto literal).

Un `.txt`/`.md` produce una sola sección.
"""

from __future__ import annotations

import re
from pathlib import Path

from doc2md.config import Config
from doc2md.domain.errors import CorruptFileError
from doc2md.domain.models import Document, Element, Paragraph, Raw
from doc2md.text_utils import clean_text

# Separador de párrafos: una o más líneas en blanco.
_BLANK_LINE = re.compile(r"\n[ \t]*\n")


def decode_text(data: bytes) -> str:
    """Decodifica bytes a texto: UTF-8 (con o sin BOM) y, si falla, latin-1.

    latin-1 nunca falla (mapea cualquier byte), así que sirve de red de
    seguridad para textos en otras codificaciones de un byte.
    """
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1")


class TextReader:
    """Adaptador de lectura de `.txt` / `.md` (puerto `DocumentReader`)."""

    def read(self, data: bytes, filename: str, config: Config) -> Document:
        try:
            text = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
        except Exception as exc:  # noqa: BLE001 — se traduce a error tipificado
            raise CorruptFileError(detail=str(exc)) from exc

        ext = Path(filename).suffix.lower()
        if ext == ".md":
            body = text.strip("\n")
            sections = [[Raw(text=body)]] if body.strip() else []
            return Document(sections=sections)

        # `.txt`: un párrafo por bloque separado por líneas en blanco.
        elements: list[Element] = []
        for block in _BLANK_LINE.split(text):
            cleaned = clean_text(block, config).strip()
            if cleaned:
                elements.append(Paragraph(text=cleaned))
        return Document(sections=[elements] if elements else [])
