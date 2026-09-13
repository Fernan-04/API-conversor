"""Tests del OCR (§Ronda 6): imágenes grandes sin texto real encima.

No dependen del binario `tesseract` (no siempre está instalado en CI/dev):
la lógica de agrupar/filtrar palabras y de decidir cuándo OCR-ear una imagen
se prueba con `pytesseract` mockeado. Un test de humo real (`requires_tesseract`)
corre solo si el binario está disponible.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

# `pytesseract` es una dependencia OPCIONAL (`pip install -e ".[ocr]"`); si no
# está instalada, todo este archivo se salta en vez de fallar — igual que
# `ocr.available()` degrada con gracia cuando falta.
pytest.importorskip("pytesseract")

from doc2md.adapters.outbound.pdf import ocr as ocr_mod
from doc2md.adapters.outbound.pdf.extract import Block, _OcrBudget, _ocr_big_images
from doc2md.config import Config

requires_tesseract = pytest.mark.skipif(
    not ocr_mod.available(), reason="tesseract no está instalado en esta máquina"
)


# --------------------------------------------------------------------------- #
# ocr.available() — cachea el resultado del primer chequeo.
# --------------------------------------------------------------------------- #

def test_available_false_without_binary(monkeypatch):
    ocr_mod._checked_binary = None
    import pytesseract

    def boom():
        raise Exception("no tesseract")

    monkeypatch.setattr(pytesseract, "get_tesseract_version", boom)
    assert ocr_mod.available() is False
    ocr_mod._checked_binary = None  # no contaminar otros tests


def test_available_true_when_binary_responds(monkeypatch):
    ocr_mod._checked_binary = None
    import pytesseract

    monkeypatch.setattr(pytesseract, "get_tesseract_version", lambda: "5.4.0")
    assert ocr_mod.available() is True
    ocr_mod._checked_binary = None


# --------------------------------------------------------------------------- #
# ocr_image_region — agrupación por (block, par, line) y filtro de confianza.
# --------------------------------------------------------------------------- #

class _FakeCropped:
    original = object()


class _FakeImage:
    def to_image(self, resolution):
        return _FakeCropped()


class _FakePage:
    def crop(self, bbox):
        return _FakeImage()


def _tesseract_data(rows):
    """rows: lista de (text, conf, block, par, line)."""
    data = {"text": [], "conf": [], "block_num": [], "par_num": [], "line_num": []}
    for text, conf, block, par, line in rows:
        data["text"].append(text)
        data["conf"].append(conf)
        data["block_num"].append(block)
        data["par_num"].append(par)
        data["line_num"].append(line)
    return data


def test_ocr_image_region_groups_words_into_lines(monkeypatch):
    import pytesseract

    rows = [
        ("Fase", 92, 1, 1, 1), ("0", 90, 1, 1, 1), ("-", 85, 1, 1, 1),
        ("Inscripciones", 91, 1, 1, 1),
        ("Fase", 93, 1, 1, 2), ("I", 88, 1, 1, 2),
    ]
    monkeypatch.setattr(
        pytesseract, "image_to_data", lambda *a, **k: _tesseract_data(rows)
    )
    lines = ocr_mod.ocr_image_region(_FakePage(), (0, 0, 100, 100), Config())
    assert lines == ["Fase 0 - Inscripciones", "Fase I"]


def test_ocr_image_region_drops_low_confidence_noise(monkeypatch):
    import pytesseract

    rows = [
        ("Fase", 92, 1, 1, 1),
        ("§¶#", 5, 1, 1, 1),   # ruido de una foto: confianza muy baja
        ("Real", 60, 1, 1, 1),
    ]
    monkeypatch.setattr(
        pytesseract, "image_to_data", lambda *a, **k: _tesseract_data(rows)
    )
    lines = ocr_mod.ocr_image_region(_FakePage(), (0, 0, 100, 100), Config())
    assert lines == ["Fase Real"]


def test_ocr_image_region_empty_when_nothing_confident(monkeypatch):
    import pytesseract

    rows = [("blob", 3, 1, 1, 1)]
    monkeypatch.setattr(
        pytesseract, "image_to_data", lambda *a, **k: _tesseract_data(rows)
    )
    assert ocr_mod.ocr_image_region(_FakePage(), (0, 0, 100, 100), Config()) == []


# --------------------------------------------------------------------------- #
# extract._ocr_big_images — integración con Page/Config.
# --------------------------------------------------------------------------- #

@dataclass
class _Img:
    x0: float
    top: float
    x1: float
    bottom: float

    def __getitem__(self, key):
        return getattr(self, key)


class _Page:
    def __init__(self, images, width=800, height=1000, page_number=1):
        self.images = images
        self.width = width
        self.height = height
        self.page_number = page_number

    def crop(self, bbox):
        return self


def test_big_image_skipped_when_small():
    """Una imagen pequeña (logo) no dispara nada, con o sin OCR."""
    page = _Page(images=[_Img(0, 0, 50, 50)])  # 2500 / 800000 << ratio mínimo
    blocks = _ocr_big_images(page, kept_words=[], config=Config(), log=lambda s: None)
    assert blocks == []


def test_big_image_skipped_when_real_text_overlaps(monkeypatch):
    """Una imagen grande con texto real ENCIMA no se OCR-ea (evita duplicar)."""
    monkeypatch.setattr(ocr_mod, "available", lambda: True)
    page = _Page(images=[_Img(0, 0, 800, 1000)])
    kept = [
        {"x0": 10 + i, "x1": 20 + i, "top": 10, "bottom": 20}
        for i in range(10)
    ]
    blocks = _ocr_big_images(page, kept_words=kept, config=Config(), log=lambda s: None)
    assert blocks == []


def test_big_image_inserts_visible_placeholder_when_ocr_unavailable():
    """Sin Tesseract, una imagen que domina la página (>=50%) SÍ avisa."""
    monkeypatch_log: list[str] = []
    page = _Page(images=[_Img(0, 0, 800, 1000)])  # 100% del área
    assert ocr_mod.available() is False  # entorno de test sin tesseract
    blocks = _ocr_big_images(
        page, kept_words=[], config=Config(), log=monkeypatch_log.append
    )
    assert len(blocks) == 1
    text = blocks[0].lines[0].text
    assert "página 1" in text and "Tesseract" in text
    assert any("sin OCR" in line for line in monkeypatch_log)


def test_big_image_no_placeholder_noise_for_decorative_photo_below_threshold():
    """Sin Tesseract, una imagen mediana (foto decorativa) NO genera aviso."""
    page = _Page(images=[_Img(0, 0, 400, 400)])  # 160000/800000 = 0.2 < placeholder 0.5
    assert ocr_mod.available() is False
    blocks = _ocr_big_images(page, kept_words=[], config=Config(), log=lambda s: None)
    assert blocks == []


def test_big_image_recovers_text_when_ocr_available(monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: True)
    monkeypatch.setattr(
        ocr_mod, "ocr_image_region", lambda page, bbox, config: ["Fase I", "Fase II"]
    )
    page = _Page(images=[_Img(0, 0, 800, 1000)])
    blocks = _ocr_big_images(page, kept_words=[], config=Config(), log=lambda s: None)
    assert len(blocks) == 1
    assert [l.text for l in blocks[0].lines] == ["Fase I", "Fase II"]


def test_big_image_ocr_failure_is_swallowed(monkeypatch):
    """Un fallo de OCR en una imagen (timeout, corrupta) no rompe el lote."""
    monkeypatch.setattr(ocr_mod, "available", lambda: True)

    def boom(page, bbox, config):
        raise RuntimeError("timeout")

    monkeypatch.setattr(ocr_mod, "ocr_image_region", boom)
    page = _Page(images=[_Img(0, 0, 800, 1000)])
    logged: list[str] = []
    blocks = _ocr_big_images(page, kept_words=[], config=Config(), log=logged.append)
    assert blocks == []
    assert any("falló" in line for line in logged)


def test_ocr_max_images_caps_processing(monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: True)
    monkeypatch.setattr(ocr_mod, "ocr_image_region", lambda page, bbox, config: ["x"])
    page = _Page(images=[_Img(0, i * 200, 800, i * 200 + 190) for i in range(5)])
    cfg = Config(ocr_max_images=2)
    blocks = _ocr_big_images(page, kept_words=[], config=cfg, log=lambda s: None)
    assert len(blocks) == 2


def test_ocr_budget_exhausted_stops_spending_more_time(monkeypatch):
    """Agotado el presupuesto de tiempo (medido, no estimado), las imágenes
    restantes se tratan como "sin OCR": aviso si dominan la página, sin ruido
    si no — pero NUNCA se sigue llamando a Tesseract (lo que causó 502 en
    Render con un PDF real de varias imágenes grandes)."""
    monkeypatch.setattr(ocr_mod, "available", lambda: True)
    calls: list[str] = []

    def fake_ocr(page, bbox, config):
        calls.append("called")
        return ["texto reconocido"]

    monkeypatch.setattr(ocr_mod, "ocr_image_region", fake_ocr)
    # Dos imágenes que dominan la página (>=50%, para que SÍ avise al agotarse
    # el presupuesto), una arriba y otra abajo.
    page = _Page(images=[_Img(0, 0, 800, 500), _Img(0, 500, 800, 1000)])
    budget = _OcrBudget(remaining=0.0)  # ya agotado desde el inicio
    blocks = _ocr_big_images(
        page, kept_words=[], config=Config(), log=lambda s: None, budget=budget
    )
    assert calls == []  # nunca se llamó a Tesseract: se respetó el presupuesto
    assert len(blocks) == 2
    assert all("presupuesto de tiempo de OCR agotado" in b.lines[0].text for b in blocks)


def test_ocr_budget_decrements_by_real_elapsed_time(monkeypatch):
    monkeypatch.setattr(ocr_mod, "available", lambda: True)

    def slow_ocr(page, bbox, config):
        import time
        time.sleep(0.05)
        return ["x"]

    monkeypatch.setattr(ocr_mod, "ocr_image_region", slow_ocr)
    page = _Page(images=[_Img(0, 0, 800, 1000)])
    budget = _OcrBudget(remaining=1.0)
    _ocr_big_images(page, kept_words=[], config=Config(), log=lambda s: None, budget=budget)
    assert budget.remaining < 1.0  # se descontó el tiempo real gastado


# --------------------------------------------------------------------------- #
# Humo real (opcional): solo corre si hay tesseract instalado.
# --------------------------------------------------------------------------- #

@requires_tesseract
def test_real_tesseract_smoke():
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (400, 100), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 30), "HOLA MUNDO", fill="black")

    class _Cropped:
        original = img

    class _FakeImg:
        def to_image(self, resolution):
            return _Cropped()

    class _FakePageReal:
        def crop(self, bbox):
            return _FakeImg()

    lines = ocr_mod.ocr_image_region(_FakePageReal(), (0, 0, 400, 100), Config())
    assert any("HOLA" in l.upper() for l in lines)
