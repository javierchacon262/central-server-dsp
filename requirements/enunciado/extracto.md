# Enunciado: extracto de lo que toca al servidor central

Extracto literal del enunciado «Proyecto final: chat distribuido entre grupos»
(Sistemas Distribuidos, Escuela de Ingeniería de Sistemas e Informática, UIS). Se copian
solo las secciones que definen el papel del servidor central: la arquitectura (2), los
requisitos que el central tiene que hacer posibles (3), el resumen del protocolo (4) y la
sesión de interoperabilidad (7). Las figuras se describen en una línea.

La transcripción completa está en el repositorio del grupo
[`Maria-Fernanda-Ruiz/Chat-distribuido`](https://github.com/Maria-Fernanda-Ruiz/Chat-distribuido/blob/main/requirements/enunciado/enunciado.md).
Este repositorio es el que publica «la especificación completa […] en formato OpenAPI,
junto con ejemplos JSON y el script de conformidad» que menciona la sección 4
([D01](../../README.md#log-de-decisiones)).

## 2. Descripción general del sistema

El sistema tiene forma de estrella: un servidor central que opera el profesor y, a su
alrededor, un servidor por cada grupo. Los servidores de grupo no se hablan directamente
entre sí; todo mensaje pasa por el servidor central.

> *Figura 1. Arquitectura del sistema:* el servidor central (registro de servidores,
> historial de `#general`, reenvío a todos los registrados, heartbeat hacia los grupos)
> en el centro y g1–g4 alrededor, cada uno con servidor + almacenamiento en un
> `docker compose`. Grupo → central: `POST /messages`; central → grupo:
> `POST /fed/messages`. La API cliente–servidor es libre; la API con el central la fija
> la especificación.

- **Servidor central.** Lo opera el profesor. Lleva el registro de los servidores
  conectados, guarda el historial de la sala global `#general` y reenvía cada mensaje a
  todos los servidores registrados.
- **Servidor de grupo.** Cada grupo opera un servidor identificado por un nombre corto
  (`g1`, `g2`, …), con sus propios usuarios, que se escriben `usuario@gN`, por ejemplo
  `ana@g3`.
- **Sala global.** Hay una sola sala, `#general`, compartida por todo el curso. No hay
  salas propias de cada grupo.
- **Clientes.** Cada grupo entrega un cliente sencillo (línea de comandos o página web
  mínima) que habla únicamente con su propio servidor. La API entre el cliente y el
  servidor es libre; la API con el servidor central no.

Ejemplo de recorrido: `ana@g3` escribe en `#general`. Su servidor `g3` envía el mensaje
al servidor central, que lo guarda en el historial y lo reenvía a `g1`, `g2` y `g4`.
Cada servidor lo entrega a sus clientes.

> *Figura 2. Recorrido de un mensaje:* 1) el cliente de ana envía a g3; 2) g3 hace
> `POST /messages` con id nuevo y lamport = 42; 3) el central lo guarda en el historial
> (descarta si el id ya existe); 4) lo reenvía con el mismo id a g1, g2 y g4; 5) cada uno
> ajusta su reloj a max(local, 42) + 1 y lo entrega a sus clientes. El central reenvía a
> todos los registrados excepto al de origen.

## 3. Requisitos del mínimo común

Todos los grupos deben cumplir estos requisitos. Son la condición para participar en la
sesión de interoperabilidad.

1. **Despliegue en contenedores.** El sistema completo (servidor, almacenamiento y
   cualquier servicio auxiliar) se levanta con `docker compose up` en un equipo limpio.
   La configuración (nombre del grupo, URL pública, URL del servidor central) se pasa por
   variables de entorno.
2. **Persistencia.** Usuarios e historial sobreviven a `docker compose restart`. Puede
   usarse SQLite en un volumen, Redis con persistencia o PostgreSQL.
3. **Usuarios locales.** Crear usuarios del grupo y permitirles enviar y leer mensajes de
   `#general`.
4. **Registro.** Al arrancar, el servidor se registra en el servidor central y renueva su
   registro periódicamente. La URL del servidor central se lee de la configuración, nunca
   está escrita en el código.
5. **Envío y recepción.** Enviar al servidor central los mensajes de sus usuarios y
   recibir los que el servidor central reenvía, según la sección 4.
6. **Entrega al menos una vez.** Un mensaje que no pudo entregarse se reintenta con espera
   exponencial (backoff). El servidor descarta los duplicados por `id`, de modo que
   reintentar nunca produce mensajes repetidos en pantalla.
