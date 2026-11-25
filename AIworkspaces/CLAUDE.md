# Proyecto: IndesIAhack 2026 — preparación de los 5 retos

## Estado actual y decisión importante (leer primero)
- **Cada reto es un proyecto independiente y autocontenido** en su carpeta (`acerinox/`, `tecnicas_reunidas/`, `airbus/`, `rbe/`, `enagas/`): su propio `.venv`, `requirements.txt`, `.env`, `config.py`, `src/db.py` (SQLAlchemy: SQLite local / PostgreSQL Azure, una BD por reto) y `app.py`. **No crear carpetas `motores/` ni `ui/` compartidas**: los motores A/B se copian dentro de cada reto. Motivo: el día solo se presenta un reto y tocar uno no debe romper otro. (Esto prevalece sobre la "Estructura de carpetas" de más abajo.)
- **Hechos (20-nov-2026):** RBE (F1 0,89 con datos sintéticos) y Enagás (−59 % de revisiones con la misma detección).
- **Hecho (25-nov-2026): Airbus** (baseline sin LLM: grafo LangGraph completo, normativa real de EASA troceada por cláusula, F1 1,00 en el documento sintético —inflado— y 0,77 en la prueba ciega; el juez LLM está implementado pero sin probar hasta tener claves).
- **Hecho (25-nov-2026): Acerinox** (sin LLM: intérprete por reglas con citas al catálogo, SQL determinista, reglas R1-R6, validador; 100 % en casos propios —inflado— y 98 % de campos / 100 % de acciones en prueba ciega; 0 bultos inventados. LLM y voz programados, sin probar).
- **Pendiente:** Técnicas Reunidas.
- **Smart App Control (Windows 11) en uno de los portátiles del equipo** bloquea DLL sin firmar: SQLAlchemy 2.1 no carga (por eso `sqlalchemy>=2.0,<2.1` en los requirements) y `psycopg` tampoco (PostgreSQL de Azure desde ese portátil probablemente falle). También bloquea los lanzadores `streamlit.exe` y `pip.exe` → en ese portátil usar siempre `python -m streamlit run app.py` y `python -m pip ...`.
- Los PDFs de los enunciados están en `retos/`.
- Azure CLI ya instalado en el portátil de Sergio (no hace falta en el de los demás salvo para conectar a PostgreSQL).

## Situación
- Hackathon del 25 al 27 de noviembre de 2026 (ETSIT-UPM). Hay 5 retos (Acerinox, Técnicas Reunidas, Airbus, RBE, Enagás) y **el reto se asigna al azar el miércoles 25**, así que preparamos los 5.
- **Calendario real (tiempo muy corto, ~1,5 días de desarrollo):**
  - Mié 25: formación de equipos, asignación del reto, check-in y acceso a la plataforma (por la tarde).
  - Jue 26: desarrollo con mentores.
  - **Vie 27 · 10:00: el código debe estar en el repositorio GitLab del equipo** (entrega). La presentación se sube al canal privado de Teams antes de exponer. 11:00: exposiciones.
  - Consecuencia: priorizar SIEMPRE un flujo de punta a punta que funcione y se pueda enseñar. Nada de extras hasta tenerlo.
- Los datos reales de cada empresa se publican ese día en la plataforma IndesIA. Hasta entonces trabajamos con **datos sintéticos** que imitan su formato, para que el día del reto solo haya que conectar los datos reales.
- Los PDFs con los enunciados están en `retos/`. Léelos si necesitas detalle.
- Idioma: responde y comenta el código en **español**. El equipo no es experto: explica los pasos y da los comandos exactos para ejecutar en la terminal de VSCode (Windows/Mac).

## Estrategia: 2 motores + 1 interfaz común
- **Motor A – anomalías explicables** (`motores/anomalias/`) → RBE y Enagás. Serie temporal → patrón esperado → desviación → prioridad → explicación.
- **Motor B – documento → dato con evidencia** (`motores/documentos/`) → Airbus, Técnicas Reunidas, Acerinox. Cada valor extraído se guarda como `{valor, unidad, fuente: {doc, pagina, bbox}, confianza}`.
- **Interfaz común** (`ui/`) en Streamlit: bandeja/lista priorizada, semáforo, panel de detalle con evidencia, botones aprobar/rechazar (humano en el bucle).

