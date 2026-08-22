# Especificación: `pdf2md` — conversor local de PDF a Markdown

> Documento de contexto para construir el proyecto desde cero.
> Pegar/entregar completo a Claude Code como brief inicial.

---

## 1. Objetivo

Construir una herramienta CLI en Python que convierta archivos PDF a Markdown
**preservando la estructura y sin perder contenido**, ejecutándose **100 % en local**.

### Motivación

Existen soluciones como [`microsoft/markitdown`](https://github.com/microsoft/markitdown),
pero se quiere un desarrollo propio por dos razones:

1. **Privacidad / seguridad**: ningún documento debe salir de la máquina. Cero llamadas
   de red en tiempo de ejecución, cero telemetría, cero APIs de terceros.
2. **Control**: los PDFs objetivo tienen particularidades (tablas de rúbricas académicas,
   páginas impresas desde HTML) que requieren heurísticas ajustables.

### Restricción dura

> El programa **no debe realizar ninguna petición de red**. Todas las dependencias
> se instalan una vez vía pip y trabajan offline. Esto debe quedar documentado en el
> README y, si es viable, verificado con un test.

---

## 2. Alcance

### Dentro del alcance (v1)

- Extracción de texto con orden de lectura correcto.
- Detección de títulos por tamaño de fuente → `#`, `##`, `###`.
- Detección de negritas por nombre de fuente → `**texto**`.
- Extracción de tablas reales → tablas Markdown.
- **Descarte de tablas de maquetación** (ver §5, es el problema central).
- Eliminación de cabeceras y pies de página repetidos.
- Unión de líneas cortadas en párrafos coherentes (con des-hifenización).
- Listas con viñetas y listas numeradas.
- Escapado de caracteres especiales de Markdown.
- Procesamiento por lotes (carpeta completa, opcionalmente recursiva).
- OCR **opcional** para PDFs escaneados (local, vía `tesseract`).

### Fuera del alcance (v1)

- Extracción de imágenes embebidas (dejar como TODO / v2).
- Fórmulas matemáticas a LaTeX.
- PDFs cifrados con contraseña (solo mostrar error claro).
- Interfaz gráfica.

---

## 3. Stack y dependencias

| Componente | Elección | Motivo |
|---|---|---|
| Extracción PDF | `pdfplumber` (>= 0.11) | Da acceso a `page.chars` con `size`, `fontname`, coordenadas — imprescindible para inferir títulos y negritas. Incluye `find_tables()`. |
| Alternativa/complemento | `pypdf` o `pypdfium2` | Fallback rápido si `pdfplumber` falla en un archivo. |
| OCR (opcional) | `pytesseract` + `pillow` + binario `tesseract` | Solo se importa si se pasa `--ocr`, para no forzar la dependencia. |
| CLI | `argparse` (stdlib) | Sin dependencias extra. |
| Tests | `pytest` | — |

Python objetivo: **3.10+** (se usan `list[str]`, `X | None`, `dataclass`).

Estructura sugerida del repo:

```
pdf2md/
├── pdf2md/
│   ├── __init__.py
│   ├── __main__.py        # entry point: python -m pdf2md
│   ├── cli.py             # argparse + orquestación
│   ├── config.py          # dataclass Config con todos los flags
│   ├── extract.py         # PDF -> bloques intermedios
│   ├── tables.py          # detección y filtrado de tablas
│   ├── clean.py           # cabeceras repetidas, ligaduras, normalización
│   └── render.py          # bloques -> Markdown
├── tests/
│   ├── fixtures/*.pdf
│   └── test_*.py
├── pyproject.toml
└── README.md
```

---

## 4. Arquitectura: pipeline en 4 fases

Separar estas fases es importante — mezclarlas es lo que hace que este tipo de
script se vuelva inmantenible.

```
PDF
 │
 ├─ FASE 1 · EXTRACCIÓN
 │   pdfplumber → chars (con size, fontname, x0, top) + tablas candidatas
 │
 ├─ FASE 2 · ESTRUCTURACIÓN
 │   chars → Line(text, size, bold, top, x0)
 │   tablas candidatas → filtro de maquetación → Table(rows)
 │   → lista ordenada de Block por coordenada vertical
 │
 ├─ FASE 3 · LIMPIEZA
 │   descarte de cabeceras/pies repetidos entre páginas
 │   des-hifenización, ligaduras, espacios múltiples
 │
 └─ FASE 4 · RENDER
     Block → Markdown (títulos, párrafos, listas, tablas)
```

### Modelos de datos

```python
@dataclass
class Line:
    text: str
    size: float      # mediana del tamaño de fuente de la línea
    bold: bool       # mayoría de chars con fontname que contiene "Bold"/"Black"
    top: float       # coordenada Y (para ordenar)
    x0: float        # coordenada X inicial (para detectar indentación)

@dataclass
class Block:
    kind: str        # "text" | "table"
    lines: list[Line]
    rows: list[list[str]]
    top: float
```

---

## 5. El problema difícil: tablas de maquetación

**Este es el punto donde falla la implementación ingenua.** Documentarlo bien.

Muchos PDFs se generan imprimiendo una página HTML. Esos HTML usan `<table>` y
`<div>` con bordes para maquetar toda la página. `pdfplumber.find_tables()` los
detecta como tablas, y el resultado es un Markdown donde **la página entera queda
metida dentro de una celda**, con todo el texto concatenado y sin estructura.

### Solución: filtrar en tres capas

**a) Descartar contenedores anidados**

