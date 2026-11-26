# Agentic OS

Un sistema operativo personal sobre **Claude Code**: una carpeta que organiza tu vida por áreas, con rutinas (skills), especialistas (subagentes), conexión a tu correo y calendario, un dashboard visual local y una bóveda de Obsidian. Todo vive en tu ordenador, en archivos de texto que puedes leer y editar.

Esta es una **plantilla limpia**: no trae datos de nadie. Las áreas, el proyecto y las tareas que verás son de ejemplo.

## Qué necesitas
* **Claude Code** (extensión de VS Code, app de escritorio de Claude o terminal) con una cuenta de Claude.
* **Node.js** versión LTS (https://nodejs.org) para el dashboard. No necesita instalar paquetes.
* **Obsidian** (https://obsidian.md), opcional, para ver las notas y el grafo.
* Opcional: conectores de Gmail y Google Calendar activados en tu cuenta de claude.ai.

## Cómo empezar (10 minutos)
1. Descomprime la carpeta donde quieras (por ejemplo en Documentos) y cámbiale el nombre si quieres.
2. Doble clic en `instalar.bat` (Windows). Copia los skills y agentes a `.claude`. Solo hace falta una vez. En Mac o Linux copia a mano `_instalar/claude` en `.claude`.
3. Abre la carpeta en VS Code o en Claude Code y escribe: **"ayúdame a personalizar el kernel"**. Claude te preguntará tu nombre, tu foco y tu forma de trabajar, y rellenará los `{{...}}` de `CLAUDE.md`.
4. Cambia las áreas de ejemplo (`areas/trabajo`, `areas/estudios`, `areas/personal`) por las tuyas, o créalas desde el dashboard.
5. Escribe **briefing** y Claude arranca tu día con agenda, correos y focos.

## Qué hay en cada carpeta
| Carpeta o archivo | Para qué sirve |
|---|---|
| `CLAUDE.md` | El kernel: quién eres, cómo quieres que te escriban y qué área atiende cada tema |
| `areas/` | Una carpeta por frente de tu vida, con su contexto (`CLAUDE.md`), sus `pendientes.md` y su nota para Obsidian |
| `diario/` | Un archivo por día con foco, decisiones y lo que queda pendiente |
| `inbox/` | Captura rápida de ideas sueltas |
| `personas/` | Una nota por persona importante (hay plantilla) |
| `.claude/skills/` | Rutinas que invocas por nombre |
| `.claude/agents/` | Especialistas en los que Claude delega |
| `.claude/settings.json` | Permisos de Claude Code y carpetas externas a las que puede entrar |
| `.mcp.json` | Conectores MCP locales o remotos |
| `os_map.json` | El mapa de qué se conecta con qué (lo usa el dashboard) |
| `dashboard/` | La app visual local (Node.js, sin dependencias) |
| `_instalar/` | Copia de seguridad de skills y agentes que usa el instalador |
| `_papelera/` | Lo que se quita, por si quieres recuperarlo (nunca se borra nada) |

## Skills incluidos
| Di esto | Qué pasa |
|---|---|
| briefing | Plan del día con agenda, correos y 3 focos |
| cierre semanal | Revisión de la semana, pendientes al día y objetivos de la siguiente |
| procesa el inbox | Ordena tus ideas sueltas en su área |

## Subagentes incluidos
`orquestador` (reparte el trabajo entre los demás), `arquitecto-os` (mantiene el sistema), `asistente-agenda`, `investigador`, `analista-financiero`, `coach-carrera` y `tutor-estudios`. Ajusta o crea los tuyos según tus áreas.

## Dashboard
Doble clic en `iniciar_dashboard.bat` (o `node dashboard/server.js`). Se abre `http://localhost:4747` con el mapa de tu OS: áreas, proyectos, skills, agentes y conectores, y cómo se conectan. Desde ahí puedes crear áreas, skills, agentes y conectores, editar instrucciones, marcar pendientes y quitar piezas (van a `_papelera/`).

**Importante:** deja abierta la ventana negra mientras uses el dashboard. Si la cierras, la página se sigue viendo pero no puede guardar.

Los proyectos aparecen solos: cualquier nota dentro de `areas/` con `tipo: proyecto` se dibuja unida a su área. Mira `areas/estudios/Proyecto de ejemplo.md`.

## Obsidian
1. En Obsidian elige **Abrir carpeta como bóveda** con esta carpeta.
2. Abre `Inicio.md`: es tu portada.
3. En Ajustes, Plugins comunitarios, activa **Dataview** (ya viene incluido) para ver los tableros de áreas, proyectos y tareas.
4. Abre la vista de grafo: áreas, proyectos y personas salen en colores distintos.

## Respaldo y privacidad
* Sigue `RESPALDO_GITHUB.md` para guardar tu OS en un repositorio **privado**.
* Nunca guardes contraseñas, claves, números de cuenta ni documentos de identidad en esta carpeta.
* Por defecto Claude no envía correos ni crea eventos sin tu confirmación: deja borradores.

## Ampliaciones
`SKILLS_EXTERNAS.md` lista skills de diseño de terceros que puedes añadir si vas a crear webs o apps.
