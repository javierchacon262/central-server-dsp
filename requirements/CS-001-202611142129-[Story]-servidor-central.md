# CS-001 · Historia: servidor central del chat distribuido

| Campo | Valor |
|---|---|
| ID | CS-001 |
| Tipo | Historia (paso 1 de SPDD) |
| Estado | Rondas 1 y 2 de decisiones cerradas (D01–D22); pendientes P12 y P13 en el [README](../README.md#decisiones-pendientes) |
| Fecha | 2026-11-14 |
| Fuente | [Extracto del enunciado](enunciado/extracto.md), secciones 2, 3, 4 y 7 |
| Responsable | Javier Chacón, auxiliar del proyecto con aval del profesor |

## Problema

El enunciado define la arquitectura en estrella y resume el protocolo, pero el servidor
central y la especificación completa quedaron por construir. El profesor delegó ese
trabajo en un auxiliar del curso, con criterio libre de diseño. Hay tres restricciones:

1. **Los grupos ya programan sobre la sección 4.** El central parte de ese protocolo y
   lo extiende sin romperlo ([D01](../README.md#log-de-decisiones)).
2. **Los grupos están detrás de NAT.** El central corre en la nube toda la semana y
   también en la sesión (D10), y los grupos corren en sus portátiles, a los que el
   central no puede llamar. Por eso hay dos formas de recibir: *pull* (el grupo consulta
   con un cursor) y *push* (el central llama a `POST /fed/messages` en la URL de un
   túnel), según D05 y D11.
3. **Los grupos necesitan saber si cumplen antes del 19 de noviembre.** El script de
   conformidad es la prueba objetiva, y el mínimo común, que vale el 40 % de la nota, se
   verifica con él (D07).

## Actores

| Actor | Qué hace con el central |
|---|---|
| Servidor de grupo (`gN`) | Se registra, envía los mensajes de sus usuarios y recibe los de los demás (push o pull) |
| Estudiantes de cada grupo | Leen la especificación y corren el script de conformidad contra su servidor |
| Auxiliar | Opera el central, publica la especificación y responde dudas en el foro |
| Profesor | Usa el script de conformidad y la sesión de interoperabilidad para evaluar |

## Historias

### HU1 · Levantar el central con un comando

Como auxiliar quiero levantar el central con `docker compose up`, igual en la VM que en
mi portátil, para que lo que se prueba en la semana sea lo mismo que corre en la sesión.

- La configuración va por variables de entorno; nada queda escrito en el código.
- El historial y el registro de servidores sobreviven a `docker compose restart`
  (SQLite en un volumen, D03).
- En la VM, el central responde por HTTPS con un certificado válido (Caddy, D04) en
  `https://dsp.cshire.io`, sobre una VM gratuita de Oracle Cloud (D08, D09).

### HU2 · Registro de servidores

Como servidor de grupo quiero registrarme y renovar mi registro, para que el central me
haga llegar los mensajes (requisito 4).

- `POST /register` con `{"server": "gN", "url": "http://…"}` registra o renueva. Si el
  nombre ya existe, se actualiza su `url`.
- El acceso es abierto: cualquier nombre se puede registrar (D06).
- El registro no vence; volver a registrarse actualiza la URL y el modo (D16).
- Un campo opcional `mode` (`push` por defecto, o `pull`) dice cómo recibe (D11).

### HU3 · Recibir los mensajes de los grupos

Como servidor de grupo quiero entregar al central los mensajes de mis usuarios, con la
garantía de que reintentar nunca los duplica (requisitos 5 y 6, figura 3).

- `POST /messages` con el formato de la sección 4.
- Un `id` nuevo se guarda, recibe el siguiente número de secuencia (`seq`, D05) y se
  reenvía (HU4).
- Un `id` ya conocido responde `200` sin efectos: es idempotente.
- Un mensaje mal formado responde `400` con `{"error", "detail"}`, que el grupo no
  reintenta. Solo se exigen `id`, `from`, `origin` y `lamport`, y un `body` de hasta
  10 000 caracteres (D12).
- Los campos desconocidos se ignoran sin error.

### HU4 · Reenviar a todos los registrados (push)

Como servidor de grupo alcanzable quiero recibir en `POST /fed/messages` los mensajes de
los demás, con el mismo `id` de origen.

- Se reenvía a todos los registrados en push, excepto al de origen.
- La entrega es al menos una vez: si un grupo no responde o responde `5xx`, se reintenta
  con backoff, sin frenar a los demás grupos.
- Cada grupo en push tiene un cursor de entrega en SQLite. Un grupo caído se pausa y,
  al volver, retoma desde su cursor (D15). Sus mensajes también siguen disponibles por
  historial (HU5) y por cursor (HU6).

### HU5 · Historial por marca de Lamport

Como servidor de grupo quiero pedir lo que me perdí con `GET /history?since={lamport}`,
tal como lo describe la sección 4 (requisito 9).

- Devuelve una lista JSON con los mensajes de `lamport ≥ since` (inclusivo, D13),
  ordenados por `(lamport, origin)`, cada uno con su `seq` (D14).
- La especificación advierte que `since={lamport}` puede dejar por fuera los mensajes
  concurrentes con una marca menor, y recomienda el cursor de HU6.

### HU6 · Modo alternativo: consulta con cursor de secuencia

Como servidor de grupo detrás de NAT quiero recibir los mensajes aunque el central no
pueda llamarme (sección 7, «modo alternativo»; D05).

- El central numera con `seq` cada mensaje nuevo, en orden de llegada y sin huecos.
- El grupo consulta cada 1 o 2 s pidiendo lo posterior a su último `seq`, y guarda ese
  número para no pedir dos veces lo mismo.
- `seq` es un campo extra: el grupo que no lo usa lo ignora, y el protocolo de la sección
  4 sigue valiendo (D01).
- A diferencia de `since={lamport}`, el cursor no pierde los mensajes concurrentes que
  llegan tarde con una marca menor.
- El parámetro es `GET /history?after_seq={seq}`, con `limit` para paginar (D14).

### HU7 · Heartbeat en las dos direcciones

Como servidor de grupo quiero saber si el central está vivo, y como auxiliar quiero
saber qué grupos están vivos (requisito 8).

- `GET /health` del central responde rápido y sin tocar la red.
- El central consulta `GET /fed/health` de cada servidor en push y lo marca caído
  después de 3 fallos seguidos, consultando cada 5 s; cuando vuelve a responder, lo
  marca vivo (D15). Un grupo en pull no recibe heartbeat: su señal de vida es la última
  consulta (D16).

### HU8 · Especificación publicada

Como estudiante quiero una especificación completa y sin ambigüedades, para programar sin
adivinar (sección 4).

- OpenAPI 3.1 con cada ruta, cada código de respuesta y cada campo, en este repositorio.
- Un ejemplo JSON por cada petición y cada respuesta.
- Versionada: cada cambio queda en un registro de cambios y se anuncia a todos los
  grupos a la vez (D19).
- La versión 1 se publica el domingo 15 (D18); los grupos la necesitan para la etapa
  3, el martes 17.

### HU9 · Script de conformidad

Como estudiante quiero correr un script que me diga si mi servidor cumple el protocolo,
para corregir antes de la sesión (secciones 6 y 9; D07).

- **Parte automática:** llama a `GET /fed/health` y `POST /fed/messages` del grupo con:
  - un mensaje nuevo;
  - un duplicado;
  - campos desconocidos;
  - un salto de Lamport, y verifica con `/fed/health` que el reloj quedó en
    `max(local, recibido) + 1`.
- **Parte guiada:** levanta un central de prueba y le pide a la persona «envíe un mensaje
  ahora». Con eso verifica:
  - el registro;
  - el `id` UUID;
  - que `lamport` sube;
  - que tras un `5xx` o un timeout inyectado se reintenta con el mismo `id`;
  - que tras un `4xx` no se reintenta.
- Corre en Docker, sin instalar nada.
- Deja un informe de texto que el grupo sube a su repositorio («salida del script de
  conformidad», sección 8).

### HU10 · Logs de eventos

Como auxiliar quiero ver en los logs todo lo que pasa en el central, para diagnosticar
problemas de interoperabilidad y responder dudas con evidencia.

- Una línea legible por evento con el `id`, el `lamport`, el `origin` y el destino. Los
  eventos son: registro, mensaje recibido, duplicado, reenvío, reintento, grupo caído y
  grupo que volvió.

### HU11 · Sesión de interoperabilidad

Como curso queremos que la sesión del jueves 19 funcione con todos los grupos (sección 7).

- El central corre en la nube; el portátil del auxiliar es el respaldo si falla
  internet en la sala (D10).
- Conversación global: todos ven los mensajes de todos, en el mismo orden.
- Caída y recuperación: un grupo se apaga mientras los demás escriben y, al volver,
  recupera lo perdido sin duplicados (con el historial o con el cursor).
- Un grupo al que el central no puede llamar funciona en pull (D11).

### HU12 · Observar el sistema durante la sesión

Como auxiliar y profesor queremos ver de un vistazo qué grupos están registrados, cuáles
están vivos y qué pasa en `#general`. Panel de solo lectura en `/` y `GET /servers`;
rutas `/admin/…` con token del auxiliar (D17).

## Definición de terminado

1. `docker compose up` levanta el central en un equipo limpio, y lo mismo corre en la VM
   con HTTPS en `https://dsp.cshire.io`.
2. Especificación OpenAPI y ejemplos JSON publicados, con registro de cambios.
3. Script de conformidad, con parte automática y parte guiada, corriendo en Docker.
4. El central de la VM disponible el domingo 15, antes de la etapa 3 de los grupos
   (D18).
5. Logs de eventos que permiten reconstruir lo que pasó con cualquier `id`.
6. Sesión del 19: los grupos conversan en `#general` en push o en pull.