`find_tables()` devuelve tablas superpuestas: una gigante (la maquetación) que
contiene a la real. Si el bbox de la tabla A contiene el bbox de la tabla B, y B no
contiene a A, entonces A es maquetación → descartar A, quedarse con B.

```python
def drop_container_tables(tables):
    return [t for t in tables
            if not any(o is not t
                       and contains_bbox(t.bbox, o.bbox)
                       and not contains_bbox(o.bbox, t.bbox)
                       for o in tables)]
```

**b) Limpiar filas y columnas vacías** antes de evaluar (`tidy_rows`).

**c) Heurísticas de "¿es una tabla de datos real?"** — descartar si:

| Condición | Umbral sugerido | Razón |
|---|---|---|
| Pocas filas o columnas | `< 2` filas o `< 2` columnas | No es tabla |
| Muchas celdas vacías | ratio de celdas con texto `< 0.4` | Es una rejilla de layout |
| Una celda concentra el texto | `len(celda_max) / len(texto_total) > 0.6` | Es un contenedor, no una tabla |
| Ocupa casi toda la página con pocas filas | `área > 85 %` de la página **y** `< 4` filas | Es el marco de la página |

Los umbrales deben vivir en `Config` para poder ajustarlos sin tocar el código.

**d) Excluir el texto de las tablas del flujo de párrafos.** Una vez aceptada una
tabla, los `chars` cuyo centro cae dentro de su bbox **no** se procesan como texto
suelto, o el contenido saldrá duplicado.

---

## 6. Otros problemas conocidos y cómo resolverlos

### 6.1 Texto en columnas se intercala

Si la página tiene varias columnas visuales (típico en rúbricas: `Completo`,
`En proceso 2`, `En proceso 1`, `Inicial`), agrupar por coordenada Y produce líneas
tipo `El proyecto utiliza El proyecto utiliza El proyecto utiliza...`.

Soluciones a implementar:

- Si la tabla se detecta correctamente, esto se resuelve solo → **priorizar §5**.
- Para texto libre en columnas: detectar franjas verticales agrupando los `x0` de las
  líneas (clustering 1-D). Si hay ≥ 2 grupos claros con separación amplia, procesar
  cada columna de arriba abajo antes de pasar a la siguiente.
- Exponer un flag `--single-column` para forzar el comportamiento simple.

### 6.2 Cabeceras y pies repetidos

Contar las 3 primeras y 3 últimas líneas de cada página, normalizando dígitos
(`re.sub(r"\d+", "#", texto.lower())`) para que `Página 1/8` y `Página 2/8` coincidan.
Si una clave aparece en ≥ 50 % de las páginas → eliminar. Aplicar solo si el
documento tiene ≥ 3 páginas. Flag `--keep-repeated` para desactivar.

### 6.3 Fragmentos de URL / footers partidos

