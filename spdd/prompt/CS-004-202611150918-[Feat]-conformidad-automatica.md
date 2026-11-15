# CS-004 · Canvas REASONS: script de conformidad, parte automática

| Campo | Valor |
|---|---|
| ID | CS-004 |
| Historia | [CS-001](../../requirements/CS-001-202611142129-[Story]-servidor-central.md), HU9 |
| Análisis | [CS-002](../analysis/CS-002-202611150918-[Analysis]-protocolo-y-central.md), §12 |
| Especificación | [`especificacion/openapi-grupo.yaml`](../../especificacion/openapi-grupo.yaml) |
| Estado | Borrador para la aprobación única del auxiliar (D22) |
| Revisado por | — |

## R · Requirements (requisitos)

Un programa en Docker que prueba `/fed/health` y `/fed/messages` del servidor de un
grupo, sin que el grupo instale nada (D07, D18). Está terminado cuando:

1. Se construye directo desde el repositorio público, sin clonarlo:
   `docker build -t conformidad-dsp "https://github.com/javierchacon262/central-server-dsp.git#main:conformidad"`.
2. `docker run --rm --network host conformidad-dsp http://localhost:8000` ejecuta los
   9 casos de CS-002 §12 en orden. En Docker Desktop, la URL es
   `http://host.docker.internal:8000`.
3. El progreso va a la salida de error y el **informe va a la salida estándar**, así que
   `… > conformidad.txt` deja el archivo que el grupo sube a su repositorio, igual en
   Linux, macOS y Windows.
4. El informe dice, por caso:
   - qué se envió y qué se esperaba;
   - qué respondió el grupo, con código y cuerpo recortado a 300 caracteres;
   - si pasó, falló o quedó como advertencia;
   - un resumen final con el nombre del servidor, la fecha en UTC, la versión de la
     especificación y la del script.
5. Sale con `0` si pasan todos los casos obligatorios, con `1` si falla alguno y con `2`
   si la URL es inválida o el servidor no responde al primer caso.
6. Si el caso 1 no da un reloj entero, los casos que dependen del reloj (3, 5 y 7) quedan
   como «no evaluado» con el motivo, en vez de fallar en cascada.
7. Las pruebas del script pasan contra dos grupos falsos: uno que cumple todo y uno con
   errores conocidos: no actualiza el reloj, responde `500` al duplicado y tarda 4 s
   con el mensaje de campos desconocidos. El script debe detectar cada error.

## E · Entities (entidades)

- **`Resultado`** (dataclass): `numero`, `nombre`, `severidad` (`obligatorio` o
  `advertencia`), `estado` (`paso`, `fallo`, `advertencia` o `no_evaluado`), `detalle`,
  `codigo_http`, `cuerpo` y `ms`.
- **`Contexto`** (dataclass): la URL base, el cliente HTTP, el `server` y el `lamport`
  que reportó el grupo, y los `id` enviados (para repetir el duplicado).
- **Mensaje de prueba**:
  - `id`: `uuid4`;
  - `from`: `conformidad@conformidad`;
  - `origin`: `conformidad` (A12);
  - `sent_at`: la hora UTC;
  - `body`: `[conformidad] mensaje de prueba del script de conformidad; se puede ignorar`.
  - Más `seq`, para que el grupo reciba exactamente lo que recibiría del central (A10).

## A · Approach (enfoque)

1. **Cada caso es una función** `caso_N(ctx) -> Resultado`, y una lista `CASOS` fija el
   orden. Agregar un caso no toca a los demás.
2. **`httpx` síncrono, con 3 s de tiempo de espera**, el mismo del central. Una llamada
   que tarda más falla el caso 9 aunque termine bien, porque el central la habría
   reintentado.
3. **El reloj se mide con `/fed/health` antes y después de cada envío.** Las
   comparaciones de los casos 3 y 7 usan la misma regla de la sección 4:
   `max(local, recibido) + 1`. Las que dependen de que el grupo no haga nada más entre
   medio quedan como advertencia y lo explican.
4. **El informe es texto plano en español**, legible en un PR, con un bloque por caso y
   un resumen al final. Lo genera `informe.py` a partir de la lista de `Resultado`, sin
   más estado.
5. **Imagen mínima**: `python:3.13-slim`, solo `httpx`, usuario sin privilegios y
   `ENTRYPOINT ["python", "-m", "conformidad"]`, para que la URL se pase como argumento.

## S · Structure (estructura)

```text
conformidad/
├── Dockerfile               base → pruebas | script; usuario 10001
├── requirements.txt         httpx 0.28.1
├── requirements-pruebas.txt pytest 9.2.0
├── pyproject.toml
├── conformidad/
│   ├── __init__.py          VERSION_SCRIPT, VERSION_ESPECIFICACION
│   ├── __main__.py          argumentos: url, --timeout; códigos de salida 0, 1 y 2
│   ├── casos.py             Contexto, Resultado, caso_1 … caso_9, CASOS
│   └── informe.py           formatear(resultados, ctx) -> str
└── pruebas/
    ├── grupos_falsos.py     GrupoConforme y GrupoConErrores sobre httpx.MockTransport
    ├── test_casos.py        cada caso contra los dos grupos
    └── test_informe.py      formato, recorte del cuerpo y códigos de salida
```

En `docker-compose.yml` va un servicio `pruebas-conformidad` en el perfil `pruebas`.

## O · Operations (operaciones)

1. **Esqueleto e informe.** Dockerfile, `__main__.py` e `informe.py`.
   - Comprobación: una URL inválida sale con 2; un informe con resultados de ejemplo
     se lee bien.
2. **Casos 1 a 9.** `casos.py`.
   - Comprobación: `test_casos.py`. `GrupoConforme` pasa todos los casos;
     `GrupoConErrores` falla 3, 4, 6 y 9, y el informe dice por qué.
3. **Prueba real.** Contra el servidor del grupo `Chat-distribuido`, si su `/fed/*` ya
   existe, o contra un servidor mínimo de prueba.
   - Comprobación: `docker build` desde la URL del repositorio público y `docker run`
     con `--network host` producen el informe esperado.

## N · Norms (normas)

- Español en el informe, el código y los mensajes; campos y rutas del protocolo en
  inglés (D20).
- El informe nunca depende del color ni de caracteres especiales de la terminal: es para
  subirlo a un repositorio.
- Versiones exactas en los requisitos.
- Conventional Commits con alcance `conformidad` (D21).

## S · Safeguards (salvaguardas)

1. **El script nunca llama a nada distinto de la URL que se le pasa**: ni al central ni a
   internet.
2. **Nunca envía más de los mensajes de los casos**, todos marcados con `origin`
   `conformidad`, para que el grupo pueda reconocerlos y filtrarlos.
3. **Una advertencia nunca cambia el código de salida**: solo los casos obligatorios
   deciden.
4. **Nunca se cae con una respuesta inesperada** (JSON inválido, HTML, conexión cortada):
   la registra como resultado del caso y sigue.
5. **La versión de la especificación que prueba va en el informe**, para que un informe
   viejo no se confunda con uno de una versión nueva.
