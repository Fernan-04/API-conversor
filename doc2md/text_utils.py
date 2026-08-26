"""Utilidades de texto puras, compartidas por todos los lectores (§6.5).

Antes vivían en `clean.py` (específico de PDF); se extrajeron aquí porque la
normalización Unicode y el descarte de glifos de la Private Use Area son útiles
para cualquier formato de origen (DOCX/PPTX/XLSX también arrastran ligaduras y
comillas tipográficas). No dependen de ninguna librería de parseo.
"""

from __future__ import annotations

import re

from doc2md.config import Config

# Glifos que pdfplumber no pudo mapear por falta de ToUnicode CMap: aparecen como
# el literal "(cid:NNN)" incrustado en el texto ("espec(cid:237)ficos"). Para las
# fuentes de estos documentos, NNN coincide con el codepoint Latin-1 del carácter
# (237 -> "í"), así que se traduce cuando cae en un rango imprimible y, si no, se
# elimina el ruido. Repara la mayoría de los cid sin inventar caracteres.
_CID_RE = re.compile(r"\(cid:(\d+)\)")


def _repair_cid(text: str) -> str:
    def sub(m: "re.Match[str]") -> str:
        code = int(m.group(1))
        # Rangos imprimibles de Latin-1 (evita controles C0/C1).
        if 0x20 <= code <= 0x7E or 0xA0 <= code <= 0xFF:
            return chr(code)
        return ""
    return _CID_RE.sub(sub, text)


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
    """Normaliza ligaduras, comillas tipográficas, guiones y espacios duros.

    También repara los glifos `(cid:NNN)` que deja pdfplumber cuando la fuente no
    trae CMap ToUnicode (ver `_repair_cid`).
    """
    if not text:
        return text
    return _repair_cid(text).translate(_TRANS)


# Palabras "menores" del español que van en minúscula dentro de un título (salvo
# si son la primera palabra). Cubre artículos, conjunciones y preposiciones cortas.
_TITLE_MINOR = frozenset(
    "de del la el los las un una unos unas y e o u a en con por para al".split()
)
# Siglas/acrónimos que deben conservar sus mayúsculas dentro de un título.
_TITLE_ACRONYMS = frozenset(
    "UML RUP BPMN IDEF RSU PPT APF PA PROY TF PC SQL CRC UTP HDFS NoSQL BD".split()
)


def _is_all_caps(text: str) -> bool:
    """True si el texto no tiene minúsculas y sí al menos una mayúscula."""
    has_upper = False
    for ch in text:
        if ch.islower():
            return False
        if ch.isupper():
            has_upper = True
    return has_upper


def title_case_es(text: str) -> str:
    """Convierte un título EN MAYÚSCULAS a Title Case en español.

    Solo actúa si el texto viene todo en mayúsculas ("FUNDAMENTACIÓN" ->
    "Fundamentación", "AVANCE DE PROYECTO FINAL 1" -> "Avance de Proyecto Final
    1"). Si ya trae minúsculas (p. ej. un subtítulo en sentence-case) se devuelve
    tal cual, para no estropear texto bien formado. Conserva siglas (`_TITLE_ACRONYMS`)
    y cualquier token con dígitos (APF1, PC2).
    """
    if not text or not _is_all_caps(text):
        return text
    words = text.split(" ")
    out: list[str] = []
    for i, w in enumerate(words):
        if not w:
            out.append(w)
            continue
        if w in _TITLE_ACRONYMS or any(c.isdigit() for c in w):
            out.append(w)                      # sigla o token con número: intacto
        elif i > 0 and w.lower() in _TITLE_MINOR:
            out.append(w.lower())              # palabra menor: minúscula
        else:
            out.append(w.capitalize())         # capitaliza (respeta acentos)
    return " ".join(out)


def clean_text(text: str, config: Config) -> str:
    """Normaliza Unicode, descarta glifos PUA y colapsa espacios/tabs/saltos.

    Lo usan los lectores de Office (DOCX/PPTX/XLSX), donde cada valor lógico es
    una sola línea: tabs y espacios múltiples de maquetación se colapsan a un
    espacio. El pipeline PDF NO usa esta función (conserva su propio manejo de
    espacios), así que la garantía de regresión de PDF no se ve afectada.
    """
    text = normalize_unicode(strip_pua(text, config))
    return " ".join(text.split())