## Reglas de diseño (los 5 jurados las valoran)
1. **El LLM no inventa ni calcula.** Los números salen del código o de la BD; el LLM interpreta, orquesta herramientas y redacta explicaciones usando solo datos ya calculados.
2. **Trazabilidad:** todo resultado enseña de dónde sale (fila, página, cláusula, recorte del PDF).
3. **Salidas del LLM siempre en JSON validado con Pydantic.** Si no valida, se reintenta.
4. **Humano en el bucle:** lo dudoso se marca "Revisar", no se decide solo.
5. Cada reto tiene una **métrica que se calcula y se enseña en la demo** (F1, error en mm, % de ruido reducido…).
6. Código simple y ejecutable de punta a punta antes de añadir extras. Primero algo que funcione, luego mejorarlo.

## Cómo funciona la plataforma IndesIA (guía oficial)
- Entrada única: **portal.indesia.org** (correo de inscripción + Microsoft Authenticator). Desde ahí: Perfil (equipo y reto), Archivos, Databricks y GitLab. No entrar por la web general de Azure.
- **Datos del reto** en Databricks, en el volumen del equipo:
  `/Volumes/<catalogo_equipo>/raw_sch/raw_vol/datos_reto/` (p. ej. catálogo `dat_hack_en01`). Lo subido por nosotros va a `.../raw_vol/uploads/`. **Nunca borrar nada de `datos_reto`** (no se recupera).
- Subir archivos: CSV/TXT/JSON/PARQUET desde el portal (≤2 GB); PDF, Excel, Word desde Databricks → Catalog → raw_vol → "Upload to this volume".
- **Clúster**: se crea solo desde el portal (Small / Medium / Large). Empezar con Small. Tarda 8–10 min en arrancar y se apaga tras 30 min sin uso → encenderlo antes de necesitarlo. Alternativa: **Serverless** en el notebook.
- Notebooks: New → Notebook. Primera celda de cada sesión: `%pip install ...` con las librerías necesarias (p. ej. `pypdf python-docx openpyxl`). Los `%pip` se pierden al reiniciar.
- **GitLab** (gitlab-dataton.indesia.org): entrar con "IndesIA Azure Entra ID" (no usuario/contraseña); repo en Projects → pestaña Member, nombre tipo `hack/hack-en01`. Clonar por SSH. El README de la plantilla trae un `git remote` que apunta a la plantilla: comprobar con `git remote -v` y corregir con `git remote set-url origin git@gitlab-dataton.indesia.org:hack/<repo>.git`. **Hacer push a menudo.**
- **Claves** (Azure OpenAI, Search, AI services, PostgreSQL): en un PDF del canal general de Teams, como enlaces a 1Password. **Prohibido escribirlas en el código o subirlas a GitLab** → solo en `.env`, y `.env` en `.gitignore` desde el primer commit. En Databricks, leerlas de variables o pedirlas con `dbutils.widgets`, nunca escritas en el notebook que se sube.
- PostgreSQL: un servidor por equipo; la conexión necesita **Azure CLI** instalado en el portátil.
- La guía oficial solo menciona modelos **GPT** y embeddings en Azure OpenAI (la diapositiva de recursos decía también Claude): comprobar el día 25 qué despliegues hay y configurar el nombre del modelo en `.env`.
- Ignorar en Databricks: "Create with Personal Compute", catálogos `samples` y `test_ml_cluster`, Genie/Playground/Agents.

