"""Logging estructurado en JSON (§8.4).

Cada conversión (exitosa o fallida) genera UNA sola línea JSON en stderr, para
poder buscar y filtrar rápido en los logs de Railway/Render.

NUNCA se incluye el contenido del archivo ni del Markdown generado: solo
metadatos técnicos (formato, tamaño, duración, resultado, código de error y
capa). Coherente con la garantía de cero persistencia (§2.1).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone


def _timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log_conversion(
    *,
    format_origen: str,
    tamano_bytes: int,
    duracion_ms: int,
    resultado: str,                 # "ok" | "error"
    codigo_error: str | None = None,
    capa: str | None = None,        # "infrastructure" | "domain"
) -> None:
    """Emite una línea JSON con los metadatos de una conversión."""
    record: dict[str, object] = {
        "timestamp": _timestamp(),
        "format_origen": format_origen,
        "tamano_bytes": tamano_bytes,
        "duracion_ms": duracion_ms,
        "resultado": resultado,
        "codigo_error": codigo_error,
    }
    if capa is not None:
        record["capa"] = capa
    print(json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)
