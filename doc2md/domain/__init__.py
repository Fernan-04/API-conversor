"""Dominio de doc2md: puro, sin I/O ni librerías de parseo.

Contiene la estructura intermedia neutral (`models`), los puertos que los
adaptadores implementan (`ports`), la jerarquía de errores tipificados (`errors`)
y el renderer a Markdown (`markdown_renderer`). Regla de dependencia: este
paquete NO importa `pdfplumber`, `python-docx`, `python-pptx`, `openpyxl` ni
`FastAPI`.
"""