### Flujo de trabajo VSCode ↔ Databricks ↔ GitLab
1. Código del proyecto en VSCode (local) → `git push` al GitLab del equipo.
2. En Databricks, traer el repo con **Workspace → Git folders** (carpetas Git) para ejecutar los notebooks/módulos sobre los datos reales y el clúster.
3. Procesado pesado y modelos (RBE, Enagás) en Databricks; los resultados (tablas de alertas, JSON, IFC) se guardan en el volumen o en PostgreSQL.
4. La demo (Streamlit) se ejecuta en el portátil, leyendo los resultados (descargados del volumen desde el portal, botón Download, o desde PostgreSQL) y llamando a Azure OpenAI con las claves del `.env`.
5. Estructura de código pensada para ambos sitios: lógica en módulos `.py` importables + notebooks finos que solo llaman a esos módulos. Rutas de datos configurables (`DATA_DIR` local o `/Volumes/...` en Databricks).

## Plataforma del hackathon (recursos Azure que da IndesIA)
El día del reto usaremos estos servicios. Antes del evento, cada uno tiene un **sustituto local** para poder preparar el código sin acceso; el código debe tener una capa (`config.py` + `.env`) que permita cambiar entre local y Azure sin tocar la lógica.

| Servicio de la plataforma | Para qué lo usamos | Retos | Sustituto local para preparar |
|---|---|---|---|
| **Azure OpenAI** (GPT, Claude, Audio, Embeddings) | LLM de todos los agentes; Audio = transcripción de voz (Whisper); Embeddings para RAG | Todos; Audio → Acerinox | API de OpenAI/Anthropic o modelo local; sentence-transformers |
| **Azure AI Search** | Índice RAG con búsqueda híbrida (palabras clave + vectores + ranker semántico) ya integrada | Airbus (normativa EASA por cláusula), Acerinox (catálogo) | rank-bm25 + chromadb |
| **Databricks** | Notebooks, procesado de datos y entrenamiento de modelos (MLflow para registrar experimentos) | RBE, Enagás (Motor A); Airbus lo pide expresamente | pandas en local |
| **Azure AI services multi-service** | **Document Intelligence**: OCR, tablas y layout con coordenadas (bbox) → evidencia trazable; **Speech**: voz a texto y texto a voz | TR (planos GA, HDM), Airbus (documento a auditar), Acerinox (catálogo + voz) | pymupdf / pdfplumber; Whisper |
| **Azure Database for PostgreSQL** | BD relacional: inventario de stock, tabla de alertas, decisiones humanas (aprobar/rechazar) | Acerinox (stock), RBE/Enagás (alertas), Airbus (hallazgos + HITL) | SQLite o PostgreSQL local |
| **Azure Data Lake Storage Gen2** | Donde probablemente estén los datos del reto; guardar PDFs, JSON, IFC generados y resultados | Todos | carpeta `datos/` local |

Notas:
- Usar el SDK oficial: `openai` (cliente `AzureOpenAI`), `azure-search-documents`, `azure-ai-documentintelligence`, `azure-cognitiveservices-speech`, `psycopg`, `azure-storage-file-datalake`, `databricks-connect`.
- Claves y endpoints solo en `.env` (`AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_KEY`, `AZURE_SEARCH_ENDPOINT`, etc.).
- Que el modelo (GPT o Claude) sea configurable por `.env`, para comparar cuál rinde mejor en cada reto.

## Stack
Python 3.11+, entorno virtual `.venv`, `requirements.txt` por carpeta.
- Datos/ML: pandas, numpy, scikit-learn, statsmodels (STL), ruptures, lightgbm, shap
- Documentos: pymupdf, pdfplumber, openpyxl, rank-bm25, sentence-transformers / chromadb
- LLM/agentes: langchain, langgraph, pydantic (proveedor LLM configurable por `.env`; en Airbus usar Azure OpenAI + Azure AI Search si la plataforma lo da)
- Voz: openai-whisper o API de transcripción
- 3D: ifcopenshell; visor web con web-ifc / That Open
- UI: streamlit, plotly
- Claves en `.env` (nunca en el código ni en git).

## Estructura de carpetas
```
retos/                 PDFs de los enunciados
motores/anomalias/     Motor A reutilizable
motores/documentos/    Motor B reutilizable
ui/                    plantilla Streamlit común
acerinox/  tecnicas_reunidas/  airbus/  rbe/  enagas/
  ├─ datos_sinteticos/ generador + datos de prueba
  ├─ src/              lógica específica del reto
  ├─ app.py            demo Streamlit
  └─ README.md         cómo ejecutar + guion de pitch
```

