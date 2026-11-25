# Reto Airbus · NIMBUS — Arquitectura, estado y plan

Documento de trabajo del equipo. Resume qué pide el reto real, qué tenemos funcionando, cuánto mide y cómo lo
llevamos a escala (≈ 7.000 usuarios y > 50.000 documentos), aunque hoy solo tenga que funcionar con 75.

---

## 1. Qué se evalúa (lo esencial de la guía)

- **Entrega:** un sistema que recibe **una carpeta de PDF** y escribe **`respuestas.csv`** sin intervención manual.
  Se ejecuta **tal cual** sobre un **corpus oculto** (misma estructura, otros defectos) el jueves: 45 min entre
  que nos lo dan (18:30) y el límite (19:15).
- **Formato:** `documento, ubicacion, tipo, clausula, justificacion` (+ columnas extra opcionales al final).
  El puntuador empareja por **documento + identificador literal** de la ubicación (`C2L-SEC-025`, `VUL-2026-012`,
  `R-17`, `cuenta u1005`…; si no hay ID: `Tabla N`, `Figura N`, `§N`). La cláusula se compara por igualdad exacta.
- **Métricas:** precisión, recall, **F1 (principal)** y % de cláusulas correctas. Referencia: **F1 ≥ 0,60 y ≥ 80 % de cláusulas**.
- **Jurado:** detección 30 % · diseño técnico y agéntico 20 % · trazabilidad 15 % · visualización 15 % ·
  justificaciones 10 % · documentación 10 %.
- **Jerarquía normativa:** Part-IS > STD-SEC-001 (vigente) > LISTA-DOC > políticas/procedimientos/especificaciones > registros.
- **Cuatro canales de defecto:** prosa, tablas, figuras y cruces entre documentos. 13 documentos son escaneados.

## 2. Estado actual (medido con el puntuador oficial, corpus de trabajo, sin LLM)

| Métrica | Valor |
|---|---|
| Precisión | **1,00** (48/48) |
| Recall | 0,225 (48/213) |
| **F1** | **0,368** |
| Cláusula correcta | **100 %** (48/48) |
| Tiempo (75 PDF, 571 págs) | 36 s en frío · 1 s con caché |

Recall por canal: prosa 19/57 · tabla 18/97 · cruzado 11/47 · figura 0/12.
Recall por familia: especificaciones 32/58 · verificación 4/7 · riesgos 5/15 · núcleo 7/42 ·
**registros 0/61 · proveedores 0/18 · auditorías 0/7 · interfaces 0/5**.

En los 56 documentos sin clave salen 93 hallazgos; una revisión manual de muestra indica que son defectos reales del mismo
estilo (TLS 1.1, rotación de claves de 18 meses, MFA «cuando sea viable», referencias a requisitos inexistentes…):
las reglas **generalizan**, no están ajustadas a los 19 documentos con clave.

## 3. Arquitectura (lo que hay hoy)

```
 carpeta de PDF
      │
      ▼
 ┌─────────────┐   PDF → Documento (secciones, requisitos, tablas por coordenadas, figuras, ¿escaneado?)
 │  INGESTA    │   paralela, un proceso por documento, caché por huella del PDF          nimbus/ingesta.py
 └─────┬───────┘
       ▼
 ┌─────────────┐   vigencias (LISTA-DOC) · parámetros del STD-SEC-001 VIGENTE · plazos de Part-IS
 │CONOCIMIENTO │   (texto oficial, con cita) · requisitos definidos en el corpus · fórmula de riesgo
 └─────┬───────┘   TODO se lee del corpus: si el corpus oculto cambia un valor, se usa el nuevo   nimbus/conocimiento.py
       ▼
 ┌─────────────┐   reglas genéricas por FORMA del contenido (no por documento):
 │ DETECTORES  │   prosa · parámetros (cálculo con código) · riesgos (P×I) · trazabilidad · verificación
 └─────┬───────┘                                                                        nimbus/detectores/
       ▼
 ┌─────────────┐   dedupe por identificador (como empareja el puntuador) · validación de formato ·
 │   SALIDA    │   CSV progresivo + traza JSON (evidencia, detector, confianza, página) para la app
 └─────────────┘                                                                        nimbus/salida.py
```

**Una orden:** `python -m nimbus.ejecutar CARPETA --salida respuestas.csv` · **Medir:** `python -m nimbus.puntuar respuestas.csv`

Principios (los que pide la guía §9–10):
- **Determinismo donde se puede:** fechas, plazos, P×I, cruces → código. El LLM solo donde hace falta lenguaje.
- **Cada hallazgo con evidencia literal** (columna `evidencia`) y su fuente de mayor rango en la justificación.
- **Degradación elegante:** un detector o un PDF que falla se registra y se sigue.
- **Configuración y secretos fuera del código** (`.env`); el kit de desarrollo (clave) nunca va a git.

## 4. Plan por niveles (ordenado por recall perdido)

