---
name: procesar-inbox
description: Ordena las ideas sueltas del inbox en su área correspondiente. Úsalo cuando el usuario diga 'procesa el inbox' o 'ordena mis ideas'.
---

# Procesar inbox

1. Lee `inbox/ideas.md`.
2. Para cada idea decide el área destino según la tabla del CLAUDE.md principal.
3. Si es una tarea, agrégala al `pendientes.md` del área. Si es una idea de proyecto, créale una nota con `tipo: proyecto` en la carpeta de su área.
4. Muestra al usuario la clasificación antes de mover nada y, cuando confirme, deja el inbox limpio (las ideas procesadas pasan a `inbox/procesado_<fecha>.md`).