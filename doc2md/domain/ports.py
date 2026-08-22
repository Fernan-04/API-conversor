"""Puertos: las interfaces que conectan el dominio con los adaptadores (§8.1).

  - `DocumentReader` (entrada): bytes de un archivo -> `Document` neutral.
  - `MarkdownRenderer` (salida): `Document` -> texto Markdown.

Se definen como `typing.Protocol` (tipado estructural): un adaptador cumple el
puerto por tener el método con la firma correcta, sin heredar nada. El dominio
depende solo de estas firmas, nunca de una implementación concreta.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from doc2md.config import Config
from doc2md.domain.models import Document


@runtime_checkable
class DocumentReader(Protocol):
    """Adaptador de lectura: convierte los bytes de un formato en un `Document`.

    Recibe `data` (los bytes crudos, sin tocar disco), `filename` (para reportar
    errores y, si hiciera falta, desambiguar) y la `config`. Debe lanzar las
    excepciones de `doc2md.domain.errors` ante archivos corruptos, protegidos,
    etc. — nunca excepciones crudas de la librería de parseo.
    """

    def read(self, data: bytes, filename: str, config: Config) -> Document: ...


@runtime_checkable
class MarkdownRenderer(Protocol):
    """Adaptador de salida: convierte un `Document` en texto Markdown."""

    def render(self, document: Document, config: Config) -> str: ...