7. **Orden lógico.** Cada mensaje lleva una marca de reloj de Lamport. El servidor
   mantiene su reloj según las reglas vistas en clase y el historial se muestra ordenado
   por `(lamport, origin)`.
8. **Detección de fallos.** El servidor consulta `GET /health` del servidor central. Si no
   responde tras un número configurable de intentos, lo marca como caído, guarda los
   mensajes pendientes y los envía cuando vuelve.
9. **Recuperación de historial.** Al arrancar, o al volver de una caída, el servidor pide
   al servidor central lo que se perdió con `GET /history?since={lamport}`.
10. **Cliente.** Un cliente sencillo para enviar y leer mensajes, que distinga
    visualmente a los usuarios de otros grupos.
11. **Registro de eventos.** Logs legibles de lo que envía, recibe, reintenta y descarta
    el servidor. Son la base del experimento y de la demo.

> *Figura 3. Entrega al menos una vez:* el intento 1 (id = 6f1c…) se pierde; tras 1 s, el
> intento 2 (mismo id) llega y el central lo guarda, pero el 200 OK se pierde; tras 2 s,
> el intento 3 (mismo id) llega, el central ve que ya lo tiene, lo descarta y responde
> 200 sin efecto. El emisor no puede distinguir «no llegó» de «llegó y se perdió la
> respuesta»: por eso el receptor debe ser idempotente.

## 4. Protocolo (resumen)

La especificación completa se publica aparte en formato OpenAPI, junto con ejemplos JSON
y el script de conformidad. Esta sección resume lo esencial; ante cualquier diferencia,
manda la especificación. Todo el tráfico es HTTP con cuerpos JSON.

### Endpoints del servidor central (los llama cada servidor de grupo)

| Método y ruta | Propósito |
|---|---|
| `POST /register` | Registrar o renovar `{"server": "g3", "url": "http://…"}` |
| `POST /messages` | Entregar un mensaje de un usuario del grupo para la sala global |
| `GET /history?since={lamport}` | Pedir los mensajes posteriores a una marca de Lamport |
| `GET /health` | Heartbeat del servidor central |

### Endpoints de cada servidor de grupo (los llama el servidor central)

| Método y ruta | Propósito |
|---|---|
| `GET /fed/health` | Heartbeat: responde con el nombre del servidor y su reloj de Lamport actual |
| `POST /fed/messages` | Recibir un mensaje reenviado por el servidor central |

### Formato de mensaje

```json
{
  "id": "6f1c2a9e-4b7d-4f0e-9a51-2c8e7d3b1f44",
  "from": "ana@g3",
  "origin": "g3",
  "lamport": 42,
  "sent_at": "2026-11-10T14:03:22Z",
  "body": "¿Ya subieron el compose?"
}
```

### Reglas de comportamiento

- `id` es un UUID generado por el servidor de origen y nunca cambia, ni siquiera al
  reenviar. Es la clave de deduplicación.
- Recibir un mensaje con un `id` ya conocido responde `200` sin efectos: la operación es
  idempotente.
- El servidor central reenvía cada mensaje a todos los servidores registrados, excepto al
  de origen.
- Antes de enviar, el servidor de grupo incrementa su reloj. Al recibir, toma
  `max(local, recibido) + 1`.
- `sent_at` es informativo: el reloj físico de cada máquina es distinto y nunca se usa
  para ordenar.
- Respuestas `5xx` o sin respuesta se reintentan; respuestas `4xx` no se reintentan y se
  registran en el log.
- Los campos desconocidos se ignoran sin error.

## 7. Sesión de interoperabilidad

En una sesión de clase todos los servidores del curso se conectan a la misma red y se
registran en el servidor central. Es la prueba de que el sistema funciona como un todo y
no solo dentro de cada grupo.

Durante la sesión se realizan, como mínimo, estas pruebas:

- **Conversación global.** Al menos un usuario de cada grupo escribe en `#general` y todos
  ven los mensajes de todos, en el mismo orden.
- **Caída y recuperación.** Por turnos, un grupo apaga su servidor mientras los demás
  siguen escribiendo; al volver, debe recuperar lo que se perdió sin mensajes duplicados.

Cada grupo lleva una bitácora de la sesión: qué funcionó, qué falló y por qué. Una
incompatibilidad encontrada y bien explicada vale tanto como una prueba que pasó sin
problemas; puede ir al póster como hallazgo.

Si la red de la sala no permite que el servidor central se conecte a los servidores de
los grupos, se usará el modo alternativo que define la especificación. En ese caso el
profesor avisa antes de la sesión.
