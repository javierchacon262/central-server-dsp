# Instrucciones para agentes y personas que continúan este proyecto

Servidor central del proyecto final de Sistemas Distribuidos (UIS). Los servidores de
chat de los grupos se registran en él y conversan en la sala global `#general`. Además,
este repositorio publica la especificación del protocolo y el script de conformidad. El
diseño está a cargo del auxiliar del proyecto (Javier Chacón), con aval del profesor, y
se trabaja con **SPDD**.

## Dónde quedó el trabajo

El 2026-11-14 se creó el repositorio y se cerró la ronda 1 de decisiones (D01–D07):

- el protocolo de la sección 4 del enunciado como base;
- dos despliegues, una VM en la nube y el portátil del auxiliar en la sala;
- SPDD con los tres entregables;
- una VM con Docker y Caddy;
- el modo alternativo con cursor `seq`;
- registro abierto;
- un script de conformidad automático y guiado.

Está la historia CS-001 con HU1–HU12. **No hay especificación ni código.**

Leer en este orden:

1. [`requirements/enunciado/extracto.md`](requirements/enunciado/extracto.md): lo que el
   enunciado dice del central. La sección 4 es la base del protocolo (D01).
2. [`README.md`](README.md): estado, log de decisiones y pendientes P01–P11.
3. [`requirements/CS-001-…-[Story]-…`](requirements/): historias HU1–HU12 y criterios.
4. [`spdd/template/REASONS-canvas.md`](spdd/template/REASONS-canvas.md): la plantilla.

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

1. Cerrar los pendientes que bloquean la especificación: P03, P05 y P06, y luego P02,
   P04 y P08.
2. Escribir el análisis en `spdd/analysis/` con el contrato de cada ruta.
3. Escribir la especificación OpenAPI y los ejemplos JSON, y publicar la versión 1 (P08).
4. Canvas y código del central; luego canvas y código del script de conformidad.
5. Desplegar en la VM (P01) y ensayar la sesión con dos servidores de prueba.
