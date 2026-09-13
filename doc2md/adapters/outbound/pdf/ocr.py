"""OCR opcional para PDFs escaneados y para imágenes sin capa de texto (§2, §Ronda 6).

Solo se importa `pytesseract`/`pillow` si hace falta (página sin texto, o imagen
grande candidata), para no forzar la dependencia en instalaciones sin Tesseract.
Nunca rompe la conversión: si el binario no está disponible, `available()`
devuelve `False` y el llamador decide (página escaneada sin `--ocr`: aviso por
stderr; imagen grande sin texto: aviso VISIBLE en el propio Markdown, ver
`extract._ocr_big_images`).
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

_checked_binary: bool | None = None


def available() -> bool:
    """True si pytesseract+pillow están importables Y el binario `tesseract`
    responde. Se cachea (no cambia dentro de un mismo proceso) para no pagar el
    coste de lanzar el binario en cada página."""
    global _checked_binary
    if _checked_binary is not None:
        return _checked_binary
    try:
        import PIL  # noqa: F401
        import pytesseract
        pytesseract.get_tesseract_version()
    except Exception:  # noqa: BLE001 — falta la lib o el binario: OCR no disponible
        _checked_binary = False
    else:
        _checked_binary = True
    return _checked_binary


def ocr_page(page, config: Config) -> str:
    """Extrae texto de una página sin capa de texto mediante OCR (best-effort)."""
    import pytesseract

    image = page.to_image(resolution=300).original
    return pytesseract.image_to_string(image, lang=config.ocr_lang, timeout=config.ocr_timeout)


def ocr_image_region(page, bbox: tuple[float, float, float, float], config: Config) -> list[str]:
    """OCR de una región (imagen grande) de la página; devuelve líneas de texto.

    Agrupa las palabras reconocidas por (bloque, párrafo, línea) de Tesseract,
    en el orden en que las devuelve `image_to_data` (orden de lectura), y
    descarta palabras por debajo de `config.ocr_min_conf`. Cualquier excepción
    (timeout, imagen corrupta) se propaga: el llamador la registra y sigue con
    el resto del documento — el OCR de UNA imagen nunca debe romper el lote.
    """
    import pytesseract

    cropped = page.crop(bbox).to_image(resolution=200).original
    data = pytesseract.image_to_data(
        cropped,
        lang=config.ocr_lang,
        timeout=config.ocr_timeout,
        output_type=pytesseract.Output.DICT,
    )
    lines: dict[tuple[int, int, int], list[str]] = {}
    order: list[tuple[int, int, int]] = []
    n = len(data.get("text", []))
    for i in range(n):
        word = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not word or conf < config.ocr_min_conf:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
    return [" ".join(lines[k]) for k in order if lines[k]]
