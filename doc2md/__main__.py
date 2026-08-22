"""Punto de entrada: `python -m doc2md`."""

from __future__ import annotations

import sys

from doc2md.adapters.inbound.cli import main

if __name__ == "__main__":
    sys.exit(main())
