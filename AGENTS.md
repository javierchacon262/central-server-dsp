# Instrucciones para agentes y personas que continúan este proyecto

Servidor central del proyecto final de Sistemas Distribuidos (UIS). Los servidores de
chat de los grupos se registran en él y conversan en la sala global `#general`. Además,
este repositorio publica la especificación del protocolo y el script de conformidad. El
diseño está a cargo del auxiliar del proyecto (Javier Chacón), con aval del profesor, y
se trabaja con **SPDD**.

## Dónde quedó el trabajo

El 2026-11-14 se creó el repositorio y se cerró la ronda 1 de decisiones (D01–D07). El
2026-11-15 se cerró la ronda 2 (D08–D22):

- el central corre siempre en la nube, en `https://dsp.cshire.io`, sobre una VM gratuita
  de Oracle Cloud con Docker y Caddy (D08–D10);
- cada grupo elige con `mode` si recibe en pull, con el cursor `seq`, o en push, con un
  túnel (D11);
- validación de forma con `400` (D12), `since` inclusivo (D13), `/history` como lista con
  `seq` y `after_seq` (D14);
- reenvío push con un cursor de entrega por grupo (D15) y registro que no vence (D16);
- panel público y rutas `/admin/…` con token (D17);
- especificación v1, central y parte automática del script publicados el domingo 15 (D18);
- una sola aprobación del auxiliar antes del código (D22).

Están la historia CS-001 con HU1–HU12, el análisis CS-002, la especificación v1 en
[`especificacion/`](especificacion/) y los canvas CS-003 y CS-004. El auxiliar los
aprobó el 2026-11-15 con las propuestas A1–A16 (D23): ya se puede escribir el código.

Leer en este orden:

1. [`requirements/enunciado/extracto.md`](requirements/enunciado/extracto.md): lo que el
   enunciado dice del central. La sección 4 es la base del protocolo (D01).
2. [`README.md`](README.md): estado, log de decisiones y pendientes P01–P11.
3. [`requirements/CS-001-…-[Story]-…`](requirements/): historias HU1–HU12 y criterios.
4. [`spdd/analysis/CS-002-…`](spdd/analysis/): el contrato de cada ruta y el
   comportamiento del central.
5. [`especificacion/`](especificacion/): OpenAPI, ejemplos y la guía para los grupos.
6. [`spdd/prompt/`](spdd/prompt/): los canvas CS-003 (central) y CS-004 (conformidad).

## Reglas

1. **No escribir código** hasta que el canvas REASONS de esa parte esté escrito y el
   auxiliar lo haya aprobado.
2. **Las decisiones se iteran con el auxiliar; el agente no decide solo.** Cada pregunta
   se presenta con sus opciones, una de ellas marcada como recomendada, y con lo que
   cambia en cada caso. Cuando se confirma:
   - se agrega una fila al «Log de decisiones» con el siguiente ID;
   - si cierra un pendiente, el pendiente se borra y la decisión dice «cierra P0X»;
   - si modifica una decisión anterior, a esa se le agrega «Ajustada por DXX»;
   - se actualiza la sección «Estado».

   Si al escribir el análisis, la especificación o el código aparece una pregunta nueva,
   se agrega como pendiente (P12, P13, …).
3. **Primero el canvas, después el código.** Si cambia el comportamiento, se corrige el
   canvas y luego el código.
4. **Nunca se rompe la sección 4 del enunciado (D01).** Un servidor de grupo que la
   cumple al pie de la letra tiene que funcionar en push contra este central. Lo nuevo
   (el cursor `seq`, campos opcionales) se agrega de forma que se pueda ignorar.
5. **La especificación es un contrato con todo el curso.** Cada cambio después de
   publicada lleva versión, una entrada en el registro de cambios y un anuncio a todos
   los grupos a la vez (P09). Ningún grupo recibe información del protocolo antes que
   los demás.
6. **Todo corre en contenedores:** el central, el script de conformidad y las pruebas.
   La configuración va por variables de entorno.
7. Los diagramas Mermaid deben renderizar en GitHub. Hay que probarlos antes de hacer
   commit.
8. Git: una rama y un PR por cosa terminada, con Conventional Commits; nunca push
   directo a `main` (P11).
9. Idioma: español en documentos y código; campos y rutas del protocolo en inglés, como
   en la sección 4 (P10).

## Próximos pasos, en orden

1. Escribir juntos, para una sola aprobación (D22):
   - el análisis en `spdd/analysis/`, con el contrato de cada ruta;
   - la especificación OpenAPI y los ejemplos JSON;
   - los canvas del central y del script de conformidad.
2. Con la aprobación del auxiliar: código y pruebas del central.
3. Desplegar en la VM de Oracle (D08) con el dominio `dsp.cshire.io` (D09).
4. Código de la parte automática del script de conformidad.
5. Publicar la versión 1 y anunciarla en el foro a todos a la vez (D18, D19).
6. Cerrar P12 (parte guiada del script) y P13 (reinicio del historial antes de la sesión).
