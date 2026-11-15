# Registro de cambios de la especificación

Versionado semántico:

- **Mayor**: algo deja de funcionar para un grupo que cumplía la versión anterior.
- **Menor**: se agrega algo que se puede ignorar.
- **Parche**: aclaraciones sin cambio de comportamiento.

Cada versión se anuncia en el foro a todos los grupos a la vez (D19).

## 1.0.0 · 2026-11-15

Primera versión publicada. Parte de la sección 4 del enunciado (D01), con estas
precisiones y extensiones:

- **Recepción en dos modos** (D11): campo opcional `mode` en `POST /register`.
  - `push`, el valor por defecto, es la sección 4: el central llama a
    `POST /fed/messages`.
  - En `pull`, el grupo consulta `GET /history?after_seq=N`.
- **`seq`** (D05, D14): número de llegada de cada mensaje al central. Va en las
  respuestas de `/messages` y `/history` y en lo que el central reenvía en push. Nunca se
  reutiliza.
- **`GET /history`** (D13, D14):
  - `since` es inclusivo (`lamport ≥ since`);
  - la respuesta es una lista JSON;
  - `after_seq` y `limit` son parámetros nuevos, y `server` es opcional.
- **Validación** (D12): `POST /messages` exige `id`, `from`, `origin` y `lamport` (entero
  de 0 a 2⁵³ − 1). Lo inválido responde `400` con `{"error", "detail"}`. No exige UUID
  ni registro previo.
- **Registro** (D16): no vence. Volver a registrarse actualiza la URL y el modo.
- **Respuestas definidas**:
  - `POST /register` responde `{"server", "url", "mode", "new"}`;
  - `POST /messages` responde `{"id", "seq", "duplicate"}`;
  - `GET /health` responde `{"status", "spec_version", "last_seq"}`.
- **Observación y administración** (D17): `GET /servers`, el panel en `GET /` y las rutas
  `/admin/…` con token.
