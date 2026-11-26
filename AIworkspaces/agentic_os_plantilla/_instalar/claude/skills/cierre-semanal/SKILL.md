---
name: cierre-semanal
description: Cierre y planificación semanal. Úsalo cuando el usuario diga 'cierre semanal', 'revisión de la semana' o los domingos.
---

# Cierre semanal

1. Lee los diarios de los últimos 7 días en `diario/`.
2. Recorre el `pendientes.md` de cada área: marca con `[x]` lo que los diarios muestran como hecho y pregunta por lo dudoso.
3. Escribe `diario/semana_<AAAA>-W<nn>.md` con: logros por área, lo que se atrasó y por qué, y los 3 objetivos de la próxima semana.
4. Opcional: genera `os_export.json` en la raíz para que otra app pueda leer los pendientes, con este formato:
   `{"semana": "...", "areas": [{"id": "...", "pendientes": [{"texto": "...", "hecho": false}]}]}`
5. Si Calendar está activo, propón bloques de tiempo para los objetivos (sin crear eventos hasta que el usuario confirme).