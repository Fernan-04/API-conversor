# doc2md

Conversor local multi-formato a Markdown: **PDF, Word (.docx), PowerPoint
(.pptx) y Excel (.xlsx)**. Nació como `pdf2md` (rúbricas y consignas de
UTP+class) y se escaló a un motor con arquitectura hexagonal + una API HTTP.

> Documentación de uso personal (no para publicar). Ver `docs/`.

## Qué hace

- Convierte PDF/DOCX/PPTX/XLSX a Markdown detectando el formato por la extensión.
- **PDF**: extrae texto con orden razonable; detecta títulos por tamaño de fuente
  y negritas; extrae **tablas reales** y **descarta las tablas de maquetación** de
  páginas HTML impresas (§5); elimina cabeceras/pies repetidos; une párrafos con
  des-hifenización; filtra glifos de iconos (PUA) y normaliza Unicode.
- **DOCX**: títulos por estilo (`Heading N`), listas, negritas y tablas.
- **PPTX**: título de cada diapositiva como encabezado, viñetas, tablas y notas
  del orador como bloque aparte.
- **XLSX**: una sección por hoja (encabezado con el nombre) + tabla de sus filas
  (con tope configurable para hojas enormes).
- **TXT/MD/CSV/TSV** (solo stdlib): `.txt` → párrafos; `.md` → passthrough
  verbatim; `.csv`/`.tsv` → tabla.
- CLI por lotes (una carpeta completa, opcionalmente recursiva) que no aborta si
  un archivo falla, y una **API HTTP** (FastAPI) para el frontend web.
- **Endurecimiento de seguridad** (ver `docs/MEMORY.md`): guarda anti zip-bomb en
  OOXML, validación de firma por magic bytes, límites por petición (nº de archivos,
  total, páginas PDF), API key opcional, **rate limiting** (por IP + global, en
  memoria) y saneo de `Content-Disposition`.

## Arquitectura (hexagonal)

```
doc2md/
├── domain/        # PURO: models, ports, errors, markdown_renderer (sin libs de I/O)
├── adapters/
│   ├── inbound/   # cli.py (CLI) + http.py (FastAPI)
│   └── outbound/  # router + un lector por formato (pdf/, docx, pptx, xlsx)
├── api.py         # convert(source, config) -> str   (fachada única)
├── config.py      # todos los umbrales
├── text_utils.py  # normalización Unicode compartida
└── logging_json.py
```

El **dominio no importa** `pdfplumber`, `python-docx`, `python-pptx`, `openpyxl`
ni `FastAPI`. Agregar un formato nuevo es escribir un lector en `adapters/outbound`
y registrarlo en `router.py` — sin tocar el dominio ni el renderer.

## Privacidad

- **CLI: 100% local**, sin red ni telemetría (`test_no_network` lo verifica
  monkeypatcheando `socket.socket`).
- **API: cero persistencia.** Los archivos se procesan en memoria y el Markdown se
  devuelve en el cuerpo de la respuesta; nada se guarda en disco, BD ni buckets.
  Los logs solo llevan metadatos técnicos (tamaño, formato, duración), nunca el
  contenido.

