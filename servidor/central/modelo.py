"""Modelos del protocolo, con los límites de CS-002 §2 y §3.1.

Los campos y valores del protocolo van en inglés, como en la sección 4 (D20).
"""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationInfo, field_validator

from .urls import LARGO_MAXIMO, normalizar_url

SPEC_VERSION = "1.0.0"
LAMPORT_MAXIMO = 2**53 - 1  # mayor entero que JavaScript lee sin perder precisión (A9)
PATRON_SERVIDOR = r"^[A-Za-z0-9_-]{1,32}$"  # A5


def _entero_json(valor: Any) -> Any:
    """Acepta 42 y 42.0 (A15); rechaza texto, booleanos y decimales."""
    if isinstance(valor, bool):
        raise ValueError("debe ser un entero ≥ 0")
    if isinstance(valor, float):
        if not valor.is_integer():
            raise ValueError("debe ser un entero ≥ 0")
        return int(valor)
    return valor


Lamport = Annotated[int, BeforeValidator(_entero_json), Field(ge=0, le=LAMPORT_MAXIMO)]


class Mensaje(BaseModel):
    """Mensaje de `#general` tal como llega en `POST /messages`."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True, validate_by_name=True,
                              validate_by_alias=True)

    id: Annotated[str, Field(min_length=1, max_length=100)]
    from_: Annotated[str, Field(alias="from", min_length=1, max_length=100)]
    origin: Annotated[str, Field(min_length=1, max_length=32)]
    lamport: Lamport
    sent_at: Annotated[str, Field(max_length=64)] = ""
    body: Annotated[str, Field(max_length=10_000)] = ""

    def contenido(self) -> tuple[str, str, int, str, str]:
        return (self.from_, self.origin, self.lamport, self.sent_at, self.body)


class MensajeGuardado(Mensaje):
    """Mensaje con su `seq`: lo que devuelve `/history` y lo que viaja en push (A10)."""

    seq: Annotated[int, Field(ge=1)]

    def como_json(self) -> dict[str, Any]:
        # Solo los seis campos de la sección 4, tal como se guardaron, más seq (A13).
        return {
            "id": self.id,
            "from": self.from_,
            "origin": self.origin,
            "lamport": self.lamport,
            "sent_at": self.sent_at,
            "body": self.body,
            "seq": self.seq,
        }


class Registro(BaseModel):
    """Cuerpo de `POST /register`."""

    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)

    server: Annotated[str, Field(pattern=PATRON_SERVIDOR)]
    mode: Literal["push", "pull"] = "push"
    url: str | None = Field(default=None, validate_default=True)

    @field_validator("url")
    @classmethod
    def _url_segun_modo(cls, valor: str | None, info: ValidationInfo) -> str | None:
        if valor is not None and len(valor) > LARGO_MAXIMO:
            raise ValueError(f"la URL puede tener hasta {LARGO_MAXIMO} caracteres")
        modo = info.data.get("mode")
        if modo != "push":
            # En pull la URL es informativa y no se valida (A14). Si `mode` es inválido,
            # ya hay un error para ese campo.
            return valor
        if valor is None:
            raise ValueError("obligatoria en modo push: URL absoluta http o https")
        return normalizar_url(valor)


@dataclass(frozen=True)
class Servidor:
    """Una fila de la tabla `servidores`, con sus mensajes pendientes si está en push."""

    nombre: str
    url: str | None
    modo: str
    registrado_en: str
    renovado_en: str
    visto_en: str | None
    entregado_seq: int | None
    lamport: int | None
    pendientes: int | None = None
