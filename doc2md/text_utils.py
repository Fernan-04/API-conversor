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


def is_all_caps(text: str) -> bool:
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
    if not text or not is_all_caps(text):
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


# Palabras menores en inglés que van en minúscula dentro de un título (salvo si
# son la primera o última palabra), estilo Title Case editorial en-US.
_TITLE_MINOR_EN = frozenset(
    "a an the and or but nor for so yet as at by in of on to up via vs "
    "with from into onto than".split()
)


def title_case_en(text: str) -> str:
    """Convierte un título EN MAYÚSCULAS a Title Case en inglés.

    Análogo a `title_case_es`: solo actúa si el texto viene todo en mayúsculas.
    Primera y última palabra siempre capitalizadas; las palabras menores
    (`_TITLE_MINOR_EN`) van en minúscula en medio del título.
    """
    if not text or not is_all_caps(text):
        return text
    words = text.split(" ")
    last = len(words) - 1
    out: list[str] = []
    for i, w in enumerate(words):
        if not w:
            out.append(w)
            continue
        if any(c.isdigit() for c in w):
            out.append(w)
        elif 0 < i < last and w.lower() in _TITLE_MINOR_EN:
            out.append(w.lower())
        else:
            out.append(w.capitalize())
    return " ".join(out)


def title_case(text: str, lang: str = "es") -> str:
    """Despacha a `title_case_es`/`title_case_en` según `lang` (§Ronda 6)."""
    return title_case_en(text) if lang == "en" else title_case_es(text)


# --------------------------------------------------------------------------- #
# Detección de idioma (§Ronda 6) — sin dependencias, basada en stopwords.
# --------------------------------------------------------------------------- #

# Palabras funcionales muy frecuentes y casi exclusivas de cada idioma. No hace
# falta una lista exhaustiva: basta con que discrimine sobre prosa real.
_STOPWORDS_ES = frozenset(
    "el la los las de del que y en un una para con por como su es son al se "
    "los su desde entre sobre pero más también sin ya fue eran esta este "
    "esa ese sus les nos o e u a".split()
)
_STOPWORDS_EN = frozenset(
    "the and of in on at to for by as is are that this with from or an a "
    "be was were will would can could should their its into about which "
    "these those has have had not".split()
)

_WORD_RE = re.compile(r"[a-záéíóúñü]+", re.IGNORECASE)


def detect_language(text: str) -> str:
    """Detecta si `text` está en español o inglés ("es"/"en"), sin dependencias.

    Cuenta ocurrencias de *stopwords* de cada idioma sobre una muestra del
    texto. Con texto insuficiente o empate, por defecto "es" (idioma histórico
    del proyecto). Pensado para llamarse una vez por documento (no por línea).
    """
    words = [w.lower() for w in _WORD_RE.findall(text[:20000])]
    if len(words) < 8:
        return "es"
    es_hits = sum(1 for w in words if w in _STOPWORDS_ES)
    en_hits = sum(1 for w in words if w in _STOPWORDS_EN)
    return "en" if en_hits > es_hits else "es"


# --------------------------------------------------------------------------- #
# Espaciado de puntuación (§Ronda 6) — arregla el "espacio antes de la coma"
# que dejan algunos PDFs maquetados con separación de caracteres manual
# ("aprendizaje , creatividad" -> "aprendizaje, creatividad").
# --------------------------------------------------------------------------- #

# Cierre de puntuación: sin espacio ANTES. No incluye ¿/¡ (son apertura) ni
# guiones (ya normalizados) ni comillas (ambiguas: pueden abrir o cerrar).
_SPACE_BEFORE_CLOSE = re.compile(r"[ \t]+([,.;:!?)\]»])")
# Apertura de puntuación: sin espacio DESPUÉS.
_SPACE_AFTER_OPEN = re.compile(r"([(\[«])[ \t]+")


def fix_punct_spacing(text: str) -> str:
    """Quita el espacio sobrante antes de cierres y después de aperturas.

    No toca saltos de línea ni colapsa espacios múltiples en otro contexto;
    solo corrige la separación pegada a estos signos de puntuación.
    """
    if not text:
        return text
    text = _SPACE_BEFORE_CLOSE.sub(r"\1", text)
    text = _SPACE_AFTER_OPEN.sub(r"\1", text)
    return text


def clean_text(text: str, config: Config) -> str:
    """Normaliza Unicode, descarta glifos PUA y colapsa espacios/tabs/saltos.

    Lo usan los lectores de Office (DOCX/PPTX/XLSX), donde cada valor lógico es
    una sola línea: tabs y espacios múltiples de maquetación se colapsan a un
    espacio. El pipeline PDF NO usa esta función (conserva su propio manejo de
    espacios), así que la garantía de regresión de PDF no se ve afectada.
    """
    text = normalize_unicode(strip_pua(text, config))
    return fix_punct_spacing(" ".join(text.split()))
