"""URL de los grupos en push: forma (CS-002 §3.1) y destinos permitidos (A2).

Como el registro es abierto (D06) y el central llama a la URL registrada, en la nube se
rechaza toda URL que resuelva a una dirección de loopback, privada, de enlace local,
reservada, multicast o sin especificar. Así nadie usa el central para llegar a la red
interna de la VM, por ejemplo al servicio de metadatos en 169.254.169.254. La
comprobación se hace al registrar y antes de cada llamada, porque el DNS puede cambiar.
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

LARGO_MAXIMO = 2048


def normalizar_url(texto: str) -> str:
    """Devuelve la URL base sin la `/` final, o lanza ValueError con el motivo."""
    if len(texto) > LARGO_MAXIMO:
        raise ValueError(f"la URL puede tener hasta {LARGO_MAXIMO} caracteres")
    if texto != texto.strip() or any(c.isspace() for c in texto):
        raise ValueError("la URL no puede tener espacios")
    try:
        partes = urlsplit(texto)
        puerto = partes.port
    except ValueError:
        raise ValueError("URL mal formada") from None
    if partes.scheme.lower() not in {"http", "https"}:
        raise ValueError("obligatoria en modo push: URL absoluta http o https")
    if not partes.hostname:
        raise ValueError("la URL debe incluir el nombre o la IP del servidor")
    if partes.username is not None or partes.password is not None:
        raise ValueError("la URL no puede llevar usuario ni contraseña")
    if partes.query or partes.fragment or texto.endswith(("?", "#")):
        raise ValueError("la URL base no puede llevar parámetros (?) ni fragmento (#)")
    if puerto == 0:
        raise ValueError("el puerto de la URL no puede ser 0")
    url = f"{partes.scheme.lower()}://{partes.netloc}{partes.path}"
    return url.rstrip("/")


def _direccion_prohibida(texto: str) -> bool:
    ip = ipaddress.ip_address(texto.split("%", 1)[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return not ip.is_global or ip.is_multicast


async def motivo_destino_prohibido(url: str, permitir_privadas: bool) -> str | None:
    """None si el central puede llamar a esa URL; si no, el motivo en español."""
    if permitir_privadas:
        return None
    partes = urlsplit(url)
    nombre = partes.hostname or ""
    try:
        puerto = partes.port or (443 if partes.scheme == "https" else 80)
    except ValueError:
        return "URL mal formada"
    try:
        _direccion_prohibida(nombre)
        direcciones = [nombre]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                nombre, puerto, type=socket.SOCK_STREAM
            )
        except (socket.gaierror, UnicodeError, OSError):
            return f"no se pudo resolver el nombre {nombre}"
        direcciones = sorted({info[4][0] for info in infos})
        if not direcciones:
            return f"no se pudo resolver el nombre {nombre}"
    for direccion in direcciones:
        if _direccion_prohibida(direccion):
            sujeto = nombre if direccion == nombre else f"{nombre} resuelve a {direccion}, que"
            return (
                f"{sujeto} es una dirección privada, local o reservada; "
                "en la nube el central solo llama a direcciones públicas"
            )
    return None


async def es_destino_permitido(url: str, permitir_privadas: bool) -> bool:
    return await motivo_destino_prohibido(url, permitir_privadas) is None
