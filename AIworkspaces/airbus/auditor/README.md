# Auditor Part-IS · NIMBUS (reto Airbus)

Una sola orden: entra una carpeta de PDF y sale `respuestas.csv` en el formato del reto.

**Resultado con el puntuador oficial del kit** (19 documentos con clave, sin los del núcleo, como en la evaluación final):

| F1 | Precisión | Recall | Cláusula correcta |
|---|---|---|---|
| **0,932** | 0,906 | 0,959 (164/171) | 91 % |

Por familia: registros operativos 61/61 · proveedores 18/18 · evaluaciones de riesgos 15/15 · interfaces 5/5 · auditorías 6/7 · verificación 6/7 · especificaciones 53/58.

## Cómo funciona

1. **Ingesta** (`src/ingesta.py`): cada PDF pasa a texto por página, unidades con su ID (requisitos, filas de registro, riesgos…), tablas y figuras. Los escaneados se transcriben con visión (`src/vision.py`).
2. **Referencias** (`src/referencias.py`): Part-IS (`normativa/part_is_ir.json`), STD-SEC-001 **vigente** según LISTA-DOC, y los documentos que cita cada uno.
3. **Propuestas**:
   - reglas deterministas (`src/reglas.py`);
   - reglas de registros operativos (`src/registros.py`): leen las tablas columna a columna y aplican STD-SEC-001 §10 (plazos leídos del estándar vigente);
   - agente LLM sobre el texto (`src/agente.py`);
   - visión en las páginas con figuras.
4. **Verificador por código** (`src/verificar.py`). El LLM propone, el código decide:

   | Regla | Qué comprueba |
   |---|---|
   | V1 | Formato oficial del tipo y de la cláusula |
   | V2 | La ubicación existe en el documento |
   | V3 | La cita literal aparece en el PDF |
   | V4 | El plazo recalculado con las fechas incumple de verdad (el LLM no hace cuentas) |
   | V5 | La confianza supera el umbral |

5. **Salida** (`auditar.py`):
   - Escribe `respuestas.csv`, deduplicado, tras cada documento. Si se acaba el tiempo, lo hecho ya está entregado.
   - Escribe `respuestas_traza.jsonl` con cada propuesta y, si se descartó, el motivo.

## Puesta en marcha (PowerShell, en esta carpeta)

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -r requirements.txt
copy .env.example .env      # y rellenar las claves (PDF de Teams). El .env no se sube nunca.
.\.venv\Scripts\python probar_clave.py
```

**El corpus no está en git.** Descomprime `03_corpus_trabajo_NIMBUS.zip` y `06_kit_desarrollo_equipos.zip` en la raíz del repositorio (al lado de `AIworkspaces`). Da igual si queda una carpeta o dos con el mismo nombre: el auditor busca los PDF solo. Si los tienes en otro sitio, pon la ruta en `CORPUS_NIMBUS` dentro de `.env`.

## Uso

```powershell
# 1. Auditar el corpus (≈4 min la primera vez; con caché ≈1 min). Encuentra los PDF solo.
.\.venv\Scripts\python auditar.py

# 2. Medir con el puntuador oficial (como la evaluación final)
python "..\..\..\06_kit_desarrollo_equipos\06_kit_desarrollo_equipos\puntuar.py" "..\..\..\06_kit_desarrollo_equipos\06_kit_desarrollo_equipos\clave_desarrollo.csv" salidas\respuestas.csv --sin-nucleo

