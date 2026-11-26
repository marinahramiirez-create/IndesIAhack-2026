---
tipo: inicio
tags: [inicio]
---

# Agentic OS

Punto de entrada de tu bóveda. Desde aquí llegas a todo.

## Áreas
* [[Trabajo]]
* [[Estudios]]
* [[Personal]]

## Personas
* Usa `personas/_plantilla_persona.md` para crear la primera.

## Día a día
* Diario de hoy: carpeta `diario/`
* Ideas sueltas: [[inbox/ideas|Inbox]]

## Tablero (requiere el plugin Dataview)

```dataview
TABLE estado, prioridad
FROM #area
SORT prioridad ASC
```

```dataview
TABLE estado, area
FROM #proyecto
```

```dataview
TASK
FROM "areas"
WHERE !completed
GROUP BY file.folder
```
