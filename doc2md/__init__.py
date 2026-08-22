"""doc2md — conversor local multi-formato a Markdown.

Convierte PDF, DOCX, PPTX y XLSX a Markdown. Procesamiento 100% local en el CLI
(sin red, sin telemetría); la API HTTP procesa en memoria y no persiste nada.

Arquitectura hexagonal: el dominio (`doc2md.domain`) es puro y no conoce ni
`pdfplumber`, ni `python-docx`, ni `FastAPI`. Los adaptadores
(`doc2md.adapters`) dependen del dominio a través de sus puertos.
"""

from __future__ import annotations

from doc2md.api import convert

__version__ = "0.2.0"

__all__ = ["convert", "__version__"]