# 3. Pantalla de revisión (diseño de Valentina): genera salidas\revision\index.html y lo abre
.\.venv\Scripts\python generar_revision.py
```

Ejecuta el paso 3 **cuando haya terminado** el paso 1: necesita su `salidas\respuestas.csv`.

Opciones de `auditar.py`:
- `--sin-llm`: solo reglas, sin coste;
- `--solo COD1,COD2`: audita solo esos documentos;
- `--hilos 6`: número de documentos en paralelo.

## Pantalla de revisión

`generar_revision.py` toma el diseño de `src/plantilla_revision.html` (el prototipo de Valentina) y le mete los datos reales. Genera la página `salidas/revision/index.html` y una imagen por cada página del PDF.

La página funciona sin servidor: doble clic y listo. Tiene estas pantallas:
- **Auditorías** (antes Inicio): los documentos auditados y los cargados, con filtros en una línea (Buscar, Estado,
  **Decisión** — Pendiente / Aceptado / Rechazado —, Tipo de hallazgo, Familia, Cláusula, **Prioridad**, **Antigüedad**
  — hoy · esta semana · más de 7 días · vencidos — y «Asignado»: «Míos» (decididos por ti), «Nuevos» (que aún no has
  abierto, recordado en tu navegador), «Con comentarios», **«En equipo»** (compartidos contigo o por ti, o trabajados por
  ti y al menos otra persona; enseña quién y por qué) y **«Escalados a mí»**), columnas ordenables y paginador.
  - **Prioridad** Alta / Media / Baja: se **sugiere** según los hallazgos (5 o más «No cumple» → Alta; alguno → Media;
    ninguno → Baja) y se cambia en Revisión (permiso «Cambiar la prioridad»); queda quién y cuándo. Es una columna
    ordenable.
  - **Plazo**: el común de Configuración → Reglas («Días para responder»). Un documento cargado cuenta desde el día en
    que se cargó y necesita respuesta hasta que alguien lo dé por revisado. Sin orden elegido, la lista va por
    **urgencia**: primero lo que hay que revisar, por prioridad y, dentro de cada una, lo que menos plazo tiene.
  - **Permisos** (matriz de roles, módulo Revisiones): «Cargar documentos», «Compartir documentos», «Cambiar la
    prioridad» y «Marcar como revisado». En los roles guardados antes de existir, los tiene quien ya podía aprobar o
    rechazar (`src/permisos.py`, pruebas en `tests/test_permisos_documentos.py`).
  - **Cargar archivo**: PDF, imagen, Word (.docx), Excel (.xlsx), CSV o texto (hasta 25 MB). El servidor lo prepara
    (`src/cargados.py`) y se puede **abrir enseguida** en Revisión, aunque no tenga hallazgos: el PDF página a página;
    el Word con títulos, párrafos y tablas; el Excel y el CSV como tablas. Queda **quién lo cargó y cuándo**; la
    **familia** se rellena sola por el código del documento (SRS-, REG-, EVR-…) y, si no se reconoce, se elige a mano.
    La cláusula no se rellena al cargar: es de cada hallazgo y sale al auditarlo (`python auditar.py`).
- **Revisión**: el PDF con la cita marcada; aprobar o rechazar con un comentario. Cada documento abierto queda como
  **pestaña** arriba (como Safari), con × para cerrarla; cada pestaña recuerda en qué hallazgo y página estabas.
  En la barra del documento: **Prioridad**, **Compartir** (eliges a personas del equipo y les llega una notificación con
  enlace), **Versiones** y **✎ Editar**. Un documento **sin hallazgos** se abre igual y se puede comentar y
  **marcar como revisado**.
  - **Versiones** (panel dentro del documento): el **original**, que nunca se modifica, y cada versión editada,
    numerada a partir de la versión oficial del documento: si el original es v3.0, las ediciones son **v3.0.1,
    v3.0.2…**, con autor, fecha, nota y un nombre opcional. «Comparar con el original» enseña los dos textos lado a
    lado (amarillo = añadido o cambiado, rojo = quitado) y «.txt» descarga el texto completo. Se guardan en
    `salidas/versiones/`.
  - **✎ Editar** (PDF; solo el Dueño de Proceso al que se ha escalado el documento, mientras no esté completado; al resto
    le sale el candado con el motivo): la página junto a su texto, ahora **legible** (párrafos juntos y tablas fila a fila,
    `src/texto_paginas.py`). Lo que cambias se **resalta mientras escribes** (amarillo; una marca roja donde se quitó
    algo, y debajo qué se quitó).
- **Panel de control IA**: lo que hizo cada agente y el F1.
- **Histórico**: con asistente y exportación de `respuestas.csv` y `feedback.csv`.
- **Configuración**.
- **Mi cuenta** (*My account* en inglés; también pulsando tu nombre arriba a la derecha): perfil (nombre, usuario,
  correo, rol, idioma y cerrar sesión), **sesiones abiertas** (navegador y desde cuándo; las lleva el servidor) y la
  **política de acceso real** del prototipo, separada de lo previsto. Llaves de acceso, app de autenticación y códigos
  de recuperación aparecen como «Próximamente»: llegarán con el inicio de sesión de Microsoft (Entra ID, ver
  `AIworkspaces/airbus/AUTENTICACION.md`).

El menú lateral lleva un icono junto a cada opción.

Las decisiones del revisor se guardan en el navegador y se exportan a `feedback.csv`. Nunca modifican `respuestas.csv`.
Arriba a la derecha, **ES / EN** cambia el idioma de la interfaz (los hallazgos siguen en español, como salen del auditor).

### Revisión en equipo, en vivo

```powershell
.\.venv\Scripts\python servidor.py      # después de generar_revision.py
```
La consola muestra dos direcciones: `http://localhost:8765` para ti y `http://<tu-IP>:8765` para los compañeros
**conectados a la misma Wi-Fi** (si Windows pregunta por el Firewall, pulsa «Permitir»). Con el servidor:
- las decisiones (aprobar / rechazar) son compartidas: si alguien aprueba, lo veis todos en unos segundos;
- cada hallazgo tiene un **debate** con comentarios; escribe `@nombre` para avisar a alguien;
- la **campanita** agrupa las notificaciones por chat o hallazgo («2 nuevos · 1 mención») en un **montón** como el de macOS.
  Pulsando la tarjeta se despliegan los mensajes del grupo para leerlos sin salir (no los marca como leídos);
  «Ver» abre el chat y **borra** ese grupo de la campanita; × lo borra sin abrirlo;
