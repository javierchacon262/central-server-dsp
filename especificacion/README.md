# Especificación del protocolo · versión 1.0.0

Esta carpeta es la **especificación completa** que anuncia la sección 4 del enunciado.
Ante cualquier diferencia con ese resumen, manda esta especificación. Todo lo que agrega
se puede ignorar: un servidor que cumple la sección 4 al pie de la letra sigue
funcionando (D01).

| Archivo | Contenido |
|---|---|
| [`openapi-central.yaml`](openapi-central.yaml) | Rutas del servidor central, que llama cada grupo |
| [`openapi-grupo.yaml`](openapi-grupo.yaml) | Rutas que cada grupo implementa (`/fed/*`) y que llama el central |
| [`ejemplos/`](ejemplos/) | Un JSON por cada petición y cada respuesta |
| [`CHANGELOG.md`](CHANGELOG.md) | Cambios entre versiones |

Los YAML se pueden abrir en <https://editor.swagger.io> (File → Import URL, con la URL
«Raw» del archivo en GitHub).

**Servidor central:** `https://dsp.cshire.io`, toda la semana y también en la sesión del
jueves 19 (D10). El estado de los servidores y la sala `#general` se ven en
<https://dsp.cshire.io/>.

## Qué precisa y qué agrega respecto a la sección 4

| Tema | Sección 4 | Esta especificación |
|---|---|---|
| Cómo recibe un grupo | El central llama a `POST /fed/messages` | Igual (push), o bien el grupo consulta con `after_seq` (pull). Se elige con `mode` al registrarse (D11) |
| `POST /register` | `{"server", "url"}` | Más `mode` opcional: `"push"` (por defecto) o `"pull"`. El registro no vence, pero se recomienda renovarlo cada 30 s (D16) |
| `POST /messages` | Idempotente por `id` | Responde `200` `{"id", "seq", "duplicate"}`. Lo inválido responde `400` con el detalle (D12) |
| `GET /history?since=` | «Posteriores a una marca» | `lamport ≥ since` (inclusivo, D13); lista JSON, cada mensaje con `seq` (D14) |
| `GET /history?after_seq=` | — | Modo pull: mensajes con `seq` mayor, en orden de llegada al central (D14) |
| `seq` | — | Número de llegada al central, creciente y sin reutilizar. Los grupos que no lo usan lo ignoran |

## Paso a paso para un grupo

### 1. Configuración

```bash
URL_CENTRAL=https://dsp.cshire.io
```

La URL del central se lee de la configuración, nunca del código (requisito 4).

### 2. Elegir cómo recibir

Un portátil detrás de NAT no puede recibir llamadas desde internet. Hay dos caminos:

- **Pull (recomendado).** El grupo pregunta cada 1–2 s si hay mensajes nuevos. No
  necesita nada más que salida a internet.
- **Push (la sección 4 tal cual).** El grupo expone su servidor con un túnel y el central
  le entrega cada mensaje en `POST /fed/messages`. Por ejemplo:
  - `cloudflared tunnel --url http://localhost:8000` da una URL
    `https://….trycloudflare.com` que cambia en cada arranque;
  - ngrok da un dominio fijo gratuito, con cuenta.

  La URL pública del túnel es la que va en el registro.

### 3. Registrarse

```bash
# pull
curl -s -X POST https://dsp.cshire.io/register \
  -H 'Content-Type: application/json' \
  -d '{"server": "g3", "url": "http://localhost:8000", "mode": "pull"}'

# push, con la URL del túnel
curl -s -X POST https://dsp.cshire.io/register \
  -H 'Content-Type: application/json' \
  -d '{"server": "g3", "url": "https://ejemplo.trycloudflare.com"}'
```

Respuesta: `{"server": "g3", "url": "…", "mode": "pull", "new": true}`. Registrarse otra
vez con el mismo nombre actualiza la URL y el modo. En pull, la `url` es informativa.

### 4. Enviar

```bash
curl -s -X POST https://dsp.cshire.io/messages \
  -H 'Content-Type: application/json' \
  -d '{"id": "6f1c2a9e-4b7d-4f0e-9a51-2c8e7d3b1f44", "from": "ana@g3", "origin": "g3",
       "lamport": 42, "sent_at": "2026-11-10T14:03:22Z", "body": "¿Ya subieron el compose?"}'
```

