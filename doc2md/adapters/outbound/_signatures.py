"""Validación de firma (magic bytes) — coherencia contenido ↔ extensión.

markitdown usa **Magika** (un modelo ML de Google) para detectar el tipo real por
contenido. Aquí replicamos la idea con una tabla mínima de firmas de la stdlib
(cero dependencias, apto para el plan gratis): comprobamos que los primeros bytes
del archivo son coherentes con la extensión declarada. Frena, por ejemplo, un
`.pdf` que en realidad es un ejecutable o un HTML.

El dispatch por extensión sigue viviendo en `router.py`; esto es una comprobación
defensiva adicional que cada lector llama al inicio de `read()`.

Nota honesta: los formatos OOXML (`.docx/.pptx/.xlsx`) comparten la firma ZIP
(`PK\\x03\\x04`), así que la firma NO distingue uno de otro — de eso se encarga el
parser correspondiente. La firma solo garantiza "esto es (al menos) un zip".
"""

from __future__ import annotations

from doc2md.domain.errors import CorruptFileError

# Firma esperada por extensión. Los OOXML son zip; sus subvariantes las valida el
# parser + la guarda anti zip-bomb (`_zip_guard`).
_ZIP_MAGIC = b"PK\x03\x04"
# ZIP vacío (`PK\x05\x06`) y ZIP spanned (`PK\x07\x08`) también son válidos.
_ZIP_MAGICS = (_ZIP_MAGIC, b"PK\x05\x06", b"PK\x07\x08")

_SIGNATURES: dict[str, tuple[bytes, ...]] = {
    ".pdf": (b"%PDF",),
    ".docx": _ZIP_MAGICS,
    ".pptx": _ZIP_MAGICS,
    ".xlsx": _ZIP_MAGICS,
}


def ensure_signature(data: bytes, extension: str) -> None:
    """Lanza `CorruptFileError` si el contenido no coincide con la extensión.

    Las extensiones de texto (`.txt/.md/.csv/.tsv`) no tienen firma binaria y no
    se comprueban aquí (son texto por naturaleza). Extensiones sin firma conocida
    se dejan pasar (la valida el propio lector).
    """
    expected = _SIGNATURES.get(extension.lower())
    if not expected:
        return
    head = data[:8]
    if not any(head.startswith(sig) for sig in expected):
        raise CorruptFileError(
            "El contenido del archivo no coincide con su extensión "
            f"({extension}): parece otro tipo de archivo.",
            detail=f"magic={head[:4]!r}",
        )
