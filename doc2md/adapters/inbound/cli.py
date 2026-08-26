"""CLI y orquestación por lotes (§7, §8) — adaptador de entrada.

Mantiene la interfaz de argumentos completa de pdf2md y ahora acepta los cuatro
formatos (PDF/DOCX/PPTX/XLSX) a través de la fachada `doc2md.convert`. El manejo
de errores por lote (un archivo que falla nunca aborta el resto) se conserva, y
cada conversión emite una línea de log JSON (§8.4).
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from doc2md import __version__, api
from doc2md.adapters.outbound import router
from doc2md.adapters.outbound.pdf import ocr
from doc2md.config import Config
from doc2md.domain.errors import ConversionError
from doc2md.logging_json import log_conversion

# Códigos de salida (§7).
EXIT_OK = 0
EXIT_INPUT_ERROR = 1
EXIT_ALL_FAILED = 2


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="doc2md",
        description="Convierte PDF/DOCX/PPTX/XLSX a Markdown, en local (sin red).",
    )
    p.add_argument("entrada", help="Archivo (.pdf/.docx/.pptx/.xlsx) o carpeta con documentos")
    p.add_argument("-o", "--output", help="Archivo .md de salida, o carpeta si la entrada es carpeta")
    p.add_argument("-r", "--recursive", action="store_true", help="Buscar documentos en subcarpetas")
    p.add_argument("--overwrite", action="store_true", help="Sobrescribir el .md si ya existe")
    p.add_argument("--no-tables", action="store_true", help="No extraer tablas")
    p.add_argument("--no-headings", action="store_true", help="No inferir títulos por tamaño de fuente")
    p.add_argument("--no-bold", action="store_true", help="No marcar negritas")
    p.add_argument("--keep-repeated", action="store_true", help="Conservar cabeceras y pies repetidos")
    p.add_argument("--no-join", action="store_true", help="Una línea del PDF = una línea del Markdown")
    p.add_argument("--single-column", action="store_true", help="Forzar lectura de una sola columna")
    p.add_argument("--no-polish", action="store_true",
                   help="Desactivar el pulido de diseño (Title Case de títulos, "
                        "jerarquía del bloque de título, clave-valor->tabla, "
                        "temario->viñetas, autolink de URLs, puntajes **(N)**)")
    p.add_argument("--page-markers", action="store_true", help="Insertar <!-- pagina N -->")
    p.add_argument("--page-break", action="store_true", help="Insertar --- entre páginas")
    p.add_argument("--ocr", action="store_true", help="OCR en páginas sin capa de texto (solo PDF)")
    p.add_argument("--ocr-lang", default="spa", help="Idioma de OCR (default: spa)")
    p.add_argument("--stdout", action="store_true", help="Imprimir en consola en vez de escribir archivo")
    p.add_argument("-v", "--verbose", action="store_true", help="Log de decisiones")
    p.add_argument("--version", action="version", version=f"doc2md {__version__}")
    return p


def config_from_args(args: argparse.Namespace) -> Config:
    polish = not args.no_polish
    return Config(
        extract_tables=not args.no_tables,
        detect_headings=not args.no_headings,
        mark_bold=not args.no_bold,
        remove_repeated=not args.keep_repeated,
        join_lines=not args.no_join,
        single_column=args.single_column,
        page_markers=args.page_markers,
        page_break=args.page_break,
        overwrite=args.overwrite,
        ocr=args.ocr,
        ocr_lang=args.ocr_lang,
        verbose=args.verbose,
        # Pulido de "diseño IA" (§A-D): un solo interruptor desde el CLI.
        titlecase_headings=polish,
        heading_strip_trailing_colon=polish,
        heading_demote_title_block=polish,
        kv_to_table=polish,
        autolink_urls=polish,
        temario_to_bullets=polish,
        score_bold_parens=polish,
        merge_orphan_score_row=polish,
    )


def find_documents(entrada: Path, recursive: bool) -> list[Path]:
    """Devuelve los documentos soportados dentro de `entrada`."""
    exts = set(router.supported_extensions())
    if entrada.is_file():
        return [entrada]
    globber = entrada.rglob if recursive else entrada.glob
    found = [p for p in globber("*") if p.is_file() and p.suffix.lower() in exts]
    return sorted(found)


def output_path_for(doc: Path, entrada: Path, output: str | None) -> Path | None:
    """Calcula la ruta .md de salida. None => stdout (lo decide el caller)."""
    if entrada.is_file():
        if output:
            out = Path(output)
            # Si -o apunta a una carpeta existente, escribir dentro con el nombre del doc.
            if out.is_dir():
                return out / (doc.stem + ".md")
            return out
        return doc.with_suffix(".md")
    # Entrada = carpeta.
    if output:
        return Path(output) / (doc.stem + ".md")
    return doc.with_suffix(".md")


def convert_one(path: Path, config: Config) -> str:
    """Convierte un documento a Markdown. Puede lanzar excepción (la captura el lote).

    Emite una línea de log JSON con metadatos (§8.4), nunca con contenido.
    """
    path = Path(path)
    fmt = path.suffix.lstrip(".").lower()
    size = path.stat().st_size if path.exists() else 0
    start = time.perf_counter()
    try:
        markdown = api.convert(path, config)
    except ConversionError as exc:
        log_conversion(
            format_origen=fmt, tamano_bytes=size,
            duracion_ms=int((time.perf_counter() - start) * 1000),
            resultado="error", codigo_error=exc.code, capa=exc.layer,
        )
        raise
    log_conversion(
        format_origen=fmt, tamano_bytes=size,
        duracion_ms=int((time.perf_counter() - start) * 1000),
        resultado="ok",
    )
    return markdown


def main(argv: list[str] | None = None) -> int:
    # Forzar UTF-8 en la salida para no crashear en Windows (cp1252) con
    # caracteres no-latin1. Imprescindible por los documentos con glifos raros.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass

    args = build_parser().parse_args(argv)
    config = config_from_args(args)

    if config.ocr and not ocr.available():
        print(f"[error] --ocr pedido pero falta pytesseract.\n{ocr.INSTALL_HINT}",
              file=sys.stderr)
        config.ocr = False

    entrada = Path(args.entrada)
    if not entrada.exists():
        print(f"[error] no existe: {entrada}", file=sys.stderr)
        return EXIT_INPUT_ERROR

    docs = find_documents(entrada, args.recursive)
    if not docs:
        print(f"[error] no se encontraron documentos soportados en: {entrada}",
              file=sys.stderr)
        return EXIT_INPUT_ERROR

    ok = 0
    failed = 0
    for doc in docs:
        try:
            markdown = convert_one(doc, config)
        except ConversionError as exc:  # un fallo nunca aborta el lote (§8)
            failed += 1
            print(f"[error] {doc.name}: {exc.user_message}", file=sys.stderr)
            continue
        except Exception as exc:  # noqa: BLE001 — cualquier otro fallo tampoco aborta
            failed += 1
            print(f"[error] {doc.name}: {exc}", file=sys.stderr)
            continue

        if args.stdout:
            sys.stdout.write(markdown)
            ok += 1
            continue

        out = output_path_for(doc, entrada, args.output)
        assert out is not None
        if out.exists() and not config.overwrite:
            print(f"[skip] {out.name} ya existe (usa --overwrite)", file=sys.stderr)
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(markdown, encoding="utf-8")
        print(f"[write] {out}", file=sys.stderr)
        ok += 1

    if ok == 0 and failed > 0:
        return EXIT_ALL_FAILED
    return EXIT_OK