## Instalación

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows  (Linux/macOS: source .venv/bin/activate)
pip install -e ".[api,dev]"     # motor + API + tests
```

OCR (opcional, solo PDF con `--ocr`): `pip install -e ".[ocr]"` + binario
`tesseract` (Windows: https://github.com/UB-Mannheim/tesseract/wiki).

## Uso del CLI

**Flujo recomendado: carpeta de documentos → carpeta `markdown/`** (los originales
no se tocan; `markdown/` es regenerable):

```bash
python -m doc2md pdfs/ -o markdown/
```

Otros modos:

```bash
python -m doc2md documentos/ -o markdown/ -r        # incluir subcarpetas
python -m doc2md informe.docx                        # escribe informe.md junto al archivo
python -m doc2md presentacion.pptx --stdout          # imprime en consola
python -m doc2md pdfs/ -o markdown/ --overwrite      # sobrescribir .md existentes
python -m doc2md pdfs/rubrica1.pdf --stdout -v       # ver decisiones de tablas
```

Por defecto NO se sobrescribe un `.md` existente. Flags completos en `--help`.

## Uso de la API

```bash
uvicorn doc2md.adapters.inbound.http:app --port 8000
```

- `GET /health` → `{"status": "ok"}`.
- `POST /convert` (`multipart/form-data`, campo `files`, uno o varios):
  - 1 archivo → cuerpo `text/markdown` (`<nombre>.md`).
  - varios → `application/zip` con un `.md` por archivo.

```bash
curl -F "files=@informe.docx" http://localhost:8000/convert -o informe.md
curl -F "files=@a.pdf" -F "files=@b.xlsx" http://localhost:8000/convert -o out.zip
```

Errores tipificados (§8.2): problemas del archivo/petición → HTTP 4xx
(`INFRA_UNSUPPORTED_FORMAT`, `INFRA_CORRUPT_FILE`, `INFRA_PASSWORD_PROTECTED`,
`INFRA_FILE_TOO_LARGE`, `INFRA_TOO_MANY_FILES`, `INFRA_UNAUTHORIZED`); bug interno
→ 500 (`DOMAIN_*`). El cuerpo trae `{code, message, layer}`.

### API key (opcional)

Si defines la env `API_KEY`, `POST /convert` exige la cabecera `X-API-Key` con ese
valor (`GET /health` sigue abierto). **Segura por defecto**: sin `API_KEY`, la auth
queda deshabilitada y todo funciona como siempre. Genera una clave con:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

```bash
# Con auth activa:
curl -F "files=@informe.docx" -H "X-API-Key: TU_CLAVE" http://localhost:8000/convert -o informe.md
```

La web (Vercel) debe enviar la misma clave vía `NEXT_PUBLIC_API_KEY`. Caveat: esa
env es visible en el bundle del navegador — frena bots y la URL "pelada", no es un
secreto fuerte.

### Variables de entorno

| Variable | Efecto |
|---|---|
| `PORT` | Puerto en el que escucha uvicorn. Lo inyecta la plataforma (Render); por defecto 8000. |
| `ALLOWED_ORIGINS` | Orígenes permitidos por CORS, separados por comas. Sin definir o `*` = cualquier origen (dev, avisa al arrancar). En producción, ponla a la URL de tu frontend (ej. `https://conversor-documentos-one.vercel.app`). |
| `API_KEY` | Si se define, `/convert` exige `X-API-Key` con ese valor. Sin definir = auth deshabilitada. |
| `RATE_LIMIT_ENABLED` / `RATE_LIMIT_PER_IP` / `RATE_LIMIT_GLOBAL` / `RATE_LIMIT_WINDOW` | Rate limiting en memoria de `/convert`. Defaults: on / 30 por IP / 90 global / 60 s. Protege el cómputo del plan gratis aunque se filtre la API key. `RATE_LIMIT_ENABLED=0` lo desactiva. |

### Docker

```bash
docker build -t doc2md-api .
docker run -p 8000:8000 doc2md-api
```

## Ajustar heurísticas (PDF)

Todos los umbrales viven en `doc2md/config.py`. Corre el CLI con `-v` para ver las
métricas de cada tabla y qué umbral la descartó, luego ajusta:

| Síntoma | Umbral a tocar en `config.py` |
|---|---|
| Descarta una tabla real angosta (2-3 col) | Bajar `table_min_cols` (p. ej. a 2) |
| Cuela un bloque de maquetación como tabla | Subir `table_min_cols` / revisar `table_max_cell_concentration` |
| Una lista de viñetas sale como tabla | Ajustar `bullet_empty_col_ratio` / `bullet_markers` |
| No detecta bien los títulos | Ajustar `heading_size_ratio` |
| No elimina una cabecera/pie repetido | Bajar `repeated_page_ratio` / subir `repeated_head_lines` |
| Une mal dos palabras cortas en una celda | Subir `cell_join_min_stem` |
| La API rechaza archivos legítimos por tamaño | Subir `max_file_size_bytes` (default 25 MB) |
| Hojas de Excel enormes se cortan | Subir `xlsx_max_rows` (default 1000) |

> `table_report_fill` (ratio de llenado) **no** decide descartes; el discriminador
> fiable en los PDFs reales es el número de columnas (ver comentario en `config.py`).
> **No recalibrar los umbrales de tablas sin volver a validar** contra los PDFs de
> calibración.

## Tests

```bash
python -m pytest -q
```

Guardián de regresión: la salida del PDF real `pdfs/verbos-objetivos.pdf` debe
seguir siendo idéntica a `markdown/verbos-objetivos.md`. Los tests de calibración
del filtro de tablas usan `rubrica1.pdf` y `APF1_INDICACION.pdf` (los dos casos
opuestos del SPEC) y se saltan si esos PDFs no están en `pdfs/`. Las fixtures de
DOCX/PPTX/XLSX se generan al vuelo (`tests/conftest.py`).

## Estado del escalamiento

Ver `docs/PLAN_escalamiento_doc2md.md` (plan completo) y `docs/MEMORY.md` (estado
y siguientes pasos). Hecho: **Fase 1** (motor multi-formato hexagonal) y **Fase 2**
(API + Dockerfile). Pendiente: Fase 3/5 (deploy en Railway/Render y Vercel) y
Fase 4 (frontend Next.js).
