"""OCR opcional para PDFs escaneados (§2, andamiaje).

Solo se importa `pytesseract`/`pillow` si se pasa `--ocr`, para no forzar la
dependencia. Ninguno de los PDFs de prueba lo necesita (ambos tienen capa de
texto); esto queda como esqueleto con mensajes claros de instalación.
"""

from __future__ import annotations

from doc2md.config import Config

INSTALL_HINT = (
    "OCR requiere pytesseract + pillow y el binario tesseract:\n"
    "  pip install pytesseract pillow\n"
    "  Windows: https://github.com/UB-Mannheim/tesseract/wiki\n"
    "  macOS:   brew install tesseract tesseract-lang\n"
    "  Linux:   sudo apt install tesseract-ocr tesseract-ocr-spa"
)


def available() -> bool:
    """True si pytesseract y pillow están importables (no valida el binario)."""
    try:
        import PIL  # noqa: F401
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    return True


def ocr_page(page, config: Config) -> str:
    """Extrae texto de una página sin capa de texto mediante OCR (best-effort)."""
    import pytesseract

    image = page.to_image(resolution=300).original
    return pytesseract.image_to_string(image, lang=config.ocr_lang)
