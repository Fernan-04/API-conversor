"""Jerarquía de excepciones tipificadas por capa (§8.2).

Cuando algo falla, el sistema puede decir EN QUÉ CAPA ocurrió, no solo "hubo un
error":

    ConversionError (base)
    ├── InfrastructureError   ← problema leyendo el archivo de origen (culpa del
    │   ├── UnsupportedFormatError          archivo del usuario -> HTTP 4xx)
    │   ├── CorruptFileError
    │   ├── PasswordProtectedError
    │   └── FileTooLargeError
    └── DomainError           ← problema generando el Markdown (bug interno ->
        ├── MarkdownSyntaxError             HTTP 5xx)
        └── StructureMappingError

Cada excepción trae:
  - `.user_message`: mensaje entendible para el usuario final.
  - `.code`: código estable para logs/soporte (ej. `INFRA_CORRUPT_FILE`).
  - `.layer`: `"infrastructure"` | `"domain"` (para filtrar logs rápido).
  - `.http_status`: cómo la traduce la API a HTTP.
"""

from __future__ import annotations


class ConversionError(Exception):
    """Base de todos los errores de conversión."""

    code: str = "CONVERSION_ERROR"
    layer: str | None = None
    http_status: int = 500

    def __init__(self, user_message: str, *, detail: str | None = None) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.detail = detail


# --------------------------------------------------------------------------- #
# Infraestructura: el archivo de origen tiene un problema (culpa del usuario).
# --------------------------------------------------------------------------- #

class InfrastructureError(ConversionError):
    code = "INFRA_ERROR"
    layer = "infrastructure"
    http_status = 400


class UnsupportedFormatError(InfrastructureError):
    code = "INFRA_UNSUPPORTED_FORMAT"
    http_status = 400

    def __init__(self, extension: str) -> None:
        ext = extension or "(sin extensión)"
        super().__init__(f"Formato no soportado: {ext}")
        self.extension = extension


class CorruptFileError(InfrastructureError):
    code = "INFRA_CORRUPT_FILE"
    http_status = 422

    def __init__(self, user_message: str = "El archivo está dañado o no se puede leer.",
                 *, detail: str | None = None) -> None:
        super().__init__(user_message, detail=detail)


class PasswordProtectedError(InfrastructureError):
    code = "INFRA_PASSWORD_PROTECTED"
    http_status = 422

    def __init__(self, user_message: str = "El archivo está protegido con contraseña.",
                 *, detail: str | None = None) -> None:
        super().__init__(user_message, detail=detail)


class FileTooLargeError(InfrastructureError):
    code = "INFRA_FILE_TOO_LARGE"
    http_status = 413

    def __init__(self, user_message: str = "El archivo excede el tamaño máximo permitido.",
                 *, detail: str | None = None) -> None:
        super().__init__(user_message, detail=detail)


class TooManyFilesError(InfrastructureError):
    """Se enviaron más archivos de los permitidos en una sola petición."""

    code = "INFRA_TOO_MANY_FILES"
    http_status = 413

    def __init__(self, user_message: str = "Se enviaron demasiados archivos en una sola petición.",
                 *, detail: str | None = None) -> None:
        super().__init__(user_message, detail=detail)


class UnauthorizedError(InfrastructureError):
    """Falta la API key o no coincide (solo si `API_KEY` está configurada)."""

    code = "INFRA_UNAUTHORIZED"
    http_status = 401

    def __init__(self, user_message: str = "Falta la API key o es inválida.",
                 *, detail: str | None = None) -> None:
        super().__init__(user_message, detail=detail)


class RateLimitedError(InfrastructureError):
    """Se superó el límite de peticiones (rate limiting)."""

    code = "INFRA_RATE_LIMITED"
    http_status = 429

    def __init__(self, user_message: str = "Demasiadas peticiones. Espera unos segundos e inténtalo de nuevo.",
                 *, detail: str | None = None) -> None:
        super().__init__(user_message, detail=detail)


# --------------------------------------------------------------------------- #
# Dominio: falló la generación del Markdown (bug interno a corregir).
# --------------------------------------------------------------------------- #

class DomainError(ConversionError):
    code = "DOMAIN_ERROR"
    layer = "domain"
    http_status = 500


class MarkdownSyntaxError(DomainError):
    code = "DOMAIN_MD_SYNTAX"


class StructureMappingError(DomainError):
    code = "DOMAIN_STRUCTURE_MAPPING"
