"""Configuración del central, leída solo de variables de entorno (CS-002 §9).

Un valor vacío significa el valor por defecto. Si hay errores, se juntan todos en un
solo `ErrorDeConfiguracion` para que la persona los corrija de una vez.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields


class ErrorDeConfiguracion(Exception):
    """Uno o más valores de configuración inválidos."""

    def __init__(self, problemas: list[str]) -> None:
        self.problemas = problemas
        super().__init__("; ".join(problemas))


@dataclass(frozen=True)
class Configuracion:
    admin_token: str = ""
    ruta_bd: str = "/datos/central.db"
    puerto: int = 9000
    heartbeat_intervalo_s: float = 5.0
    heartbeat_fallos_para_caido: int = 3
    backoff_base_s: float = 1.0
    backoff_max_s: float = 30.0
    http_timeout_s: float = 3.0
    max_servidores: int = 100
    permitir_url_privadas: bool = False
    # Ventana de la señal de vida en pull (CS-002 §3.5). No se lee del entorno.
    ventana_pull_s: float = 60.0

    @property
    def administracion_habilitada(self) -> bool:
        return bool(self.admin_token)

    @classmethod
    def desde_entorno(cls, entorno: Mapping[str, str] | None = None) -> "Configuracion":
        entorno = os.environ if entorno is None else entorno
        valores: dict[str, object] = {}
        problemas: list[str] = []

        def leer(nombre: str) -> str | None:
            crudo = entorno.get(nombre, "").strip()
            return crudo or None

        token = entorno.get("ADMIN_TOKEN", "")
        if token.strip() != token:
            problemas.append("ADMIN_TOKEN no puede empezar ni terminar con espacios")
        elif token:
            valores["admin_token"] = token

        if (ruta := leer("RUTA_BD")) is not None:
            valores["ruta_bd"] = ruta

        enteros = {
            "PUERTO": ("puerto", 1, 65535),
            "HEARTBEAT_FALLOS_PARA_CAIDO": ("heartbeat_fallos_para_caido", 1, 1000),
            "MAX_SERVIDORES": ("max_servidores", 1, 100_000),
        }
        for variable, (campo, minimo, maximo) in enteros.items():
            crudo = leer(variable)
            if crudo is None:
                continue
            try:
                valor = int(crudo)
            except ValueError:
                problemas.append(f"{variable}={crudo!r}: debe ser un entero")
                continue
            if not minimo <= valor <= maximo:
                problemas.append(f"{variable}={valor}: debe estar entre {minimo} y {maximo}")
                continue
            valores[campo] = valor

        decimales = {
            "HEARTBEAT_INTERVALO_S": "heartbeat_intervalo_s",
            "BACKOFF_BASE_S": "backoff_base_s",
            "BACKOFF_MAX_S": "backoff_max_s",
            "HTTP_TIMEOUT_S": "http_timeout_s",
        }
        for variable, campo in decimales.items():
            crudo = leer(variable)
            if crudo is None:
                continue
            try:
                valor = float(crudo)
            except ValueError:
                problemas.append(f"{variable}={crudo!r}: debe ser un número de segundos")
                continue
            if not 0 < valor <= 3600:
                problemas.append(f"{variable}={valor}: debe ser mayor que 0 y como mucho 3600")
                continue
            valores[campo] = valor

        crudo = leer("PERMITIR_URL_PRIVADAS")
        if crudo is not None:
            if crudo.lower() in {"true", "1", "si", "sí"}:
                valores["permitir_url_privadas"] = True
            elif crudo.lower() in {"false", "0", "no"}:
                valores["permitir_url_privadas"] = False
            else:
                problemas.append(f"PERMITIR_URL_PRIVADAS={crudo!r}: debe ser true o false")

        base = valores.get("backoff_base_s", cls.backoff_base_s)
        tope = valores.get("backoff_max_s", cls.backoff_max_s)
        if isinstance(base, float) and isinstance(tope, float) and base > tope:
            problemas.append(f"BACKOFF_BASE_S={base} no puede ser mayor que BACKOFF_MAX_S={tope}")

        if problemas:
            raise ErrorDeConfiguracion(problemas)
        return cls(**valores)  # type: ignore[arg-type]

    def resumen(self) -> dict[str, object]:
        """Valores para el log de arranque, sin el token (salvaguarda 8)."""
        datos = {f.name: getattr(self, f.name) for f in fields(self) if f.name != "admin_token"}
        datos["administracion"] = "habilitada" if self.administracion_habilitada else "deshabilitada"
        return datos
