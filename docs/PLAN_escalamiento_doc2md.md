
# Plan de escalamiento: de `pdf2md` a un conversor web multi-formato

## 0. Punto de partida

Ya existe y funciona:
- **`pdf2md`**: paquete Python que convierte PDF → Markdown, con heurísticas
  propias (títulos por tamaño de fuente, detección de tablas reales vs.
  maquetación, limpieza de cabeceras/pies repetidos, etc.)
- CLI funcional (`python -m pdf2md pdfs/ -o markdown/`)
- Tests con `pytest` usando PDFs reales como fixtures
- 100% local, sin red, sin telemetría

## 1. Visión del proyecto final

Una web (accesible desde PC y celular, sin instalar nada) donde el usuario:
1. Entra al enlace (desplegado en Vercel).
2. Sube uno o varios documentos: **PDF, Word (.docx), PowerPoint (.pptx),
   Excel (.xlsx)**.
3. Un botón dispara la conversión a Markdown.
4. Otro botón descarga el/los resultado(s) (`.md` individual o `.zip` si son
   varios).

Sin comandos, sin terminal, sin instalar Python — todo visual.

## 2. Decisión importante que hay que tomar primero

⚠️ **Trade-off de privacidad.** El proyecto actual presume "cero red, cero
telemetría, todo local" (ver README, sección Privacidad). Al pasar a una web
pública, los archivos que el usuario suba **sí viajarán a un servidor**
(el tuyo, pero servidor al fin) para poder convertirlos.

Opciones a decidir antes de empezar a construir:

| Opción | Pros | Contras |
|---|---|---|
| **A. Servidor propio procesa los archivos** (lo más simple) | Reusa el motor Python tal cual, rápido de construir | Los archivos salen de la máquina del usuario, aunque sea a un backend controlado por ti |
| **B. Procesamiento en el navegador (client-side, WASM/Pyodide)** | Mantiene la promesa "nunca sale de tu equipo" | Mucho más complejo, Pyodide es pesado, portar pdfplumber a WASM no es trivial, PPTX/DOCX/XLSX en el navegador también piden librerías JS específicas |
| **C. Híbrido**: opción A por defecto, con aviso claro al usuario | Balance realista | Igual requiere servidor |

**Recomendación:** empezar con la **Opción A**, siendo transparente en la UI
("tus archivos se procesan en un servidor y se borran tras la conversión").
Migrar a client-side más adelante es una optimización futura, no un bloqueo
para lanzar.

### 2.1 Garantía de no-persistencia (requisito explícito)

Aunque el archivo original y el `.md` resultante pasan por el servidor
durante la conversión, **nada se guarda de forma permanente en ningún
lado**. Ni el archivo subido ni el Markdown generado se almacenan en disco,
base de datos, ni ningún servicio externo. El único lugar donde queda el
resultado es en la descarga que hace el propio usuario a su dispositivo.

Esto debe cumplirse a nivel de diseño de la API, no solo como promesa en la
UI:

- [ ] El archivo subido se procesa **en memoria o en un archivo temporal**
      que se borra inmediatamente después de responder (ya sea que la
      conversión funcione o falle).
- [ ] La respuesta de la API entrega el Markdown **directamente en el
      cuerpo de la respuesta HTTP** (o como stream), nunca guardándolo
      primero en un bucket, base de datos o carpeta persistente del
      servidor.
- [ ] No hay logs que guarden el contenido de los archivos (los logs, si
      los hay, deben limitarse a metadatos técnicos: tamaño, tipo,
      duración — nunca el contenido).
- [ ] No hay historial de conversiones ni cuentas de usuario en la v1 —
      justamente para no tener que decidir "dónde guardar" nada.
- [ ] Si se usa almacenamiento temporal en disco durante el procesamiento
      (por ejemplo, para archivos grandes que no caben cómodos en memoria),
      debe limpiarse con un `try/finally` que garantice el borrado incluso
      si la conversión lanza una excepción.

En otras palabras: el servidor actúa como una "cinta transportadora" que
transforma el archivo al vuelo y lo entrega — no como un almacén.

## 3. Arquitectura propuesta