- **«Visto»** en el chat, debajo de tus mensajes: ✓ enviado · ✓✓ gris lo han visto algunos · ✓✓ azul lo han visto todos.
  En tu último mensaje se lee «Visto por Marina, Sergio» (o «Visto hace 2 min» en un privado); al pasar el ratón, quién y cuándo.
  Cuenta como visto cuando la otra persona tiene ese chat abierto y la pestaña a la vista;
- «*Marina también está en este hallazgo*»: quién está mirando lo mismo que tú;
- **Chat** con tres tipos: **canales públicos** (los crea o borra un administrador del equipo), **grupos** (los crea
  cualquiera; su creador los administra: nombre, integrantes y papeles) y **privados** entre dos personas. Cada uno
  solo recibe los chats en los que está; `#número` enlaza un hallazgo;
- **Configuración → Usuarios**: roles y usuarios con permisos por módulo (ver abajo).

### Usuarios, roles y permisos

Con el servidor, solo entra quien está dado de alta: `/api/login` da un token de sesión y **todas** las operaciones
sacan el usuario de ese token (nunca del cuerpo de la petición) y comprueban el permiso de su rol en el servidor
(`src/permisos.py`). El inicio de sesión todavía no pide contraseña (prototipo; en producción, Entra ID).

- **Roles** (Configuración → Usuarios → Roles): nombre, descripción y una matriz de permisos por módulo.
  Solo el rol **Admin** crea, edita o elimina roles; los demás los consultan. Ninguna casilla concede administrar roles.
  Admin y Dueño de Proceso son roles del sistema (no se eliminan); un rol con usuarios tampoco se elimina.
- **Permisos** (acciones reales de la app):
  - Revisiones: consultar, **aprobar** y **rechazar** (independientes), comentar, editar hallazgos, escalar documentos,
    editar documentos escalados.
  - Configuración: consultar, cambiar el umbral, gestionar usuarios.
  - Descarga de histórico: respuestas del auditor, revisión del equipo.
- **Usuarios**: crear, editar (correo y rol) y eliminar. Todo usuario tiene un rol existente; solo un Admin da o quita
  el rol Admin y siempre queda al menos uno. Al cambiar el rol cambian al momento los permisos.
