**Estructura de la carpeta "agentic_os_plantilla"**

La carpeta "agentic_os_plantilla" contiene los siguientes archivos y subcarpetas:

* `.claude`: carpeta principal del sistema operativo personal
* `agents`: subcarpeta con agentes (especialistas) del sistema
	+ `analista-financiero.md`
	+ `arquitecto-os.md`
	+ `asistente-agenda.md`
	+ `coach-carrera.md`
	+ `investigador.md`
	+ `orquestador.md`
	+ `tutor-estudios.md`
* `settings.json`: archivo de configuración del sistema
* `skills`: subcarpeta con skills (rutinas) del sistema
	+ `briefing`
	+ `cierre-semanal`
	+ `procesar-inbox`
* `.gitattributes`
* `.gitignore`
* `.mcp.json`
* `CLAUDE.md`: archivo principal del sistema operativo personal
* `Inicio.md`: archivo de inicio del sistema operativo personal
* `README.md`: archivo de lectura de la carpeta
* `RESPALDO_GITHUB.md`: archivo de respaldo de la carpeta en GitHub
* `SKILLS_EXTERNAS.md`: archivo con skills de diseño de terceros
* `areas`: subcarpeta con áreas del sistema
	+ `estudios`
	+ `personal`
	+ `trabajo`
* `diario`: subcarpeta con el diario del sistema
	+ `_plantilla.md`
* `inbox`: subcarpeta con la caja de ideas del sistema
	+ `ideas.md`
* `iniciar_dashboard.bat`: archivo de inicio del dashboard del sistema
* `instalar.bat`: archivo de instalación del sistema
* `os_map.json`: archivo de mapa del sistema
* `personas`: subcarpeta con personas del sistema
	+ `_plantilla_persona.md`

**Fragmentos relevantes del contenido**

* El sistema operativo personal se construye sobre Claude Code y requiere una cuenta de Claude.
* El sistema requiere Node.js versión LTS y Obsidian (opcional).
* El sistema tiene una estructura de áreas, proyectos y tareas.
* El sistema utiliza skills y agentes para automatizar tareas.
* El sistema tiene un dashboard visual local y una bóveda de Obsidian.
* El sistema tiene reglas de seguridad para proteger la privacidad del usuario.

**Reglas de seguridad**

* Nunca envíes correos, publiques contenido ni aceptes invitaciones sin confirmación explícita del usuario.
* No guardes contraseñas, claves, números de cuenta ni documentos de identidad en ningún archivo del sistema.
* No borres archivos. Si algo sobra, muévelo a `_papelera/`.

**Cómo escribirle (obligatorio)**

* Escribe en idioma salvo que la tarea pida otro idioma.
* Tono profesional pero conversacional, con frases simples aun en temas técnicos.
* Si el usuario no programa, explica los pasos técnicos en lenguaje sencillo y da los comandos exactos.
* Une las ideas con palabras conectoras (además, por eso, sin embargo, así que).
* Mantén un tono alentador y con visión de futuro.
* {{OTRAS_PREFERENCIAS_DE_ESTILO}}

---
*Documentación generada automáticamente con RAG (ChromaDB + llama3.2). Regenerar con `python _rag/rag.py document agentic_os_plantilla`.*
