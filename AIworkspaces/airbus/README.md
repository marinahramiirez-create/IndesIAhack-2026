# Airbus — Auditoría automática de cumplimiento normativo (EASA Part-IS) con agentes

Proyecto **independiente**: tiene su propio entorno, su propia base de datos y su propia app.
Audita un documento técnico de requisitos frente a la normativa de ciberseguridad aeronáutica de EASA
(Part-IS, Reg. UE 2023/203 y 2022/1645): veredicto por requisito (**Cumple / No cumple / Revisar / No aplica**),
justificación, enlace a la cláusula exacta, contradicciones entre requisitos e informe exportable.

## Instalación (una sola vez)

Terminal de VSCode (`Ctrl + ñ`):

**Windows (PowerShell)**
```powershell
cd airbus
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
> Si PowerShell bloquea la activación: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repite.

**Mac**
```bash
cd airbus
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Ejecutar (con el entorno activado, dentro de `airbus/`)
```
python datos_sinteticos/generar.py   # 1. documento de requisitos + gold set de prueba
python -m src.pipeline               # 2. grafo de agentes → veredictos, métricas → BD
streamlit run app.py                 # 3. informe interactivo en el navegador
```
> Si sale *"An Application Control policy has blocked this file"* (Smart App Control de Windows 11 bloquea
> `streamlit.exe`), usa `python -m streamlit run app.py`. Igual con pip: `python -m pip install ...`.
La normativa ya está troceada por cláusula en `normativa/clausulas.json`. Para regenerarla desde el XML oficial de EASA:
```
python -m src.normativa normativa/EAR_Information_Security_2025-12.xml
```
(XML descargado de la web pública de EASA → *Easy Access Rules for Information Security* → versión XML.
No se sube a git porque ocupa 32 MB; el JSON sí.)

## Qué hace

| Paso (agente) | Archivo | Cómo |
|---|---|---|
| Normativa → cláusulas | `src/normativa.py` | Lee el XML oficial de EASA y saca 332 cláusulas (41 IR, 90 AMC, 169 GM) con su ID y sus apartados (a), (b)… |
| Obligaciones atómicas | `normativa/obligaciones.json` | Cada regla IS.I.OR troceada en obligaciones verificables (24), cada una con cita literal, elementos exigidos y límites numéricos (72 h, 5 años, 3 años) |
| **Extractor** | `src/documento.py` | `.docx` / `.pdf` / `.md` → requisitos con ID, sección y ubicación (párrafo/página) |
| RAG | `src/rag.py` | BM25 sobre obligaciones y cláusulas. Con embeddings de Azure → búsqueda híbrida. Sustituible por Azure AI Search |
| **Auditor** | `src/auditor.py` | Juez por reglas (elementos presentes, límites numéricos calculados por código, redacción vaga) + juez LLM opcional con JSON Pydantic y **autoconsistencia** (3 juicios; si discrepan → Revisar) |
| **Reflexión** | `src/grafo.py` | Si la confianza es baja, se reformula la búsqueda (sinónimos o LLM) y se re-juzga. Si sigue baja → Revisar |
| **Trazabilidad** | `src/grafo.py` | Verifica que la cláusula citada existe; **verificador de citas** del LLM (la cita debe estar literalmente en la norma); cobertura de reglas IR |
| **Crítico** | `src/consistencia.py` | Contradicciones (mismo parámetro, distinto valor) y homogeneidad del detalle |
| Supervisor + HITL | `src/grafo.py` | LangGraph decide el siguiente agente según el estado; `construir(hitl=True)` se para antes del cierre (`interrupt`) |
| Métricas | `src/evaluar.py` | P/R/F1 vs gold, % de trazabilidad, contradicciones |
| Base de datos | `src/db.py` | SQLite local / PostgreSQL Azure (`hallazgos`, `contradicciones`, `cobertura`, `metricas`, `decisiones`) |
| Informe | `app.py` | Contadores, tabla filtrable, texto que incumple resaltado, cláusula enlazada, matriz requisitos × reglas, decisiones del revisor, export HTML/CSV |

## Resultados con datos sintéticos (sin LLM, solo juez por reglas)

| Conjunto | F1 detección | Trazabilidad | Contradicciones |
|---|---|---|---|
| Documento principal (38 requisitos) | 1,00 | 100 % | 4/4, 0 falsas |
| **Prueba ciega** (14 requisitos redactados con otras palabras) | **0,77** | **77 %** | 1/1, 2 falsas |

**Ojo: el 1,00 está inflado.** Las obligaciones y el documento principal se escribieron a la vez. La cifra realista
es la de la prueba ciega (`python datos_sinteticos/prueba_ciega.py`): el juez por reglas falla con sinónimos
("audit trails" en vez de "records", "prior approval", "every six months"). **Ahí es donde entra el juez LLM** el día del reto.

## El día del reto
1. **Preguntar al mentor**: formato del documento y del gold set (¿veredictos por requisito? ¿cláusula esperada?),
   si "Revisar" cuenta como acierto, y qué normativa exacta entra (¿solo Part-IS o también AMC/GM?).
2. Poner los ficheros en una carpeta y en `.env`: `DIR_DATOS`, `DOCUMENTO`, `GOLD` y, si los IDs son distintos,
   `PATRON_ID_REQUISITO`. Si el gold tiene otras columnas, adaptar `src/evaluar.py` (renombrar a `req_id`,
   `veredicto_gold`, `clausula_gold`).
3. Activar el LLM: `LLM_PROVEEDOR=azure` + claves + `AZURE_OPENAI_DEPLOYMENT` (y `AZURE_OPENAI_EMBEDDINGS`
   para la búsqueda híbrida). Ejecutar `python -m src.pipeline` y comparar F1 con y sin LLM (`LLM_PROVEEDOR=ninguno`).
4. Si la normativa del reto es otra parte de EASA: descargar su XML y `python -m src.normativa archivo.xml`.
   Las obligaciones atómicas de reglas nuevas se pueden redactar a mano o pedírselas al LLM (revisándolas).
5. Calibrar `UMBRAL_CONFIANZA` con el gold set.

## Guion de pitch (6 min)
1. **Problema (40 s)**: un auditor contrasta a mano cada requisito con cientos de cláusulas; poca trazabilidad.
2. **Arquitectura (60 s)**: grafo LangGraph (pestaña *Agentes*): Supervisor → Extractor → Auditor → Reflexión → Trazabilidad → Crítico → revisión humana.
3. **Demo (2 min)**: REQ-016 «within 5 working days» → No cumple, el límite de 72 h lo calcula el código, texto resaltado, cláusula IS.I.OR.230(c) enlazada. REQ-022: la reflexión corrige la regla recuperada.
4. **Consistencia (40 s)**: retención 5 años vs 2 años; y la trampa que NO marca (registros de personal 3 años).
5. **Fiabilidad (40 s)**: el LLM nunca calcula; autoconsistencia; verificador de citas; lo dudoso va a "Revisar".
6. **Métricas (40 s)**: F1 y % de trazabilidad frente al gold; honestos con la prueba ciega.
7. **Humano en el bucle y export (20 s)**: aprobar/corregir → BD → informe HTML.