```
┌─────────────────────────┐        HTTPS         ┌──────────────────────────┐
│   Frontend (Next.js +   │ ───── sube archivo ──▶│   API de conversión      │
│   TypeScript, en Vercel)│ ◀──── descarga .md ────│   (Python, FastAPI)      │
│   - drag & drop         │                       │   - reusa pdf2md         │
│   - botón "Convertir"   │                       │   - + módulos docx/pptx/ │
│   - botón "Descargar"   │                       │     xlsx                 │
└─────────────────────────┘                       └──────────────────────────┘
```

**Por qué dos servicios separados y no todo en Vercel:**
Vercel es excelente para el frontend (Next.js) y funciones serverless
livianas en Node/TypeScript, pero **no es un buen lugar para correr Python
con librerías pesadas** (pdfplumber, Pillow, etc.) por límites de tiempo de
ejecución y tamaño de paquete en sus funciones serverless. El motor de
conversión en Python necesita un hosting distinto que sí soporte procesos
Python normales: **Railway, Render o Fly.io** son las opciones más simples
(tienen capa gratuita, despliegan desde un repo Git con un `Dockerfile` o
`requirements.txt`, y no hay que administrar servidores).

## 4. Fases de trabajo

### Fase 1 — Extender el motor de conversión (sigue en Python, sin UI todavía)
- [ ] Añadir soporte **DOCX**: usar `python-docx` (o `pandoc` si se prefiere
      reusar la lógica que ya usamos para leer Word) para extraer texto,
      títulos por estilo (`Heading 1`, `Heading 2`...), listas y tablas.
- [ ] Añadir soporte **PPTX**: usar `python-pptx`, extrayendo texto de cada
      diapositiva, títulos de slide como encabezados, y notas del orador
      como bloque aparte.
- [ ] Añadir soporte **XLSX**: usar `openpyxl` u `openpyxl` + `pandas`,
      convirtiendo cada hoja a una tabla Markdown (con límite razonable de
      filas para hojas enormes).
- [ ] Refactor: unificar todo bajo una función `convert(path) -> markdown`
      que detecte el tipo de archivo por extensión y llame al extractor
      correspondiente (mismo patrón "router" que ya usa `pdf2md`).
- [ ] Tests: un PDF, un DOCX, un PPTX y un XLSX de ejemplo como fixtures,
      igual que ya se hace con `rubrica1.pdf`.

### Fase 2 — Exponer el motor como API
- [ ] Envolver el conversor con **FastAPI**: un endpoint
      `POST /convert` que reciba un archivo (`multipart/form-data`) y
      devuelva el Markdown resultante (o un `.zip` si se suben varios).
- [ ] Manejo de errores claro: formato no soportado, archivo corrupto,
      PDF con contraseña, etc. → respuestas JSON con mensaje entendible.
- [ ] Límite de tamaño de archivo razonable (evitar abusos).
- [ ] **Cero persistencia**: ni el archivo original ni el `.md` generado se
      guardan en disco permanente, base de datos ni almacenamiento externo
      (ver sección 2.1). Todo temporal se borra con `try/finally` sin
      importar si la conversión fue exitosa o falló.
- [ ] `Dockerfile` simple para que Railway/Render puedan desplegar sin
      configuración manual.

### Fase 3 — Desplegar la API
- [ ] Elegir hosting (Railway o Render, capa gratuita para empezar).
- [ ] Desplegar y obtener una URL pública HTTPS (ej.
      `https://doc2md-api.up.railway.app`).
- [ ] Probar el endpoint con `curl` o Postman antes de tocar el frontend.

### Fase 4 — Construir el frontend visual
- [ ] Proyecto **Next.js + TypeScript** (App Router).
- [ ] Pantalla única, mobile-first:
  - Zona de **arrastrar y soltar** archivos (o botón "Elegir archivo").
  - Lista de archivos subidos con su tipo detectado (PDF/DOCX/PPTX/XLSX).
  - Botón **"Convertir"** → llama a la API (`POST /convert`).
  - Indicador de progreso mientras convierte.
  - Botón **"Descargar"** una vez lista la conversión (`.md` o `.zip`).
