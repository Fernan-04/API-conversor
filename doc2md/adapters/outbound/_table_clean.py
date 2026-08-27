"""Limpieza de tablas de hoja de cálculo (XLSX/CSV) antes de renderizar.

Funciones **puras** sobre `list[list[str]]` (celdas ya convertidas a texto). El
problema que resuelven: las hojas usadas como **maquetación visual** (un diagrama
de Gantt / cronograma) traen cientos de columnas de línea de tiempo casi vacías,
errores de fórmula (`#N/A`, `#REF!`…) y filas/columnas de solo ceros. Eso infla el
Markdown con ruido que no aporta y hace que una IA tarde en leerlo. Objetivo:
emitir **solo el contenido valioso** sin perder datos reales.

Regla de seguridad: la poda agresiva (ceros, densidad) SOLO se activa cuando la
hoja "parece maquetación" (muy ancha, `ncol >= config.xlsx_layout_min_cols`). Una
hoja de datos normal (pocas columnas) solo recibe normalización de errores + el
recorte de filas/columnas TOTALMENTE vacías de siempre.
"""

from __future__ import annotations

from doc2md.config import Config


def normalize_errors(rows: list[list[str]], config: Config) -> list[list[str]]:
    """Convierte las celdas con un error de fórmula de Excel en vacío.

    Un `#N/A`/`#REF!`/… es "sin dato", igual que una celda vacía; dejarlo como
    texto contamina la tabla y, peor, evita que la celda/columna se considere
    vacía al recortar.
    """
    errors = config.xlsx_error_values
    if not errors:
        return rows
    return [["" if c.strip() in errors else c for c in row] for row in rows]


def trim_empty(rows: list[list[str]]) -> list[list[str]]:
    """Descarta filas y columnas TOTALMENTE vacías (en cualquier posición) y
    rellena a rectángulo.

    Imprescindible para hojas de maquetación con huecos intercalados entre los
    datos. Mismo criterio que `tidy_rows` para las tablas de PDF.
    """
    rows = [r for r in rows if any(c for c in r)]        # fuera filas vacías
    if not rows:
        return []
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    keep = [i for i in range(ncol) if any(row[i] for row in rows)]  # cols con datos
    return [[row[i] for i in keep] for row in rows]


def _is_zeroish(cell: str) -> bool:
    """True si la celda es vacía o representa un cero (p. ej. `0`, `0.0`, `0,00`).

    Los ceros de fórmula que quedan de la maquetación de un Gantt no aportan; se
    tratan como vacío al decidir si una fila/columna es descartable.
    """
    s = cell.strip()
    if not s:
        return True
    try:
        return float(s.replace(",", ".")) == 0.0
    except ValueError:
        return False


def drop_zero_only(rows: list[list[str]]) -> list[list[str]]:
    """Descarta filas y columnas cuyo contenido es solo vacío o ceros.

    Una fila/columna con algún valor no-cero se conserva ENTERA (no se toca celda
    a celda). Pensado para la maquetación de un Gantt (bandas de ceros de fórmula).
    """
    rows = [r for r in rows if not all(_is_zeroish(c) for c in r)]
    if not rows:
        return []
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    keep = [i for i in range(ncol) if not all(_is_zeroish(row[i]) for row in rows)]
    return [[row[i] for i in keep] for row in rows]


def _meaningful(cell: str) -> bool:
    """True si la celda aporta dato real: no vacía y no un cero de fórmula."""
    return not _is_zeroish(cell)


def _column_is_counter(values: list[str]) -> bool:
    """True si la columna es un ÍNDICE/CONTADOR (enteros estrictamente crecientes).

    Las hojas auxiliares arrastran una columna "N°"/"Indice" con 1,2,3,… que se
    prolonga cientos de filas más allá de los datos reales (fuente de una lista
    desplegable). Ese contador no debe impedir recortar la cola muerta, así que se
    detecta para ignorarlo. Se tolera texto no numérico (p. ej. la cabecera "N°")
    mientras los enteros dominen y sean monótonos crecientes.
    """
    nums: list[int] = []
    nonempty = 0
    for v in values:
        s = v.strip()
        if not s:
            continue
        nonempty += 1
        try:
            f = float(s.replace(",", "."))
        except ValueError:
            continue
        if f == int(f):
            nums.append(int(f))
    if len(nums) < 3 or nonempty == 0 or len(nums) / nonempty < 0.6:
        return False
    return all(nums[i] < nums[i + 1] for i in range(len(nums) - 1))


