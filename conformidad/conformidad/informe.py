"""Informe de texto plano a partir de los resultados (CS-004, A4).

Sin colores ni caracteres de control: el informe es para subirlo al repositorio del
grupo y leerlo en un PR.
"""

from __future__ import annotations

from . import VERSION_ESPECIFICACION, VERSION_SCRIPT
from .casos import ETIQUETAS, FALLO, NO_EVALUADO, OBLIGATORIO, PASO, Contexto, Resultado, ahora_utc

MAX_CUERPO = 300
ANCHO = 78


def recortar(texto: str | None, maximo: int = MAX_CUERPO) -> str:
    """Una sola línea, recortada a `maximo` caracteres."""
    if texto is None:
        return ""
    plano = " ".join(texto.split())
    if len(plano) <= maximo:
        return plano
    return f"{plano[:maximo]}... (recortado; {len(plano)} caracteres en total)"


def codigo_salida(resultados: list[Resultado], ctx: Contexto) -> int:
    """0 si pasan todos los obligatorios, 1 si falla alguno y 2 si el grupo no respondió.

    Una advertencia nunca cambia el código (salvaguarda 3): un caso obligatorio que
    queda como advertencia cuenta como aprobado.
    """
    if ctx.sin_respuesta:
        return 2
    for r in resultados:
        if r.severidad == OBLIGATORIO and r.estado in (FALLO, NO_EVALUADO):
            return 1
    return 0


def _bloque(r: Resultado) -> list[str]:
    lineas = [f"Caso {r.numero} - {r.nombre} [{r.severidad}]"]
    if r.enviado:
        lineas.append(f"  Enviado:   {r.enviado}")
    if r.esperado:
        lineas.append(f"  Esperado:  {r.esperado}")
    if r.codigo_http is not None:
        lineas.append(f"  Respuesta: {r.codigo_http} en {r.ms} ms")
        cuerpo = recortar(r.cuerpo)
        lineas.append(f"  Cuerpo:    {cuerpo if cuerpo else '(vacío)'}")
    elif r.cuerpo:
        lineas.append(f"  Respuesta: {recortar(r.cuerpo)}")
    lineas.append(f"  Resultado: {ETIQUETAS[r.estado]}: {r.detalle}")
    return lineas


def formatear(resultados: list[Resultado], ctx: Contexto, fecha: str | None = None) -> str:
    fecha = fecha or ahora_utc()
    codigo = codigo_salida(resultados, ctx)
    linea = "=" * ANCHO
    lineas = [
        linea,
        "Informe de conformidad - parte automática",
        "Servidor central de Sistemas Distribuidos (UIS)",
        linea,
        f"URL probada:              {ctx.url}",
        f"Servidor (server):        {ctx.server or '(no informado)'}",
        f"Fecha (UTC):              {fecha}",
        f"Versión especificación:   {VERSION_ESPECIFICACION}",
        f"Versión del script:       {VERSION_SCRIPT}",
        f"Tiempo de espera:         {ctx.timeout_s:g} s",
        "",
    ]
    for r in resultados:
        lineas.extend(_bloque(r))
        lineas.append("")

    conteo = {estado: 0 for estado in ETIQUETAS}
    for r in resultados:
        conteo[r.estado] += 1
    obligatorios_fallidos = [
        str(r.numero) for r in resultados if r.severidad == OBLIGATORIO and r.estado in (FALLO, NO_EVALUADO)
    ]
    advertencias = [str(r.numero) for r in resultados if r.estado not in (PASO, FALLO, NO_EVALUADO)]

    if codigo == 0:
        veredicto = "CONFORME: pasan todos los casos obligatorios"
    elif codigo == 1:
        veredicto = f"NO CONFORME: fallan los casos obligatorios {', '.join(obligatorios_fallidos)}"
    else:
        veredicto = "SIN RESPUESTA: el servidor no respondió al caso 1"

    lineas += [
        linea,
        "Resumen",
        linea,
        f"Casos ejecutados:         {len(resultados)} de 9",
        f"Pasan:                    {conteo[PASO]}",
        f"Fallan:                   {conteo[FALLO]}",
        f"Advertencias:             {conteo['advertencia']}"
        + (f" (casos {', '.join(advertencias)})" if advertencias else ""),
        f"No evaluados:             {conteo[NO_EVALUADO]}",
        f"Veredicto:                {veredicto}",
        f"Código de salida:         {codigo}",
        "",
        "Las advertencias no cambian el código de salida: solo deciden los casos",
        "obligatorios. Los mensajes de prueba llevan origin \"conformidad\".",
    ]
    return "\n".join(lineas) + "\n"
