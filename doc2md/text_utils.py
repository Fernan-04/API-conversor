"""Utilidades de texto puras, compartidas por todos los lectores (§6.5).

Antes vivían en `clean.py` (específico de PDF); se extrajeron aquí porque la
normalización Unicode y el descarte de glifos de la Private Use Area son útiles
para cualquier formato de origen (DOCX/PPTX/XLSX también arrastran ligaduras y
comillas tipográficas). No dependen de ninguna librería de parseo.
"""

from __future__ import annotations

from doc2md.config import Config

# Ligaduras tipográficas y caracteres Unicode "de imprenta" -> ASCII sensato.
_UNICODE_MAP = {
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi",
    "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st",
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "‒": "-", "−": "-",
    "…": "...",
    " ": " ", " ": " ", " ": " ", "​": "",
}

_TRANS = str.maketrans(_UNICODE_MAP)


def strip_pua(text: str, config: Config) -> str:
    """Elimina glifos del rango Private Use Area (iconos de UI)."""
    lo, hi = config.pua_start, config.pua_end
    if not text:
        return text
    return "".join(ch for ch in text if not (lo <= ord(ch) <= hi))


def normalize_unicode(text: str) -> str:
    """Normaliza ligaduras, comillas tipográficas, guiones y espacios duros."""
    if not text:
        return text
    return text.translate(_TRANS)


def clean_text(text: str, config: Config) -> str:
    """Normaliza Unicode, descarta glifos PUA y colapsa espacios/tabs/saltos.

    Lo usan los lectores de Office (DOCX/PPTX/XLSX), donde cada valor lógico es
    una sola línea: tabs y espacios múltiples de maquetación se colapsan a un
    espacio. El pipeline PDF NO usa esta función (conserva su propio manejo de
    espacios), así que la garantía de regresión de PDF no se ve afectada.
    """
    text = normalize_unicode(strip_pua(text, config))
    return " ".join(text.split())