- [ ] Diseño responsive: que se vea bien tanto en navegador de PC como en
      el navegador del celular (no hace falta app nativa).
- [ ] Manejo de errores visual (archivo no soportado, error de red, etc.)

### Fase 5 — Desplegar el frontend
- [ ] Repo del frontend en GitHub.
- [ ] Conectar el repo a **Vercel** (deploy automático en cada push).
- [ ] Variable de entorno con la URL de la API (para no hardcodearla).
- [ ] Dominio final: el que asigne Vercel (`tuproyecto.vercel.app`) o uno
      propio si se compra después.

### Fase 6 — Pulido final
- [ ] Soporte para **conversión múltiple** (varios archivos a la vez →
      descarga en `.zip`).
- [ ] Aviso de privacidad visible ("tus archivos se procesan en el
      servidor solo durante la conversión y no se guardan en ningún
      lado — ni el original ni el resultado; lo único que persiste es lo
      que tú descargas a tu dispositivo").
- [ ] Manejo de archivos grandes / timeouts.
- [ ] (Opcional, futuro) Vista previa del Markdown antes de descargar.
- [ ] ❌ **Descartado para esta v1** (no solo opcional): historial de
      conversiones, cuentas de usuario, login. El proyecto es de uso
      personal / grupo pequeño sin registro — ver sección 6.1. Si algún
      día se decide escalar a más usuarios o cobrar, ahí se revisita.

## 5. Stack tecnológico resumen

| Parte | Tecnología |
|---|---|
| Motor de conversión | Python (extendiendo `pdf2md` actual) |
| Librerías de extracción | `pdfplumber` (PDF), `python-docx` (Word), `python-pptx` (PowerPoint), `openpyxl` (Excel) |
| API | FastAPI |
| Hosting de la API | Railway o Render |
| Frontend | Next.js + TypeScript |
| Hosting del frontend | Vercel |

## 6. Preguntas abiertas para decidir antes de empezar a construir con Claude

1. ¿Confirmas la Opción A de privacidad (servidor procesa y borra), o
   prefieres explorar client-side desde ya aunque sea más lento de construir?
2. ¿Railway o Render para la API? (ambos son similares, Railway suele ser
   más simple de configurar la primera vez).
3. ¿El límite de tamaño de archivo aceptable? (afecta el plan gratuito del
   hosting).
4. ✅ **Ya decidido**: sin autenticación ni cuentas de usuario. Es un
   proyecto de uso personal / para un grupo pequeño de personas con el
   enlace, no un producto abierto al público general. Esto simplifica
   bastante la v1 (ver sección 6.1).
5. ¿Nombre del proyecto? (para el dominio de Vercel y el repo).

### 6.1 Implicaciones de "sin cuentas, uso personal / grupo pequeño"

Esto simplifica varias cosas del plan y conviene tenerlas explícitas para
que Claude Code no las agregue "por si acaso":

- [ ] **No hay login, registro ni sesiones.** La web es de acceso libre
      para quien tenga el enlace — no hay pantalla de "iniciar sesión".
- [ ] **No hay base de datos de usuarios.** No hace falta Postgres, ni
      Supabase, ni Auth0, ni nada similar en la v1.
- [ ] **No hay tracking de quién sube qué.** Ni siquiera de forma anónima
      (analytics, IDs de sesión persistentes, etc.) — coherente con el
      punto de "cero persistencia" de la sección 2.1.
- [ ] Como la audiencia es pequeña y conocida (tú y quizás algunas
      personas más), el límite de tamaño de archivo y el plan gratuito de
      Railway/Render y Vercel deberían alcanzar sin problema — no hace
      falta sobre-diseñar para escala masiva desde el día uno.
- [ ] Si más adelante se quiere abrir a más gente o cobrar por el
      servicio, ahí sí conviene reconsiderar cuentas, límites de uso por
      usuario, y algún tipo de autenticación — pero eso es una fase
      *futura y opcional*, no parte de esta v1.

## 7. Orden sugerido de ataque con Claude Code

1. Fase 1 completa (extender el motor en Python, con tests) — se puede
   seguir haciendo igual que hasta ahora, en local.
2. Fase 2 (API) — aún en local, probando con `curl`.
3. Fase 3 (desplegar API) — primer punto donde algo queda "en la nube".
4. Fase 4 y 5 (frontend + Vercel) — recién aquí se necesita TypeScript.
5. Fase 6 (pulido) — al final, con todo ya funcionando de punta a punta.

Este orden evita construir la interfaz visual antes de tener un motor de
conversión confiable — así cada pieza se prueba por separado antes de
integrarla.

## 8. Requisitos de arquitectura y calidad de código (obligatorios)

Estos cuatro puntos no son opcionales dentro del plan: son la base para que
el proyecto se pueda mantener y depurar fácilmente a medida que se agreguen
más formatos. Se aplican **desde la Fase 1**, no como algo a agregar al
final.

### 8.1 Arquitectura hexagonal para el motor de conversión

El motor (hoy `pdf2md`, mañana `doc2md`) se organiza en dos capas
claramente separadas, con el **dominio en el centro** y sin dependencias
hacia afuera:

```
┌─────────────────────────────────────────────────────────┐
│                     ADAPTADORES (infraestructura)         │
│                                                             │
│  ┌───────────────┐   ┌───────────────┐   ┌──────────────┐ │
│  │  Adaptador     │   │  Adaptador     │   │  Adaptador   │ │
│  │  de entrada:   │   │  de lectura:   │   │  de lectura: │ │
│  │  HTTP (FastAPI)│   │  PDF (plumber) │   │  DOCX/PPTX/  │ │
│  │  recibe archivo│   │                │   │  XLSX        │ │
│  └───────┬───────┘   └───────┬───────┘   └──────┬───────┘ │
│          │                   │                    │        │
│          ▼                   ▼                    ▼        │
│  ┌─────────────────────────────────────────────────────┐  │
│  │              PUERTOS (interfaces)                     │  │
│  │  - `DocumentReader` (entrada: bytes → estructura       │  │
│  │    intermedia neutral: título, párrafo, tabla, lista)  │  │
│  │  - `MarkdownRenderer` (salida: estructura → texto .md) │  │
│  └───────────────────────┬───────────────────────────────┘  │
└──────────────────────────┼──────────────────────────────────┘
                            ▼
              ┌───────────────────────────┐
              │         DOMINIO            │
              │  (puro, sin I/O, sin red,  │
              │   sin saber de HTTP ni de  │
              │   PDF/Word/Excel)          │
              │                             │
              │  - Reglas de conversión a   │
              │    sintaxis Markdown        │
              │  - Detección de tablas vs.  │
              │    maquetación              │
              │  - Limpieza (des-hifenizar, │
              │    cabeceras repetidas...)  │
              └───────────────────────────┘
```

**Regla de dependencia:** el dominio no importa nada de `pdfplumber`,
`python-docx`, `FastAPI` ni ninguna librería de infraestructura. Los
adaptadores dependen del dominio a través de los puertos — nunca al revés.
Esto es lo que permite, por ejemplo, agregar soporte para un formato nuevo
(EPUB, HTML...) escribiendo solo un adaptador de lectura nuevo, sin tocar
una sola línea de las reglas de conversión.

- [ ] Carpeta `domain/`: estructura intermedia (`Document`, `Heading`,
      `Paragraph`, `Table`, `ListBlock`...) + el renderer a Markdown. Cero
      imports de librerías externas de parseo.
- [ ] Carpeta `adapters/inbound/`: el endpoint HTTP de FastAPI que recibe
      el archivo subido y llama al puerto de entrada.
- [ ] Carpeta `adapters/outbound/`: un lector por formato
      (`pdf_reader.py`, `docx_reader.py`, `pptx_reader.py`,
      `xlsx_reader.py`), cada uno implementando la interfaz `DocumentReader`
      y devolviendo la estructura intermedia del dominio.
- [ ] El "router" que hoy detecta la extensión y elige el lector correcto
      vive en la capa de adaptadores, no en el dominio.

### 8.2 Manejo explícito de errores, tipificados por fase

Cuando algo falla, el sistema debe poder decir **en qué capa ocurrió**, no
solo "hubo un error". Se define una jerarquía de excepciones propia:

```
ConversionError (base)
│
├── InfrastructureError          ← algo falló leyendo el archivo de origen
│   ├── UnsupportedFormatError   (extensión no soportada)
│   ├── CorruptFileError         (archivo dañado / ilegible)
│   ├── PasswordProtectedError   (PDF/DOCX con contraseña)
│   └── FileTooLargeError        (excede el límite configurado)
│
└── DomainError                  ← algo falló generando el Markdown
    ├── MarkdownSyntaxError      (la estructura intermedia no se pudo
    │                             renderizar a sintaxis Markdown válida)
    └── StructureMappingError    (un elemento del documento de origen no
                                   tiene mapeo claro a la estructura
                                   intermedia del dominio)
```

- [ ] Cada excepción trae un mensaje entendible para el usuario final
      *y* un `código de error` estable para logs/soporte (ej.
      `INFRA_CORRUPT_FILE`, `DOMAIN_MD_SYNTAX`).
- [ ] La API traduce estas excepciones a respuestas HTTP claras:
      infraestructura → `400/422` (problema con el archivo del usuario);
      dominio → `500` (bug interno a corregir, no culpa del usuario).
- [ ] El frontend distingue ambos casos en el mensaje que le muestra al
      usuario: "tu archivo tiene un problema" vs. "algo falló de nuestro
      lado, ya quedó registrado".

### 8.3 Procesamiento sin estado (stateless) y en streaming

**Nota de coherencia con la sección 3:** tal como está definida la
arquitectura, el motor de conversión (Python) corre en **Railway o
Render**, no en Vercel — Vercel solo aloja el frontend. El principio de
"sin estado, procesar en memoria/streaming" aplica igual de importante en
Railway/Render que en Vercel, así que se mantiene el requisito, solo
corrigiendo dónde vive.

- [ ] El archivo subido se procesa como **stream** en la medida que las
      librerías lo permitan (`pdfplumber` y similares suelen requerir un
      archivo o buffer completo — en ese caso, usar un archivo temporal en
      memoria (`io.BytesIO`) o en disco efímero, nunca disco persistente).
- [ ] Nada de variables globales ni caché en memoria compartida entre
      peticiones — cada conversión es independiente y no debe depender de
      que otra petición haya pasado antes (importante en un entorno
      serverless/multi-instancia como Railway/Render, donde no hay
      garantía de que la misma instancia atienda dos peticiones seguidas).
- [ ] Límite de tamaño de archivo definido explícitamente en config, para
      no saturar la memoria disponible de la instancia (ver pregunta
      abierta #3 en la sección 6).
- [ ] La respuesta al frontend se arma y se envía apenas está lista —no se
      guarda "por si se vuelve a pedir", coherente con la sección 2.1.

### 8.4 Trazabilidad rápida: logging estructurado (JSON)

Cada conversión (exitosa o fallida) genera **una única línea de log en
formato JSON**, para poder buscar y filtrar rápido en los logs de
Railway/Render (o en Vercel para lo que corresponda al frontend/API
gateway si aplica).

Campos mínimos:

```json
{
  "timestamp": "2026-08-21T22:14:03Z",
  "format_origen": "docx",
  "tamano_bytes": 154823,
  "duracion_ms": 842,
  "resultado": "ok",
  "codigo_error": null
}
```

En caso de error:

```json
{
  "timestamp": "2026-08-21T22:15:11Z",
  "format_origen": "pdf",
  "tamano_bytes": 2043199,
  "duracion_ms": 130,
  "resultado": "error",
  "codigo_error": "INFRA_PASSWORD_PROTECTED",
  "capa": "infrastructure"
}
```

- [ ] **Nunca** se incluye el contenido del archivo ni del Markdown
      generado en el log — solo metadatos técnicos (coherente con la
      sección 2.1).
- [ ] El campo `capa` (`"domain"` / `"infrastructure"`) permite filtrar de
      inmediato si el problema es de lectura de archivos o de las reglas
      de conversión, sin tener que leer el mensaje completo.
- [ ] Estos logs son efímeros (los que da la plataforma de hosting por
      defecto) — no se persisten en una base de datos propia, para no
      contradecir el punto de "cero almacenamiento" de la sección 2.1.