## Los 5 retos

### 1. Acerinox – asistente de inventario por voz y texto
- Pide: interfaz conversacional (voz + texto) que traduce peticiones coloquiales ("chapa brillante de 2 mm que aguante el mar") a especificaciones técnicas y encuentra el bulto en stock, o propone transformaciones según reglas.
- Datos: BD de stock (ID único por bulto + especificaciones), reglas de transformación en TXT, catálogo PDF. Muestra reducida.
- Jurado: traducción al dato, repreguntar si falta info, **prohibido inventar** (ni aceros ni propiedades inexistentes), bulto correcto y disponible, transformaciones posibles, criterio de negocio, originalidad.
- Solución: Whisper → LLM rellena ficha (grado, acabado, espesor, ancho, largo, formato, cantidad) → diccionario coloquial→técnico desde el catálogo (RAG, con cita) → repregunta si falta un campo → el LLM solo llama a herramientas (`buscar_stock`, `proponer_transformacion`) con SQL determinista → validador que comprueba que todo ID mostrado existe → planificador de transformaciones con menor merma → ranking (menor merma, FIFO, no romper bultos grandes). Demo: tarjeta con bulto, encaje exacto/transformable, operaciones, merma y motivo.

### 2. Técnicas Reunidas – GA2MODEL (plano 2D → modelo 3D IFC)
- Pide: leer planos GA (PDF) y hojas de datos (HDM, Excel/PDF), extraer geometría trazable, generar modelo IFC y procesar rev2 explicando cambios.
- Datos: por equipo (TAG): `GAD_<TAG>_rev1/rev2`, `HDM_<TAG>`, `VESOR_<TAG>`, `ESTRUCTURA_<TAG>`, y `<TAG>.ifc` de referencia en 4 equipos (estáticos Conjunto A).
- Obligatorio: IFC (carcasa + tapas + ≥3 boquillas + soporte, sin errores), JSON con valor+unidad+fuente+confianza, visor. Bonus: delta rev1→rev2.
- Jurado: fidelidad geométrica vs IFC referencia **35 %**, extracción de atributos y calibración de confianza **25 %**, actualización incremental **20 %**, arquitectura/escalado 10 %, innovación 10 %. Demo de 6 min: plano → dato → modelo → cambio → decisión.
- Solución: texto vectorial con coordenadas (pymupdf) + VLM para vistas → JSON trazable (confianza alta si GA/HDM/VESOR coinciden) → plantillas paramétricas (recipiente vertical: virola + fondos + faldón; horizontal: silletas) → IFC con ifcopenshell + Psets → visor con clic en boquilla = recorte del PDF → diff rev1/rev2 coloreado → script que mide error en mm contra los IFC de referencia. Empezar por UNA tipología (recipiente vertical).

### 3. Airbus – auditoría de cumplimiento normativo con agentes
- Pide: auditar un documento técnico (requisitos con IDs) frente a normativa EASA: veredicto por requisito (Cumple / No cumple / Revisar) con justificación, enlace a la cláusula exacta, detección de contradicciones, informe visual.
- Datos: documento sintético, EASA Easy Access Rules (PDF/XML públicos; enfoque cyber: Part-IS, Reg. UE 2022/1645 y 2023/203), gold set con fallos marcados.
- Plataforma: Python en Databricks + VSCode, Azure AI Search, LangGraph (baseline recomendada).
- Jurado: F1 vs gold **30 %** (referencia ≥0,80), trazabilidad hallazgo→regla **20 %** (≥90 %), justificaciones 15 %, diseño agéntico (LangGraph, bucle de reflexión, HITL) 15 %, visualización 10 %, documentación 10 %.
- Solución: indexar EASA desde XML a nivel de cláusula con su ID → búsqueda híbrida BM25 + vectores → descomponer cada cláusula en obligaciones atómicas y juzgar requisito × obligación → grafo LangGraph: Supervisor → Extractor → Auditor → Trazabilidad → Crítico, con reflexión si baja confianza → autoconsistencia (3 juicios; si discrepan, "Revisar" + interrupt HITL) → consistencia por grupos temáticos + detector de contradicciones numéricas → calibrar umbrales con el gold set y mostrar F1 → dashboard con filtros, texto resaltado, enlace a cláusula, matriz reglas × requisitos, export HTML.

