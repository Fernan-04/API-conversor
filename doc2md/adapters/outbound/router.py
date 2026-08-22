"""Router de formato: elige el lector según la extensión (§8.1).

Vive en la capa de adaptadores, no en el dominio. Agregar un formato es añadir
una entrada aquí y un lector nuevo — sin tocar el dominio ni el renderer.
"""

from __future__ import annotations

from pathlib import Path

from doc2md.adapters.outbound.docx_reader import DocxReader
from doc2md.adapters.outbound.pdf.reader import PdfReader
from doc2md.adapters.outbound.pptx_reader import PptxReader
from doc2md.adapters.outbound.xlsx_reader import XlsxReader
from doc2md.domain.errors import UnsupportedFormatError
from doc2md.domain.ports import DocumentReader

# Una instancia por formato (los lectores no tienen estado; las libs pesadas se
# importan de forma perezosa dentro de cada `read`).
_READERS: dict[str, DocumentReader] = {
    ".pdf": PdfReader(),
    ".docx": DocxReader(),
    ".pptx": PptxReader(),
    ".xlsx": XlsxReader(),
}


def supported_extensions() -> tuple[str, ...]:
    return tuple(_READERS)


def reader_for(filename: str) -> DocumentReader:
    """Devuelve el lector adecuado para `filename`, o lanza UnsupportedFormatError."""
    ext = Path(filename).suffix.lower()
    try:
        return _READERS[ext]
    except KeyError:
        raise UnsupportedFormatError(ext) from None