Las URLs largas del pie se parten y dejan basura tipo `h 4` o `1/`. Tras el filtro
de repetidos, aplicar una limpieza final: descartar líneas de ≤ 3 caracteres que no
sean parte de una lista, y colapsar `\n{3,}` a `\n\n`.

### 6.4 Detección de títulos

Calcular el tamaño de fuente **modal** del documento (no la media) = cuerpo de texto.
Toda línea con `size >= body_size * 1.15` es candidata a título. Ordenar los tamaños
distintos de mayor a menor y mapear los 4 primeros a `#`, `##`, `###`, `####`.

Refuerzos opcionales: una línea corta (`< 80` chars), en negrita, sin punto final y
seguida de línea en blanco, también puede tratarse como título aunque el tamaño no
suba.

### 6.5 Ligaduras y caracteres Unicode

Normalizar `ﬁ ﬂ ﬀ ﬃ ﬄ`, comillas tipográficas, guiones largos, espacios duros.

### 6.6 Espacios entre palabras

`pdfplumber` no siempre inserta espacios. Al concatenar chars, insertar un espacio si
`char.x0 - char_anterior.x1 > max(1.2, size * 0.28)`.

### 6.7 Des-hifenización

Si una línea termina en `-` y la siguiente empieza en minúscula, unir sin el guion.
Cuidado con palabras compuestas legítimas (`front-end`): solo aplicar en salto de línea.

### 6.8 Escapado de Markdown

Escapar `\ ` `` ` `` `*` `_` `{}` `[]` `()` `#` `+` `|` en el texto plano.
**No escapar** dentro de bloques de código. En celdas de tabla, además reemplazar
saltos de línea por espacios y escapar `|`.

---

## 7. Interfaz de línea de comandos

```
python -m pdf2md ENTRADA [-o SALIDA] [opciones]
```

| Flag | Efecto |
|---|---|
| `ENTRADA` | Archivo `.pdf` o carpeta con PDFs |
| `-o, --output` | Archivo `.md` de salida, o carpeta si la entrada es carpeta. Por defecto: junto al PDF |
| `-r, --recursive` | Buscar PDFs en subcarpetas |
| `--overwrite` | Sobrescribir el `.md` si ya existe. Por defecto: omitir y avisar `[skip] rubrica1.md ya existe` |
| `--no-tables` | No extraer tablas |
| `--no-headings` | No inferir títulos por tamaño de fuente |
| `--no-bold` | No marcar negritas |
| `--keep-repeated` | Conservar cabeceras y pies repetidos |
| `--no-join` | Una línea del PDF = una línea del Markdown |
| `--single-column` | Forzar lectura de una sola columna |
| `--page-markers` | Insertar `<!-- pagina N -->` |
| `--page-break` | Insertar `---` entre páginas |
| `--ocr` | OCR en páginas sin capa de texto |
| `--ocr-lang` | Idioma de OCR (default `spa`) |
| `--stdout` | Imprimir en consola en vez de escribir archivo |
| `-v, --verbose` | Log de decisiones: tablas aceptadas/descartadas, líneas filtradas |

Códigos de salida: `0` ok, `1` error de entrada, `2` todos los archivos fallaron.

### 7.1 Organización de la salida (importante)

Aunque el CLI soporta los tres modos, **el flujo recomendado y el que debe destacarse
en el README es la carpeta separada**:

```
proyecto/
├── pdfs/          ← originales, nunca se tocan
│   ├── rubrica1.pdf
│   └── rubrica2.pdf
└── markdown/      ← generado, regenerable, desechable
    ├── rubrica1.md
    └── rubrica2.md
```

```bash
python -m pdf2md pdfs/ -o markdown/
```

Razones: se puede borrar y regenerar `markdown/` sin riesgo para los originales, y el
listado de originales queda limpio.

Los otros dos modos (sin `-o`, que escribe junto al PDF; y `-o archivo.md` para un
solo archivo) siguen existiendo, pero se documentan como secundarios.

### 7.2 Protección contra sobrescritura

Por defecto el programa **no** debe sobrescribir un `.md` existente: debe imprimir
`[skip] rubrica1.md ya existe (usa --overwrite)` y continuar con el siguiente archivo.
Esto evita destruir ediciones manuales al reejecutar el comando sobre la misma carpeta.