### 4. RBE (Burger King, Popeyes, Tim Hortons) – anomalías y cambios de tendencia en ventas
- Pide: detectar, distinguir del ruido (estacionalidad, campañas), priorizar y explicar anomalías puntuales y cambios de tendencia. Fuera de alcance: forecast oficial, despliegue.
- Datos: ventas por ticket y canal (restaurante, fecha, canal, ventas, tickets, ticket medio), calendario (festivos, eventos, no lectivos), maestro de restaurantes (marca, país, provincia, zona, tipología).
- Jurado: calidad técnica **30 %**, impacto negocio **25 %**, explicabilidad para no técnicos 20 %, reproducibilidad 15 %, creatividad 10 %. Métrica principal F1 (sin etiquetas: precision@K, backtesting).
- Salida pedida: tabla de alertas (restaurante, fecha/tramo, canal, métrica, tipo, score, impacto €, explicación, recomendación), gráficos real vs esperado, informe técnico.
- Solución (Motor A): STL + calendario por restaurante×canal → z-score robusto (MAD) para puntuales + change points (ruptures) para tendencias → comparación con restaurantes pares de la zona (descarta eventos externos) → agregación jerárquica → prioridad = impacto € × severidad × persistencia → F1 inyectando anomalías sintéticas → copiloto LLM que redacta con números ya calculados. UI: bandeja tipo email ordenada por € en riesgo.

### 5. Enagás – validación inteligente de Unidades de Medida (UM) de gas
- Pide: pasar de criterios de validación iguales para todas las UM a criterios adaptados a cada UM según su histórico; score de riesgo por UM y día; clasificar en revisión prioritaria / revisión recomendada / validación automática candidata; explicar cada recomendación. Panel de apoyo al equipo DLC.
- Criterios actuales diarios: NC, ERROR, MODULA, SERIE, AJUSTES, MODIF, DIF_PCS, DIF_ORION, DIF_ORION_ABS, DIF_HIS. Mensuales: CONTRAS, CONTRAS_OBS, DIF_PCS, DIF_ORION, DIF_ORION_ABS.
- Datos: lecturas diarias de campo (Neptuno), consumos diarios calculados (SLM, con modificaciones de usuarios), contrastación de contadores, consumos validados (ORION), calidad de gas diaria (PCS). Tabulares, serie diaria.
- Jurado: detección **25 %**, priorización **20 %**, explicabilidad y trazabilidad **20 %**, utilidad para DLC 15 %, viabilidad 10 %, visualización 10 %.
- Solución (Motor A): bandas históricas propias por UM (cuantiles por día de semana/estación) para cada criterio = "regla adaptativa" → features UM-día (Neptuno vs SLM vs ORION, dif. PCS, variación semanal, contrastación, ajustes previos) → etiqueta proxy = días que el usuario ajustó/modificó → LightGBM + Isolation Forest → SHAP traducido a frase → balance por ramal con UM vecinas → semáforo de 3 niveles → gráfico regla estándar vs adaptativa (menos alertas, mismo recall) y % de validación automática candidata.

## Extras que suben nota (añadir cuando el núcleo funcione)
Ideas buenas y baratas recogidas de un documento externo de ideas. No sustituyen al núcleo: se añaden encima, en este orden de prioridad.

- **Enagás**
  1. *Simulador de umbrales con backtesting*: el usuario mueve un umbral y ve cuántas alertas habría dado el histórico, cuántas coinciden con ajustes reales y cuántas revisiones se ahorran; sugiere el umbral óptimo por UM. Hace visible el "% de medidas candidatas a validación automática".
  2. *Origen probable*: cruzar Neptuno/SLM/ORION/calidad de gas/contrastación para decir si apunta a contador, conversor, cromatógrafo o ajuste manual (el jurado valora "identificar la causa probable").
  3. *Arranque en frío*: UM con poco histórico heredan el perfil de UM similares (clustering) hasta tener datos propios.
