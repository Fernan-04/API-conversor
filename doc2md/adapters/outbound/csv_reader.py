"""Lector CSV / TSV: implementa el puerto `DocumentReader`.

Usa solo el módulo `csv` de la stdlib (cero dependencias pesadas). Produce una
única sección con una `Table` (la primera fila se trata como cabecera al
renderizar). Reutiliza los topes `config.xlsx_max_rows` / `config.xlsx_max_cols`
para acotar archivos enormes.

  - `.tsv` -> delimitador tabulador.
  - `.csv` -> se intenta autodetectar el delimitador (`,`, `;` o tab) con
              `csv.Sniffer`; si no se puede, se usa la coma.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path

from doc2md.config import Config
from doc2md.domain.errors import CorruptFileError
from doc2md.domain.models import Document, Element, Paragraph, Table
from doc2md.adapters.outbound.text_reader import decode_text
from doc2md.text_utils import clean_text


def _detect_delimiter(sample: str, extension: str) -> str:
    if extension == ".tsv":
        return "\t"
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t").delimiter
    except csv.Error:
        return ","


class CsvReader:
    """Adaptador de lectura CSV/TSV (puerto `DocumentReader`)."""

    def read(self, data: bytes, filename: str, config: Config) -> Document:
        try:
            text = decode_text(data).replace("\r\n", "\n").replace("\r", "\n")
            ext = Path(filename).suffix.lower()
            delimiter = _detect_delimiter(text[:4096], ext)
            reader = csv.reader(io.StringIO(text), delimiter=delimiter)

            rows: list[list[str]] = []
            truncated_cols = False
            for i, raw_row in enumerate(reader):
                if i >= config.xlsx_max_rows:
                    break
                if len(raw_row) > config.xlsx_max_cols:
                    raw_row = raw_row[: config.xlsx_max_cols]
                    truncated_cols = True
                rows.append([clean_text(cell, config) for cell in raw_row])
        except Exception as exc:  # noqa: BLE001 — se traduce a error tipificado
            raise CorruptFileError(detail=str(exc)) from exc

        # Descarta filas totalmente vacías (líneas en blanco del CSV).
        rows = [r for r in rows if any(c.strip() for c in r)]
        if not rows:
            return Document(sections=[])

        elements: list[Element] = []
        if truncated_cols:
            elements.append(Paragraph(
                text=f"(Filas recortadas a {config.xlsx_max_cols} columnas.)"
            ))
        elements.append(Table(rows=rows))
        return Document(sections=[elements])