`--verbose` es importante para depurar las heurísticas de §5: debe decir
`[tabla] descartada (ratio de llenado 0.21)` y similares.

---

## 8. Comportamiento esperado en errores

- PDF con contraseña → mensaje claro, continuar con los demás archivos del lote.
- PDF corrupto → capturar excepción, `[error] nombre.pdf: <motivo>`, seguir.
- PDF sin capa de texto y sin `--ocr` → advertir que probablemente es escaneado y
  sugerir `--ocr`.
- `--ocr` sin `pytesseract` instalado → mensaje con el comando de instalación exacto.
- Un fallo en un archivo **nunca** debe abortar el lote completo.

---

## 9. Tests

Crear `tests/fixtures/` con PDFs pequeños generados o recortados:

| Test | Verifica |
|---|---|
| `test_simple_text` | Párrafos y títulos básicos |
| `test_layout_table_discarded` | Una página HTML impresa **no** produce una tabla Markdown gigante |
| `test_real_table_kept` | Una tabla de datos real sí se convierte a tabla Markdown con el número correcto de columnas |
| `test_repeated_header_removed` | La cabecera aparece 0 veces en la salida de un PDF de 5 páginas |
| `test_no_content_loss` | El conjunto de palabras del PDF ⊆ conjunto de palabras del `.md` (tolerando cambios de espaciado) |
| `test_no_network` | Monkeypatch de `socket.socket` para que falle; la conversión debe completarse igual |
| `test_batch_continues_on_error` | Un PDF corrupto en la carpeta no impide convertir los demás |
| `test_no_overwrite_by_default` | Reejecutar el comando no pisa un `.md` ya existente sin `--overwrite` |

`test_no_content_loss` es el más valioso: es la garantía de "sin perder ningún dato".

---

## 10. README (contenido mínimo)

> Nota: el README se escribe como documentación **para el propio autor**, no para
> publicar. Ver §13.4.

1. Qué hace y qué **no** hace.
2. Declaración explícita de privacidad: procesamiento local, sin red.
3. Instalación (incluyendo `tesseract` por sistema operativo, marcado como opcional).
4. Ejemplos de uso para los 5 casos más comunes, **empezando por el patrón
   `pdfs/` → `markdown/` de §7.1**.
5. Sección "Limitaciones conocidas": columnas complejas, PDFs escaneados de baja
   calidad, tablas con celdas combinadas.
6. Sección "Ajustar heurísticas": qué umbrales tocar en `config.py` y para qué.

---

## 11. Criterios de aceptación

La v1 está lista cuando:

- [ ] `rubrica1.pdf` (página HTML impresa) produce **una tabla Markdown correcta**,
      no un bloque de texto con la página entera en una celda.
- [ ] `APF1_INDICACION.pdf` conserva su tabla de rúbrica de 6 columnas: el filtro
      **no** la descarta por confundirla con maquetación.
- [ ] Ambos criterios anteriores se cumplen **con los mismos umbrales**, sin
      configuración distinta por archivo.
- [ ] No hay contenido duplicado entre el flujo de párrafos y las tablas.
- [ ] Las cabeceras/pies repetidos no aparecen en la salida.
- [ ] Los títulos del documento se mapean a niveles `#` coherentes.
- [ ] `test_no_content_loss` pasa en todos los fixtures.
- [ ] `test_no_network` pasa.
- [ ] Procesa una carpeta de 10 PDFs sin abortar aunque uno esté corrupto.
- [ ] `--verbose` explica por qué se descartó cada tabla candidata.
- [ ] Correr el comando dos veces sobre la misma carpeta no destruye ediciones manuales.
- [ ] El README documenta el patrón `pdfs/` → `markdown/` como flujo recomendado.
- [ ] No se ha creado ningún archivo de publicación (git, CI, licencia). Ver §13.4.

---

## 12. Ideas para v2 (no implementar ahora)

- Extraer imágenes a `assets/` y referenciarlas con `![](assets/img-01.png)`.
- Detección de celdas combinadas (`colspan`/`rowspan`) → HTML embebido en el Markdown.
- Salida en otros formatos: JSON estructurado, YAML front-matter con metadatos del PDF.
- Modo `--diff`: comparar dos PDFs a nivel de Markdown.
- Paralelizar el lote con `concurrent.futures.ProcessPoolExecutor`.
- Perfiles guardables (`--profile rubrica-utp`) con umbrales preajustados por tipo de documento.