- **RBE**
  1. *Descomposición de la caída*: ventas = tickets × ticket medio, y por canal → "cae por menos tickets en delivery, no por precio". Muy barato y muy explicable.
  2. *Semáforo de persistencia*: estado ruido → posible cambio → cambio confirmado, y medir la anticipación (días hasta detectar un cambio), porque el reto pide detectar tendencias "con la mayor anticipación posible".
  3. *Calendario aprendido*: proponer etiquetar efectos recurrentes no explicados (puentes, eventos locales) para descontarlos después.
- **Técnicas Reunidas**
  1. *Comprobaciones de plausibilidad* antes de generar el IFC: boquillas fuera de la carcasa, peso en operación menor que en vacío, cotas que no suman, diámetros no normalizados. Cada fallo con evidencia.
  2. *Impacto por disciplina en el delta*: "skirt +150 mm → afecta a Civil; N3 movida → afecta a Piping".
  3. Cada corrección del ingeniero en el visor se guarda como ejemplo para futuras extracciones.
- **Acerinox**
  1. *Alternativas equivalentes*: si no hay stock exacto, ofrecer equivalentes **solo si el catálogo los respalda**, marcados claramente como alternativa.
  2. *Plan de corte visual*: combinar varios bultos para pedidos grandes minimizando merma, con un esquema dibujado.
  3. *Demanda no atendida*: registrar peticiones sin solución y resumirlas para compras/producción.
- **Airbus**
  1. *Verificador de citas*: comprobar que la cláusula citada existe y respalda el veredicto; si no, pasa a "Revisar". Sube directamente el 20 % de trazabilidad.
  2. *Gold set adversarial*: generar incumplimientos sintéticos para ampliar las pruebas y reevaluar el F1 automáticamente cada vez que se cambia un prompt o modelo.
  3. *Agente de remediación*: para cada "No cumple", proponer una redacción corregida mostrada como diferencia; el revisor acepta o rechaza.

Descartadas para el hackathon (demasiado coste para 3 días o dependen de datos que quizá no haya): vigilancia de cambios normativos EASA, mapa territorial y canibalización en RBE (requiere ubicaciones), biblioteca RAG de equipos en TR, aprendizaje activo en Enagás (mencionarlo solo en el pitch como evolución).

## Pitch (estructura común, ~6 min)
Problema (trabajo manual que se elimina) → datos reales con su evidencia → resultado visible en vivo → métrica → sostenibilidad (qué se mantiene, qué se reentrena, cuánto cuesta operarlo).

## Orden de trabajo antes del evento
1. Crear `.venv`, estructura de carpetas y `ui/` con plantilla Streamlit común.
2. Motor A + generador sintético RBE y Enagás con anomalías inyectadas + cálculo de F1.
3. Motor B: extractor PDF con coordenadas, visor de evidencia, wrapper LLM con JSON validado, RAG híbrido.
4. Airbus: descargar e indexar normativa EASA Part-IS por cláusula; grafo LangGraph mínimo.
5. Técnicas Reunidas: generador IFC paramétrico de recipiente vertical desde JSON.
6. Acerinox: inventario simulado + reglas de transformación de ejemplo + chat con herramientas.
7. README y guion de pitch de 6 minutos por reto.

## El día del hackathon (plan comprimido)
- **Mié 25 (tarde):** acceso, crear clúster Small, clonar repo, mirar `datos_reto`, preguntar al mentor la métrica exacta y el formato. Adaptar el esqueleto ya preparado a los datos reales. Objetivo del día: flujo de punta a punta feo pero funcional + primer push.
- **Jue 26:** calidad del resultado + métrica del jurado + interfaz Streamlit. Push cada pocas horas. Por la noche: guion del pitch y presentación.
- **Vie 27 antes de las 10:00:** último push con README (cómo ejecutar), presentación en Teams, ensayo de la demo con un plan B (capturas o vídeo por si falla la red).
