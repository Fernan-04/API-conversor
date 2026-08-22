"""Rate limiting en memoria para el adaptador HTTP.

Protege el cómputo del plan gratis de Render de que lo drenen: aunque alguien
saque la `X-API-Key` del navegador (es `NEXT_PUBLIC_*`, visible por diseño), este
limitador acota **cuántas** peticiones puede hacer.

Por qué en memoria: Render free corre UNA instancia con UN worker
(`WEB_CONCURRENCY=1`), así que un contador en el proceso es exacto y suficiente.
Se resetea si el servicio se duerme — irrelevante, las ventanas de abuso son de
segundos. Sin Redis ni dependencias externas.

Dos límites de ventana deslizante (marcas `time.monotonic()`):
  - por IP:  `RATE_LIMIT_PER_IP` peticiones por `RATE_LIMIT_WINDOW` s.
  - global:  `RATE_LIMIT_GLOBAL` peticiones por ventana (frena abuso distribuido /
             IPs falsificadas y acota el gasto total).

Los umbrales se leen de variables de entorno (mismo patrón que `API_KEY`), con
defaults generosos que no molestan a un usuario real pero cortan un bucle de abuso.
Se llama desde el handler `async` (hilo del event loop), así que el acceso a los
dicts es monohilo y no hace falta lock.
"""

from __future__ import annotations

import os
import time
from collections import deque


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


ENABLED = os.getenv("RATE_LIMIT_ENABLED", "1").strip().lower() not in ("0", "false", "no", "")
PER_IP = _int_env("RATE_LIMIT_PER_IP", 30)
WINDOW = _int_env("RATE_LIMIT_WINDOW", 60)
GLOBAL = _int_env("RATE_LIMIT_GLOBAL", 90)

# Estado: una cola de marcas de tiempo por IP + una cola global.
_hits: dict[str, deque[float]] = {}
_global: deque[float] = deque()


def _prune(marks: deque[float], now: float) -> None:
    cutoff = now - WINDOW
    while marks and marks[0] <= cutoff:
        marks.popleft()


def check(ip: str) -> float | None:
    """Registra una petición de `ip`. Devuelve `None` si se permite, o los
    segundos que faltan para reintentar si se superó algún límite (para
    `Retry-After`). Cuando devuelve un número, la petición NO se contabiliza.
    """
    if not ENABLED:
        return None

    now = time.monotonic()

    # Límite global.
    _prune(_global, now)
    if len(_global) >= GLOBAL:
        return max(0.0, WINDOW - (now - _global[0]))

    # Límite por IP.
    marks = _hits.get(ip)
    if marks is None:
        marks = _hits[ip] = deque()
    _prune(marks, now)
    if len(marks) >= PER_IP:
        return max(0.0, WINDOW - (now - marks[0]))

    # Poda perezosa de IPs sin marcas (evita crecimiento del dict).
    if len(_hits) > 4096:
        for k in [k for k, v in _hits.items() if not v]:
            _hits.pop(k, None)

    marks.append(now)
    _global.append(now)
    return None


def reset() -> None:
    """Limpia el estado. Uso principal: aislar los tests entre sí."""
    _hits.clear()
    _global.clear()
