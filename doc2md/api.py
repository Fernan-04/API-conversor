"""Fachada pública del motor de conversión (§Fase1).

`convert()` es el único punto de entrada que usan el CLI, la API HTTP y los
tests. Detecta el formato por la extensión, elige el lector adecuado (router),
obtiene la estructura neutral `Document` y la renderiza a Markdown.

Acepta una ruta (`str`/`Path`) o bytes en memoria (para la API stateless, §8.3);
en el caso de bytes hace falta `filename` para deducir la extensión.
"""

from __future__ import annotations

from pathlib import Path

from doc2md.adapters.outbound import router
from doc2md.config import Config
from doc2md.domain.markdown_renderer import render_markdown


def _read_source(source, filename: str | None) -> tuple[bytes, str]:
    if isinstance(source, (bytes, bytearray)):
        if not filename:
            raise ValueError(
                "convert() con bytes requiere `filename` para deducir el formato."
            )
        return bytes(source), filename
    path = Path(source)
    return path.read_bytes(), filename or path.name


def convert(source, config: Config | None = None, *, filename: str | None = None) -> str:
    """Convierte un documento a Markdown.

    `source`: ruta (`str`/`Path`) o `bytes` del archivo.
    `filename`: obligatorio si `source` son bytes (para deducir la extensión).
    """
    config = config or Config()
    data, name = _read_source(source, filename)
    reader = router.reader_for(name)
    document = reader.read(data, name, config)
    return render_markdown(document, config)