- `200` `{"id": "6f1c…", "seq": 57, "duplicate": false}`: el mensaje quedó guardado.
- `200` con `"duplicate": true`: el central ya lo tenía. Es lo esperado al reintentar.
- `400` `{"error": "mensaje inválido", "detail": [{"field": "lamport", "problem": "…"}]}`:
  no se reintenta (sección 4). Hay que corregir el servidor.
- `5xx` o sin respuesta: se reintenta con el **mismo** `id` y backoff exponencial.

`lamport` es un entero JSON (`42`, no `"42"`). Se exigen `id`, `from`, `origin` y
`lamport`; `body` admite hasta 10 000 caracteres.

### 5. Recibir en pull

El grupo guarda en su base el último `seq` que procesó y pregunta por lo posterior. Un
esquema en Python con `httpx`:

```python
async def recibir_por_pull(central: str, servidor: str) -> None:
    ultimo = leer_ultimo_seq()                       # 0 la primera vez
    async with httpx.AsyncClient(base_url=central, timeout=3) as http:
        while True:
            try:
                r = await http.get("/history", params={"after_seq": ultimo, "server": servidor})
                r.raise_for_status()
                mensajes = r.json()                  # lista, en orden de seq
                for m in mensajes:
                    # la misma recepción que /fed/messages: descartar si el id ya existe;
                    # si es nuevo, reloj = max(local, m["lamport"]) + 1; guardar el mensaje
                    # y el nuevo último seq en la misma transacción
                    recibir(m)
                    ultimo = m["seq"]
                if len(mensajes) == 1000:            # página llena: pedir la siguiente ya
                    continue
            except httpx.HTTPError:
                pass                                 # el central no respondió: siguiente ciclo
            await asyncio.sleep(1.5)
```

- Los mensajes propios también llegan por esta vía; la deduplicación por `id` los
  descarta.
- El parámetro `server` es opcional. Con él, el panel muestra al grupo como activo.

### 6. Recibir en push

El central llama a `POST {url}/fed/messages` con el mensaje tal como llegó, más `seq`.
Un `2xx` cuenta como entregado. Con un `5xx` o sin respuesta en 3 s, reintenta el mismo
mensaje con backoff, sin perderlo; con un `4xx`, lo salta. También consulta
`GET {url}/fed/health` cada 5 s y espera `{"server", "lamport"}`.

### 7. Recuperar el historial

Al arrancar y al volver de una caída del central (requisito 9):

- `GET /history?since=N` devuelve los mensajes con `lamport ≥ N`, ordenados por
  `(lamport, origin)`. Como es inclusivo, pedir `since` = la última marca vista también
  trae los mensajes concurrentes con esa misma marca; los repetidos se descartan por `id`.
- En pull, `GET /history?after_seq=N` sirve también para recuperar: no pierde los
  mensajes que llegaron tarde con una marca menor.
- `limit` (hasta 1000) pagina. `since` y `after_seq` juntos responden `400`.

### 8. Detectar la caída del central

`GET /health` responde `200` `{"status": "ok", "spec_version": "1.0.0", "last_seq": 57}`.
Tras varios fallos seguidos, el grupo marca el central como caído, guarda lo pendiente y
lo envía al volver (requisito 8).

### 9. Comprobar el servidor con el script de conformidad

```bash
docker build -t conformidad-dsp \
  "https://github.com/javierchacon262/central-server-dsp.git#main:conformidad"

# Linux
docker run --rm --network host conformidad-dsp http://localhost:8000 > conformidad.txt
# Windows y macOS (Docker Desktop)
docker run --rm conformidad-dsp http://host.docker.internal:8000 > conformidad.txt
```

El script prueba `/fed/health` y `/fed/messages`:

- un mensaje nuevo;
- el ajuste del reloj de Lamport;
- un duplicado;
- campos desconocidos;
- una marca menor que el reloj;
- un mensaje sin `id`;
- el tiempo de respuesta.

Los mensajes de prueba llevan `origin` `conformidad`. El informe queda en
`conformidad.txt`, listo para subir al repositorio del grupo (sección 8 del enunciado).

## Dudas y cambios

Las dudas se resuelven en el foro del curso. Toda aclaración o cambio se publica aquí y
en el foro **a la vez para todos los grupos** (D19). Cada cambio sube la versión y queda
en el [`CHANGELOG.md`](CHANGELOG.md).
