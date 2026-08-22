"""Guarda anti "zip-bomb" para formatos OOXML (DOCX/PPTX/XLSX).

Un DOCX/PPTX/XLSX es un contenedor ZIP con XML dentro. Una entrada muy comprimida
(ratio enorme) o un total descomprimido gigantesco puede agotar la RAM del plan
gratis (~512 MB en Render) **antes** de que la librería de parseo llegue a
protegerse. markitdown lee todas las entradas sin ningún límite
(`_zip_converter.py`, `pre_process.py`); aquí lo evitamos.

`ensure_safe_zip` solo lee el **índice** del zip (`ZipInfo`: `file_size` y
`compress_size`) — NO descomprime nada — y rechaza si:
  - hay más de `config.zip_max_entries` entradas;
  - el total descomprimido supera `config.zip_max_uncompressed_bytes`;
  - el ratio descomprimido/comprimido supera `config.zip_max_ratio`.

Se llama al inicio de `read()` en los lectores OOXML, antes del import perezoso de
la librería pesada. Un archivo que no sea zip válido -> `CorruptFileError`.
"""

from __future__ import annotations

import io
import zipfile

from doc2md.config import Config
from doc2md.domain.errors import CorruptFileError, FileTooLargeError


def ensure_safe_zip(data: bytes, config: Config) -> None:
    """Valida el índice del zip contra los umbrales de `config`. No extrae nada."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise CorruptFileError(detail=f"zip inválido: {exc}") from exc

    try:
        infos = zf.infolist()
    finally:
        zf.close()

    if len(infos) > config.zip_max_entries:
        raise FileTooLargeError(
            "El archivo contiene demasiados elementos internos y podría agotar "
            "la memoria del servidor.",
            detail=f"entries={len(infos)} > {config.zip_max_entries}",
        )

    total_uncompressed = 0
    total_compressed = 0
    for info in infos:
        total_uncompressed += info.file_size
        total_compressed += info.compress_size

    if total_uncompressed > config.zip_max_uncompressed_bytes:
        raise FileTooLargeError(
            "El archivo se descomprime a un tamaño excesivo (posible archivo "
            "malicioso).",
            detail=(
                f"uncompressed={total_uncompressed} "
                f"> {config.zip_max_uncompressed_bytes}"
            ),
        )

    # Ratio de compresión: la señal más fiable de un zip-bomb. Se evalúa solo si
    # hay datos comprimidos apreciables (evita falsos positivos en zips diminutos).
    if total_compressed > 4096:
        ratio = total_uncompressed / total_compressed
        if ratio > config.zip_max_ratio:
            raise FileTooLargeError(
                "El archivo tiene una relación de compresión sospechosa "
                "(posible archivo malicioso).",
                detail=f"ratio={ratio:.1f} > {config.zip_max_ratio}",
            )