---

## 13. Notas de arranque (leer antes de escribir código)

### 13.1 Estado actual del repo

El repositorio ya contiene:

```
pdf2md/
├── docs/
│   └── SPEC_pdf2md.md     ← este documento
└── pdfs/                  ← PDFs de prueba reales
```

No hay código todavía. Se construye desde cero.

### 13.2 PDFs de prueba reales

La carpeta `pdfs/` contiene documentos reales del caso de uso. Son **dos casos
opuestos a propósito**, y el proyecto solo está bien cuando ambos salen correctos
a la vez:

| Archivo | Qué es | Qué verifica |
|---|---|---|
| `rubrica1.pdf` | Página HTML impresa desde UTP+class | Que el filtro **descarte** las tablas de maquetación que envuelven toda la página |
| `APF1_INDICACION.pdf` | Documento hecho en Word, con una tabla de rúbrica legítima de 6 columnas | Que el filtro **no descarte** tablas de datos reales por ser demasiado agresivo |

Ese equilibrio es el criterio central de la §5: un filtro demasiado permisivo rompe
el primero, uno demasiado estricto rompe el segundo.

Usarlos directamente como fixtures, o copiarlos a `tests/fixtures/`. **No inventar
PDFs de prueba sintéticos mientras existan estos**, porque los sintéticos no
reproducen el problema que hay que resolver.

Fallo conocido a reproducir y corregir: con `pdfplumber.find_tables()` sin filtrar,
la salida de `rubrica1.pdf` es una tabla Markdown gigante con la página entera dentro
de una sola celda, más texto de columnas intercalado tipo
`El proyecto utiliza El proyecto utiliza El proyecto utiliza...`, más fragmentos
basura (`h 4`, `1/`) procedentes de las URLs largas del pie de página que se parten
entre líneas.

### 13.3 Entorno virtual

Crear el entorno **antes** de instalar nada, para no contaminar el Python del sistema:

```bash
python3 -m venv .venv
source .venv/bin/activate        # Linux / macOS
# .venv\Scripts\activate         # Windows
pip install pdfplumber pytest
```

`pytesseract` y `pillow` solo si se va a probar `--ocr`.

### 13.4 Proyecto local, sin control de versiones

Este proyecto es **de uso personal y local**. Por ahora **no se sube a ningún
repositorio remoto**. No inicializar git ni crear `.gitignore`, `LICENSE`,
workflows de CI, badges, ni ningún archivo pensado para publicar.

El README (§10) se escribe igualmente, pero como documentación para el propio autor:
cómo se usa la herramienta y qué umbrales tocar cuando algo salga mal. Nada de
secciones de "contribuir", instalación desde PyPI, ni ejemplos para terceros.

Si más adelante se decide publicarlo, eso será un paso aparte.

### 13.5 Estructura final esperada

```
pdf2md/
├── .venv/                 (entorno virtual)
├── docs/
│   └── SPEC_pdf2md.md
├── pdfs/                  (PDFs de prueba reales)
├── markdown/              (salida generada, regenerable)
├── pdf2md/                (el paquete Python, ver §3)
├── tests/
├── pyproject.toml
└── README.md
```

### 13.6 Orden de trabajo sugerido

1. Esqueleto del paquete + CLI mínimo que solo extraiga texto plano.
2. **§5 completa** — filtrado de tablas de maquetación. Es el corazón del proyecto;
   validar contra los PDFs de `pdfs/` antes de seguir.
3. Detección de títulos y negritas (§6.4).
4. Limpieza de cabeceras repetidas (§6.2) y fragmentos basura (§6.3).
5. Párrafos, des-hifenización, listas, escapado (§6.5–6.8).
6. Lote, `--overwrite`, `--verbose`, manejo de errores (§7, §8).
7. Tests (§9) y README (§10).
8. Columnas múltiples (§6.1) — dejar para el final, es lo más frágil.

No pasar a un punto sin que el anterior funcione sobre los PDFs reales de `pdfs/`.