- **Escalamiento y edición de documentos**: en Revisión, «⇪ Escalar» asigna el documento a UNA persona con rol
  **Dueño de Proceso**. Solo esa persona puede pulsar «✎ Editar» (crear versiones), y solo mientras el documento no
  esté Completado. Si se escala a otra persona, el anterior deja de poder editarlo; ambos reciben un aviso.

Pruebas (42, sin instalar nada; levantan el servidor en un puerto libre con datos temporales):

```bash
.venv/bin/python -m unittest tests.test_permisos -v      # Windows: .\.venv\Scripts\python -m unittest tests.test_permisos -v
```
- **Aviso emergente**: cuando llega una notificación nueva sale arriba a la derecha y se oculta solo a los **10 segundos**
  (con el ratón encima se pausa); la notificación sigue en la campanita;
- **Editar un mensaje** solo durante los **30 minutos** siguientes a enviarlo (el ✎ desaparece después y el servidor lo rechaza);
- **Vaciar chat**: cada persona puede vaciar un chat **solo para sí**; los demás siguen viendo los mensajes;
- **Adjuntos** (imágenes, PDF, texto) se abren en una **vista previa dentro de la página**, con × para cerrar (o Esc).

Para conectarse desde fuera de la red (por ejemplo, desde casa) se puede usar Radmin VPN: todos en la misma red
de Radmin y se abre `http://<IP de Radmin del ordenador con el servidor>:8765`. El inicio de sesión es de prototipo
(no comprueba contraseñas); en producción se conectaría a Entra ID.

Todo se guarda en `salidas/colaboracion.json` (las versiones de los PDF en `salidas/versiones/` y los documentos
cargados en `salidas/revision/cargados/`), en el ordenador que ejecuta el servidor; nada sale fuera.

La primera vez que se ejecuta `generar_revision.py` tras esta versión prepara el texto legible de cada página
(≈1 minuto para el corpus); después se reutiliza.

### Asistente IA con modelo (RAG local con Llama)

El botón **Asistente IA** responde al momento con lo que encuentra en la app (con botones «Ver…»). Con el servidor de
equipo encendido, **además** lee los documentos y contesta con un modelo, citando las fuentes. El modelo es Llama en
Ollama, 100 % local. Busca en el corpus NIMBUS (los PDF) y en el código y la documentación de `airbus/`, y recibe los
hallazgos y métricas que ya calculó la app (no calcula ni inventa). Sus juicios son propuestas para revisar.

Una vez (desde `AIworkspaces`, ver `AIworkspaces/README.md`): instalar Ollama, `ollama pull llama3.2`,
`ollama pull nomic-embed-text`, crear `_rag/.venv` con **Python 3.13** e indexar con `rag.py ingest`
(indexa también `03_corpus_trabajo_NIMBUS` de la raíz del repo; el índice se queda en local, no va a git).

Cada vez, con la app Ollama abierta, en dos terminales:

```bash
# Terminal 1 (desde AIworkspaces): el servicio del asistente, en http://127.0.0.1:8766
_rag/.venv/bin/python _rag/servidor_rag.py           # Windows: _rag\.venv\Scripts\python _rag\servidor_rag.py
# Terminal 2 (desde airbus/auditor): la app
.venv/bin/python servidor.py                         # Windows: .\.venv\Scripts\python servidor.py
```

Si el servicio del asistente está apagado, el botón sigue funcionando con la búsqueda en la app y avisa de que la IA no responde.
En qué carpetas busca se cambia en `AIworkspaces/_rag/config.py` (`ASISTENTE_CARPETAS`). Si cambias el puerto
(`ASISTENTE_PUERTO`), cámbialo también en `ASISTENTE_URL` de `servidor.py`.

Alternativa en Streamlit: `.\.venv\Scripts\python -m streamlit run app.py` (`app_clasica.py` es la primera versión).

## Reglas del equipo

- No subir nunca `.env`, `cache/`, `salidas/` ni el corpus o la clave (ya están en `.gitignore`).
- Antes de cambiar el auditor, mide el F1. Después del cambio, vuelve a medirlo y compáralo: no bajar la precisión.
