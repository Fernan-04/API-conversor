"""API HTTP de conversión (FastAPI) — adaptador de entrada (Fase 2).

Contrato de cero persistencia (§2.1, §8.3):
  - los archivos se procesan en memoria (`io.BytesIO`), nunca en disco persistente;
  - el Markdown se devuelve en el cuerpo de la respuesta, no se guarda en ningún
    bucket/BD/carpeta;
  - los buffers se liberan siempre (`try/finally`), haya éxito o error;
  - no hay estado global ni caché entre peticiones;
  - los logs (§8.4) solo llevan metadatos, nunca el contenido.

`POST /convert` acepta uno o varios archivos: uno devuelve `.md`; varios, un
`.zip` armado en memoria.
"""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from doc2md import __version__, api
from doc2md.config import Config
from doc2md.domain.errors import ConversionError, FileTooLargeError
from doc2md.logging_json import log_conversion

app = FastAPI(
    title="doc2md API",
    version=__version__,
    description="Convierte PDF/DOCX/PPTX/XLSX a Markdown. No almacena nada.",
)

# El frontend (Vercel) vive en otro origen; se permite CORS. Se puede restringir
# por variable de entorno al desplegar.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


def _error_response(exc: ConversionError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.http_status,
        content={"code": exc.code, "message": exc.user_message, "layer": exc.layer},
    )


def _convert_upload(data: bytes, filename: str, config: Config) -> str:
    """Convierte un archivo en memoria, con logging de metadatos (§8.4)."""
    fmt = Path(filename).suffix.lstrip(".").lower()
    start = time.perf_counter()
    if len(data) > config.max_file_size_bytes:
        log_conversion(
            format_origen=fmt, tamano_bytes=len(data),
            duracion_ms=0, resultado="error",
            codigo_error=FileTooLargeError.code, capa="infrastructure",
        )
        raise FileTooLargeError(
            f"El archivo excede el límite de "
            f"{config.max_file_size_bytes // (1024 * 1024)} MB."
        )
    try:
        markdown = api.convert(data, config, filename=filename)
    except ConversionError as exc:
        log_conversion(
            format_origen=fmt, tamano_bytes=len(data),
            duracion_ms=int((time.perf_counter() - start) * 1000),
            resultado="error", codigo_error=exc.code, capa=exc.layer,
        )
        raise
    log_conversion(
        format_origen=fmt, tamano_bytes=len(data),
        duracion_ms=int((time.perf_counter() - start) * 1000),
        resultado="ok",
    )
    return markdown


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "version": __version__}


@app.post("/convert")
async def convert_endpoint(files: list[UploadFile] = File(...)):
    """Convierte uno o varios documentos a Markdown.

    - 1 archivo  -> respuesta `text/markdown` (`<nombre>.md`).
    - varios     -> respuesta `application/zip` con un `.md` por archivo.
    """
    config = Config()

    if not files:
        return JSONResponse(
            status_code=400,
            content={"code": "INFRA_ERROR", "message": "No se envió ningún archivo.",
                     "layer": "infrastructure"},
        )

    # --- Un solo archivo: devolver el .md en el cuerpo. --------------------- #
    if len(files) == 1:
        upload = files[0]
        try:
            data = await upload.read()
            markdown = _convert_upload(data, upload.filename or "archivo", config)
        except ConversionError as exc:
            return _error_response(exc)
        finally:
            await upload.close()
        stem = Path(upload.filename or "archivo").stem
        return Response(
            content=markdown,
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{stem}.md"'},
        )

    # --- Varios archivos: empaquetar en un .zip en memoria. ---------------- #
    buffer = io.BytesIO()
    try:
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for upload in files:
                try:
                    data = await upload.read()
                    markdown = _convert_upload(
                        data, upload.filename or "archivo", config
                    )
                except ConversionError as exc:
                    return _error_response(exc)
                finally:
                    await upload.close()
                stem = Path(upload.filename or "archivo").stem
                zf.writestr(f"{stem}.md", markdown)
        zip_bytes = buffer.getvalue()
    finally:
        buffer.close()

    return Response(
        content=zip_bytes,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="markdown.zip"'},
    )