def trim_dead_tail(rows: list[list[str]], config: Config) -> list[list[str]]:
    """Recorta la COLA MUERTA de la parte inferior de la hoja.

    Las hojas auxiliares de un Gantt tienen la tabla real arriba y, debajo,
    cientos de filas de andamiaje de fórmula: casi todo vacío o `#N/A` (ya
    normalizado a vacío) con, a lo sumo, un índice incremental o un cero suelto.
    Se recortan desde abajo las filas que no tienen NINGUNA celda con dato real en
    las columnas de contenido (se excluyen las columnas-contador), hasta topar con
    la última fila real de la tabla. Solo actúa en la cola: una tabla cuya última
    fila tiene datos no se toca. Salvaguarda: si TODAS las columnas son contador
    (una lista de enteros de una sola columna), no se ignora ninguna, para no
    borrar la lista entera.
    """
    if not rows:
        return rows
    ncol = max(len(r) for r in rows)

    def cell(r: list[str], i: int) -> str:
        return r[i] if i < len(r) else ""

    counters = {
        i for i in range(ncol)
        if _column_is_counter([cell(r, i) for r in rows])
    }
    content = [i for i in range(ncol) if i not in counters] or list(range(ncol))

    end = len(rows)
    while end > 1 and not any(_meaningful(cell(rows[end - 1], i)) for i in content):
        end -= 1
    return rows[:end]


def trim_layout_columns(rows: list[list[str]], config: Config) -> list[list[str]]:
    """Descarta las columnas de MAQUETACIÓN: las que tienen muy pocas celdas con
    dato (fracción de relleno < `config.xlsx_min_col_fill`).

    Es el arreglo clave del Gantt: la banda de la línea de tiempo tiene ~1 celda
    llena por columna (el número del día) sobre decenas de filas -> fill ≈ 0.01,
    muy por debajo de la tabla real de la izquierda (fill alto). Solo se poda por
    columnas: las filas de andamiaje que quedan vacías tras quitar esas columnas
    las recoge la segunda pasada de `trim_empty`. No se poda por filas para no
    borrar títulos que viven en una sola celda ("CRONOGRAMA DE ACTIVIDADES").
    """
    if not rows:
        return rows
    nrow = len(rows)
    ncol = max(len(r) for r in rows)
    rows = [r + [""] * (ncol - len(r)) for r in rows]
    min_fill = config.xlsx_min_col_fill
    keep = [
        i for i in range(ncol)
        if sum(1 for row in rows if row[i].strip()) / nrow >= min_fill
    ]
    if not keep:
        return []
    return [[row[i] for i in keep] for row in rows]


def clean_table(rows: list[list[str]], config: Config) -> list[list[str]]:
    """Pipeline de limpieza para una hoja XLSX.

    Siempre: normaliza errores de fórmula + recorta filas/columnas vacías. Si la
    hoja "parece maquetación" (muy ancha) y `xlsx_clean_layout` está activo, además
    descarta ceros de fórmula y las columnas de la línea de tiempo, y vuelve a
    recortar vacíos. Una hoja de datos normal (angosta) NO entra a esa poda.
    """
    rows = normalize_errors(rows, config)
    rows = trim_empty(rows)
    if not rows:
        return rows
    if config.xlsx_trim_dead_tail:
        rows = trim_dead_tail(rows, config)
        rows = trim_empty(rows)   # la cola podía sostener columnas ahora vacías
    if not rows:
        return rows
    ncol = len(rows[0])
    if config.xlsx_clean_layout and ncol >= config.xlsx_layout_min_cols:
        rows = drop_zero_only(rows)
        rows = trim_layout_columns(rows, config)
        rows = trim_empty(rows)
    return rows


def clean_csv(rows: list[list[str]], config: Config) -> list[list[str]]:
    """Limpieza conservadora para CSV/TSV (datos, no maquetación): normaliza
    errores y recorta filas/columnas TOTALMENTE vacías. No aplica la poda por
    densidad/ceros para no sorprender en CSV de datos.
    """
    rows = normalize_errors(rows, config)
    rows = trim_empty(rows)
    return rows
