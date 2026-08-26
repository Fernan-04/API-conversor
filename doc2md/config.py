"""Configuración central de doc2md.

Todos los umbrales de las heurísticas viven aquí, con nombre y comentario que
explica QUÉ problema resuelve cada uno. Regla del proyecto: cero números mágicos
dentro de la lógica (los adaptadores y el renderer leen de `Config`).

Los valores por defecto del filtro de tablas están calibrados contra los dos PDFs
reales de `pdfs/`: `rubrica1.pdf` (página HTML impresa, cuyas tablas de
maquetación hay que descartar) y `APF1_INDICACION.pdf` (Word con una rúbrica real
de 6 columnas que NO se debe descartar). **No recalibrar sin volver a validar
contra ambos** (ver `tests/test_pdf.py`).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Config:
    # ------------------------------------------------------------------ #
    # Salida / flags de comportamiento (§7)
    # ------------------------------------------------------------------ #
    extract_tables: bool = True        # --no-tables lo pone en False
    detect_headings: bool = True       # --no-headings
    mark_bold: bool = True             # --no-bold
    remove_repeated: bool = True       # --keep-repeated lo pone en False
    join_lines: bool = True            # --no-join
    single_column: bool = False        # --single-column
    page_markers: bool = False         # --page-markers  -> <!-- pagina N -->
    page_break: bool = False           # --page-break    -> --- entre páginas
    overwrite: bool = False            # --overwrite
    ocr: bool = False                  # --ocr
    ocr_lang: str = "spa"              # --ocr-lang
    verbose: bool = False              # -v/--verbose

    # ------------------------------------------------------------------ #
    # Formatos y límites (Fase 1/2)
    # ------------------------------------------------------------------ #
    # Extensiones soportadas por el router. El orden no importa.
    supported_extensions: tuple[str, ...] = (
        ".pdf", ".docx", ".pptx", ".xlsx",
        ".txt", ".md", ".csv", ".tsv",
    )
    # Límite de tamaño de archivo para la API (evita saturar la memoria del plan
    # gratuito de Railway/Render). 25 MB por decisión de proyecto.
    max_file_size_bytes: int = 25 * 1024 * 1024
    # Tope de filas por hoja de cálculo (hojas enormes -> tabla Markdown gigante).
    # Lo reutiliza también el lector CSV/TSV.
    xlsx_max_rows: int = 1000
    # Tope de columnas por hoja. Las hojas usadas como maquetación visual (p. ej.
    # un diagrama de Gantt) tienen cientos de columnas de línea de tiempo que no
    # son datos tabulares; se recortan a este ancho con un aviso. Lo reutiliza el
    # lector CSV/TSV.
    xlsx_max_cols: int = 50

    # ------------------------------------------------------------------ #
    # Límites de recursos por petición (endurecimiento de seguridad)
    # ------------------------------------------------------------------ #
    # Nº máximo de archivos por petición a la API. Sin este tope, un cliente
    # podría enviar miles de archivos y hacer que el .zip se arme entero en
    # memoria (crítico en el plan gratis de Render, ~512 MB RAM).
    max_files: int = 20
    # Tamaño total acumulado (suma de todos los archivos de la petición).
    max_total_bytes: int = 60 * 1024 * 1024
    # Nº máximo de páginas de un PDF. Un PDF hostil con muchísimas páginas puede
    # saturar CPU/RAM; se rechaza antes de procesarlo entero.
    pdf_max_pages: int = 300

    # ------------------------------------------------------------------ #
    # Guarda anti "zip-bomb" para formatos OOXML (DOCX/PPTX/XLSX son zip+XML).
    # Se inspecciona el índice del zip (sin extraer) y se rechaza si excede
    # estos umbrales. Referencia: markitdown NO tiene ninguna de estas guardas.
    # ------------------------------------------------------------------ #
    zip_max_entries: int = 2000          # nº de ficheros dentro del zip
    zip_max_uncompressed_bytes: int = 400 * 1024 * 1024   # 400 MB descomprimidos
    zip_max_ratio: float = 120.0         # descomprimido / comprimido

    # ------------------------------------------------------------------ #
    # Títulos (§6.4)
    # ------------------------------------------------------------------ #
    # Una línea es candidata a título si su tamaño de fuente es al menos este
    # múltiplo del tamaño MODAL del documento (el cuerpo de texto).
    heading_size_ratio: float = 1.15
    # Máximo de niveles de título distintos que se mapean a #, ##, ###, ####.
    heading_max_levels: int = 4
    # Refuerzo: una línea corta (< N chars), en negrita y sin punto final puede
    # tratarse como título aunque el tamaño no suba.
    heading_short_line_max_len: int = 80
    # Pulido de títulos (acercar la salida al "diseño IA"):
    #  - titlecase_headings: un título EN MAYÚSCULAS ("FUNDAMENTACIÓN") se pasa a
    #    Title Case español ("Fundamentación"). Solo afecta a títulos all-caps.
    #  - heading_strip_trailing_colon: quita los dos puntos finales ("Logro a
    #    evaluar:" -> "Logro a evaluar").
    #  - heading_demote_title_block: el bloque de título del inicio del documento
    #    (varias líneas grandes seguidas, todas nivel 1) se degrada a #/##/###.
    titlecase_headings: bool = True
    heading_strip_trailing_colon: bool = True
    heading_demote_title_block: bool = True

    # ------------------------------------------------------------------ #
    # Bloque clave-valor -> tabla (§B). Un párrafo que en realidad son campos
    # numerados "N.N Etiqueta: valor" (sección "Datos Generales") se convierte en
    # una tabla de 2 columnas (Campo | Detalle). Se exige un mínimo de pares y que
    # cubran casi todo el párrafo, para no disparar sobre prosa normal.
    # ------------------------------------------------------------------ #
    kv_to_table: bool = True
    kv_min_pairs: int = 3
    kv_min_coverage: float = 0.75
    kv_label_max_len: int = 40

    # URLs sueltas -> enlace Markdown [etiqueta](url) (§D). La etiqueta es el host;
    # si el host menciona "biblioteca" se usa "Ver en biblioteca" (caso UTP).
    autolink_urls: bool = True

    # Temario corrido -> lista de viñetas (§B). SOLO se aplica al párrafo que sigue
    # a un título cuyo texto está en `bullet_trigger_headings` (no a prosa normal,
    # que también tiene límites de oración). Se parte por fin de oración (".+May")
    # y por marcadores de guion; se exige >= 2 ítems para convertir.
    temario_to_bullets: bool = True
    bullet_trigger_headings: tuple[str, ...] = ("temario",)

    # ------------------------------------------------------------------ #
    # Negritas (§2)
    # ------------------------------------------------------------------ #
    # Subcadenas en el fontname que indican negrita.
    bold_font_markers: tuple[str, ...] = ("Bold", "Black", "Heavy", "Semibold")
    # Fracción mínima de chars en negrita para marcar la línea entera.
    bold_line_ratio: float = 0.6

    # ------------------------------------------------------------------ #
    # Filtro de tablas (§5) — el corazón del proyecto.
    #
    # IMPORTANTE (medido sobre los PDFs reales): el discriminador limpio entre
    # rúbrica real y maquetación en estos documentos es el NÚMERO DE COLUMNAS
    # (rúbricas 5-6 vs basura 2-3), no el ratio de llenado. `table_report_fill`
    # NO se usa como descarte duro porque mataría la rúbrica real de
    # rubrica1 p2/p3 (fill 0.31-0.38); solo se reporta en --verbose.
    # `table_min_cols` es "agresivo" a 4 (optimizado para rúbricas UTP);
    # bajarlo a 2 lo vuelve general para documentos variados.
    # ------------------------------------------------------------------ #
    table_min_rows: int = 2            # menos filas -> no es tabla
    table_min_cols: int = 4            # menos columnas (tras tidy) -> se descarta
    # Si una sola celda concentra más de esta fracción del texto total de la
    # tabla, es un contenedor ("la página entera en una celda"), no una tabla.
    table_max_cell_concentration: float = 0.6
    # Descartar la tabla A cuyo bbox contiene al de otra tabla B (y B no a A):
    # A es la maquetación que envuelve a la tabla real.
    table_drop_containers: bool = True

    # Métricas SOLO informativas para --verbose (no deciden descarte):
    #   - fill: fracción de celdas con texto. fill<0.4 NO descarta (ver arriba).
    #   - altura de la tabla / altura de página: los wrappers de maquetación
    #     miden ~3x la página, pero contienen rúbrica real -> tampoco descarta.
    table_report_fill: float = 0.4     # umbral solo para colorear el log
    table_report_height_ratio: float = 1.3

    # Detector de listas de viñetas mal detectadas como tabla de 2 columnas
    # (APF1 p1/p2): una columna vacía en >= ratio de las filas y la otra
    # empezando por un marcador de viñeta -> emitir como lista, no como tabla.
    bullet_table_max_cols: int = 2
    bullet_empty_col_ratio: float = 0.7
    bullet_markers: tuple[str, ...] = ("●", "•", "‣", "▪", "◦", "-", "*", "·")

    # ------------------------------------------------------------------ #
    # Pulido de tablas — opción "tabla limpia".
    # ------------------------------------------------------------------ #
    polish_tables: bool = True
    # (1) Re-unir palabras partidas por salto de columna dentro de una celda
    #     ("Planteamient o" -> "Planteamiento"). Se unen un inicio de palabra
    #     "roto" (que NO termina en un final válido de palabra) y un fragmento
    #     suelto muy corto.
    cell_join_max_frag: int = 2          # longitud máx del fragmento suelto
    # Longitud mín del inicio de palabra para unir. Alto a propósito: las
    # palabras que se parten por ancho de columna son largas ("Planteamient"),
    # mientras que préstamos cortos completos ("chart", "gantt") acaban en
    # consonante "inválida" pero NO deben absorber la conjunción "y"/"o".
    cell_join_min_stem: int = 7
    # Finales de palabra "válidos" en español: si el inicio termina en uno de
    # estos, se considera palabra completa y NO se une (evita romper "algo o").
    cell_word_valid_endings: str = "aeiouáéíóúünrsldzxy"
    # (2) Fusionar filas huérfanas de puntajes: fila con las primeras N celdas
    #     vacías y el resto solo numérico -> se anexa a la fila anterior.
    merge_score_rows: bool = True
    score_row_empty_leading: int = 2
    # Formatear los puntajes fusionados como "**(N)**" (como el diseño IA) en vez
    # de un número suelto. Se aplica tanto a la fusión dentro de una tabla como a
    # la fila-huérfana de puntajes que cae al inicio de la página siguiente.
    score_bold_parens: bool = True
    # Recuperar la fila-huérfana de puntajes (solo números + vacías) que pdfplumber
    # deja al inicio de la página siguiente cuando parte una rúbrica: sus números
    # se anexan a las celdas de nivel de la última fila de la tabla anterior.
    merge_orphan_score_row: bool = True
    # (3) Descartar filas separadoras (solo guiones) que quedan dentro de una
    #     tabla por un corte de página.
    drop_separator_rows: bool = True
    # (4) Unir tablas partidas entre páginas: una tabla al inicio de la página
    #     siguiente con el mismo nº de columnas que la que cerró la anterior se
    #     trata como continuación. Si su 1ª fila repite la cabecera, se elimina.
    merge_tables_across_pages: bool = True
    merge_drop_repeated_header: bool = True
    # (5) Fusionar una continuación con MENOS columnas: cuando una tabla parte entre
    # páginas, las filas siguientes pueden perder las columnas "spanning" de la
    # izquierda (p. ej. la columna "Unidad" de un cronograma queda vacía y
    # pdfplumber no la emite). Si la continuación tiene entre 1 y N columnas menos,
    # se rellena por la izquierda con celdas vacías para alinear y unir.
    merge_pad_narrower_max: int = 2

    # ------------------------------------------------------------------ #
    # Cabeceras / pies repetidos (§6.2)
    # ------------------------------------------------------------------ #
    repeated_head_lines: int = 3       # nº de primeras líneas a considerar
    repeated_tail_lines: int = 3       # nº de últimas líneas a considerar
    repeated_page_ratio: float = 0.5   # aparece en >= 50% de páginas -> quitar
    repeated_min_pages: int = 3        # solo aplicar si el doc tiene >= 3 págs

    # ------------------------------------------------------------------ #
    # Fragmentos basura y espaciado (§6.3, §6.6)
    # ------------------------------------------------------------------ #
    # Líneas de <= N chars que no sean parte de una lista se descartan
    # (restos de URLs partidas: "h 4", "1/", ...).
    junk_line_max_len: int = 3
    # Insertar un espacio entre chars si el hueco supera max(gap_min, size*factor).
    space_gap_min: float = 1.2
    space_gap_size_factor: float = 0.28

    # ------------------------------------------------------------------ #
    # Unicode (§6.5) + glifos de iconos no cubiertos por el spec.
    # ------------------------------------------------------------------ #
    # Rango Private Use Area (SegoeFluentIcons y similares): iconos de UI que
    # aparecen al imprimir HTML; producen basura -> se eliminan.
    pua_start: int = 0xE000
    pua_end: int = 0xF8FF

    def is_bold_font(self, fontname: str) -> bool:
        """True si el fontname corresponde a una fuente en negrita."""
        return any(m in fontname for m in self.bold_font_markers)
