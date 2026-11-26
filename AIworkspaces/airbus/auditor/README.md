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
- **Inicio**: los documentos.
- **Revisión**: el PDF con la cita marcada; aprobar o rechazar con un comentario.
- **Panel de control IA**: lo que hizo cada agente y el F1.
- **Histórico**: con asistente y exportación de `respuestas.csv` y `feedback.csv`.
- **Configuración**.

Las decisiones del revisor se guardan en el navegador y se exportan a `feedback.csv`. Nunca modifican `respuestas.csv`.

Alternativa en Streamlit: `.\.venv\Scripts\python -m streamlit run app.py` (`app_clasica.py` es la primera versión).

## Reglas del equipo

- No subir nunca `.env`, `cache/`, `salidas/` ni el corpus o la clave (ya están en `.gitignore`).
- Antes de cambiar el auditor, mide el F1. Después del cambio, vuelve a medirlo y compáralo: no bajar la precisión.
