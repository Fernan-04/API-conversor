# MEMORY — estado del proyecto doc2md (handoff)

> Documento para retomar el trabajo si la sesión se interrumpe. Última
> actualización: 2026-08-21.

## Qué es

`doc2md` = escalamiento de `pdf2md` a un conversor **multi-formato** (PDF, DOCX,
PPTX, XLSX) → Markdown, con **arquitectura hexagonal** y una **API HTTP**. El plan
completo (6 fases) está en `docs/PLAN_escalamiento_doc2md.md`; el spec original del
motor PDF, en `docs/SPEC_pdf2md.md`.

## Decisiones tomadas (no volver a preguntar)

- Paquete renombrado `pdf2md` → **`doc2md`** (el CLI sigue funcionando).
- Privacidad **Opción A**: la API procesa en el servidor y **no persiste nada**
  (§2.1). Sin cuentas ni login (§6.1).
- Límite de tamaño de archivo en la API: **25 MB** (`config.max_file_size_bytes`).
- Tope de filas por hoja XLSX: **1000** (`config.xlsx_max_rows`).

## Estado por fase

| Fase | Descripción | Estado |
|---|---|---|
| 1 | Motor multi-formato + arquitectura hexagonal + errores tipificados + logging JSON | ✅ Hecho |
| 2 | API FastAPI (`POST /convert`, cero persistencia) + Dockerfile | ✅ Hecho |
| 3 | Deploy de la API (Railway o Render) | ⬜ Pendiente (requiere tus cuentas) |
| 4 | Frontend Next.js + TypeScript | ⬜ Pendiente |
| 5 | Deploy del frontend (Vercel) | ⬜ Pendiente (requiere tus cuentas) |
| 6 | Pulido (aviso de privacidad, timeouts, vista previa) | ⬜ Parcial (la API ya hace .zip múltiple) |

## Cómo correr todo

```bash
# instalar (motor + API + tests)
.venv\Scripts\python -m pip install -e ".[api,dev]"

# tests  (27 pasan; 3 se saltan si faltan los PDFs de calibración)
.venv\Scripts\python -m pytest -q

# CLI multi-formato
.venv\Scripts\python -m doc2md pdfs/ -o markdown/ --verbose

# API local
.venv\Scripts\uvicorn doc2md.adapters.inbound.http:app --port 8000
curl -F "files=@pdfs/verbos-objetivos.pdf" http://localhost:8000/convert -o out.md
```

## Mapa del código (arquitectura hexagonal)

- `doc2md/domain/` — **puro**, sin librerías de I/O. `models.py` (Document /
  Heading / Paragraph / ListBlock / Table), `ports.py` (DocumentReader,
  MarkdownRenderer), `errors.py` (jerarquía tipificada), `markdown_renderer.py`.
- `doc2md/adapters/inbound/` — `cli.py` (CLI por lotes) y `http.py` (FastAPI).
- `doc2md/adapters/outbound/` — `router.py` (extensión → lector) + un lector por
  formato: `pdf/` (pipeline heurístico completo), `docx_reader.py`,
  `pptx_reader.py`, `xlsx_reader.py`.
- `doc2md/api.py` — fachada `convert(source, config, filename=...)`, único punto
  que usan CLI, API y tests.
- `doc2md/config.py` — todos los umbrales. `logging_json.py` — log de 1 línea JSON.

## Puntos delicados / trampas

- **No recalibrar los umbrales de tablas en `config.py`** sin volver a validar
  contra los PDFs de calibración. El discriminador fiable rúbrica-vs-maquetación es
  el nº de columnas (`table_min_cols`), no el fill.
- **Guardián de regresión**: `convert('pdfs/verbos-objetivos.pdf')` debe ser
  idéntico a `markdown/verbos-objetivos.md` (`tests/test_pdf.py::
  test_output_matches_baseline`). El refactor movió el render al dominio SIN
  cambiar la salida; si cambia, algo se rompió.
- **PDFs de calibración ausentes**: `rubrica1.pdf` y `APF1_INDICACION.pdf` ya no
  están en `pdfs/` (solo `verbos-objetivos.pdf`). Los tests que los usan se saltan
  con `@requires_rubrica` / `@requires_apf1`. Si los recuperas, colócalos en
  `pdfs/` y esos 3 tests correrán solos.
- El dominio no debe importar `pdfplumber`/`docx`/`pptx`/`openpyxl`/`fastapi`
  (regla §8.1). Las libs de Office se importan de forma perezosa dentro de cada
  `read()`.

## Siguientes pasos (para retomar)

1. **Fase 3 — deploy API**: crear cuenta en Railway o Render, conectar el repo,
   desplegar con el `Dockerfile` de la raíz. Obtener la URL pública HTTPS y
   probarla con `curl` (igual que en local). Considerar restringir CORS
   (`allow_origins`) al dominio del frontend.
2. **Fase 4 — frontend**: proyecto Next.js + TypeScript (App Router), pantalla
   única mobile-first con drag & drop, botón Convertir (`POST /convert`) y
   Descargar. Variable de entorno con la URL de la API.
3. **Fase 5 — deploy frontend**: repo en GitHub + Vercel (deploy automático).
4. **Fase 6 — pulido**: aviso de privacidad visible, manejo de timeouts / archivos
   grandes, vista previa opcional del Markdown.
