"""Adaptador de lectura PDF.

Envuelve el pipeline heurístico basado en `pdfplumber` (coordenadas, tamaños de
fuente, filtro de tablas de maquetación). Toda esa lógica es infraestructura
—específica de PDF— y por eso vive aquí, no en el dominio. `reader.py` la
orquesta y traduce el resultado a la estructura neutral `Document`.
"""