| Prioridad | Qué | Defectos en juego (clave) | Técnica | Estado |
|---|---|---|---|---|
| 1 | **Registros operativos** (cuentas, formación, vulnerabilidades, cambios, incidentes, copias, claves) | 61 + gran parte de los 47 cruzados | Tablas → dataframes; reglas del §10 del estándar como **funciones parametrizadas**; fechas con código; cruces entre registros (cuenta ↔ personal ↔ formación, vulnerabilidad ↔ cambio ↔ excepción, incidente ↔ notificación) | pendiente |
| 2 | **Prosa con LLM** (inconsistencias entre requisitos, cobertura faltante frente a Part-IS, matriz de cumplimiento vs texto oficial) | ~38 de prosa + matriz MCM | Juez LLM con salida JSON validada, **cita literal obligatoria** verificada contra el PDF, autoconsistencia; RAG sobre Part-IS oficial (ya indexado en ES y EN) | pendiente (claves) |
| 3 | **Escaneados** (8 proveedores + 3 auditorías + 2 actas) | 25 | Modelo con visión (GPT-5.5) → **JSON estructurado** con el mismo esquema que la ingesta digital; luego los MISMOS detectores. Medir la transcripción antes de auditar | pendiente (claves) |
| 4 | **Figuras** (diagramas de arquitectura, flujo, red, ciclo de accesos) | 12 | Visión → grafo (nodos, flechas, protocolos) → contraste con requisitos de segmentación/cifrado/MFA | pendiente (claves) |
| 5 | Interfaces (ICD) y evaluaciones de riesgos (fechas, interfaces no consideradas) | 15 | Reglas + LLM | parcial |

Calibración: cada hallazgo lleva `confianza`. Umbral configurable para elegir el punto precisión/recall; los dudosos
van a «Revisar» en la app (humano en el bucle), no al CSV.

## 5. Escalar a ~7.000 usuarios y > 50.000 documentos

Hoy: un proceso local, 75 PDF en 36 s. El diseño ya separa las piezas que hay que escalar.

**Volumen.** 50.000 documentos × ~7,6 págs ≈ 380.000 páginas. Ingesta digital ≈ 0,4 s/página/núcleo → ~42 h·núcleo:
en un clúster de 32 núcleos ≈ **1,5 h la primera vez**; después **solo lo que cambia** (caché por huella).
Visión solo para escaneados/figuras (~10 % de páginas ≈ 38.000) en lotes con límites de ritmo.

| Pieza | Hoy (hackathon) | A escala (plataforma IndesIA / Azure) |
|---|---|---|
| Almacén de PDF | carpeta local | **ADLS Gen2**, una ruta por organización y versión |
| Ingesta | `ProcessPoolExecutor` | **Databricks Jobs** (un PDF por tarea, Spark `mapPartitions`), reintentos y cola de errores |
| Caché | JSON por huella en disco | tabla **Delta** por huella + versión de ingesta (incremental) |
| Normativa y estándar | en memoria | **Azure AI Search** (híbrido BM25 + vectores) por cláusula, con metadatos de vigencia |
| Datos estructurados (registros, hallazgos, decisiones) | SQLite | **PostgreSQL** (particionado por organización) |
| LLM / visión | — | Azure OpenAI: **modelo pequeño** (clasificar, extraer) y **grande** (razonar); caché de respuestas por (prompt, huella) |
| Orquestación agéntica | funciones Python | LangGraph por documento (sin estado compartido) |
| App (7.000 usuarios) | Streamlit local | Streamlit/FastAPI en **Azure Container Apps** con autoscalado, solo lectura de PostgreSQL; login **Microsoft Entra ID** (ya iniciado en `src/auth.py`) con roles revisor/auditor/admin |
| Secretos | `.env` | **Key Vault** + identidades gestionadas |
| Observabilidad | consola + traza JSON | MLflow (experimentos y métricas por versión) + logs centralizados |

**Coste:** reglas y cálculos son gratis; el LLM solo se llama para lo que las reglas no resuelven (prosa ambigua,
escaneados, figuras). Un documento que no cambia no se vuelve a pagar.

**Multi-organización:** el conocimiento (estándar vigente, lista maestra) se construye **por organización**; Part-IS es
común. Ningún detector depende de NIMBUS.

## 6. Reparto sugerido del equipo

| Persona | Bloque | Entrega comprobable |
|---|---|---|
| A | Registros (nivel 3) | «una tabla de registro → dataframe sin perder filas» + reglas del §10 del estándar |
| B | LLM de prosa + RAG Part-IS (nivel 2) | hallazgos de prosa con cita verificada; comparar F1 con/sin LLM |
| C | Visión: escaneados y figuras (nivel 4) | «un escaneado audita igual que uno digital» |
| D | App + pitch | panel filtrable alimentado por `respuestas.traza.json` (misma fuente que el CSV) |

Regla de oro: **medir cada cambio** con `python -m nimbus.puntuar` y revisar a mano una muestra de los documentos SIN clave.

## 7. Limitaciones conocidas (hoy)

- Escaneados y figuras: aún sin visión (0/37 defectos de esos canales).
- Registros operativos: aún sin reglas (0/61).
- Las tablas se reconstruyen por coordenadas: tablas con diseños muy distintos pueden necesitar ajustes.
- Las cifras son del corpus de trabajo; el corpus oculto tendrá otros defectos.

*Uso de IA: el código se ha desarrollado con ayuda de Claude Code (asistente de programación), revisado y probado por el equipo.*
