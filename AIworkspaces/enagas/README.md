# Enagás — Validación inteligente de Unidades de Medida (UM)

Proyecto **independiente**: tiene su propio entorno, su propia base de datos y su propia app.
Pasa de criterios de validación iguales para todas las UM a criterios **adaptados al histórico de cada UM**,
con un score de riesgo por UM y día, 3 niveles de revisión y una explicación de cada recomendación.

## Instalación (una sola vez)

Terminal de VSCode (`Ctrl + ñ`):

**Windows (PowerShell)**
```powershell
cd enagas
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
**Mac**
```bash
cd enagas
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```
> Mac: LightGBM necesita `brew install libomp` si da error al importarlo.

## Ejecutar (con el entorno activado, dentro de `enagas/`)
```
python datos_sinteticos/generar.py   # 1. datos de prueba de las 5 fuentes + incidencias inyectadas
python -m src.pipeline               # 2. criterios, modelo, niveles, explicaciones, métricas → BD
streamlit run app.py                 # 3. panel DLC en el navegador
```

## Qué hace

| Paso | Archivo | Cómo |
|---|---|---|
| Cruce de fuentes | `src/datos.py` | Neptuno + SLM + ORION + calidad de gas + contrastación → una fila por UM y día. **El día del reto solo se toca esto.** |
| Criterios estándar | `src/criterios.py` | NC, ERROR, MODULA, SERIE, DIF_PCS, DIF_ORION, DIF_ORION_ABS, DIF_HIS con umbrales fijos (`.env`) |
| Criterios adaptativos | `src/criterios.py` | Umbral propio de cada UM = percentil 99,5 de su último año (solo pasado, sin días con incidencia) + 25 % de margen. MODULA/SERIE no alertan si son habituales en esa UM |
| Etiqueta | `src/criterios.py` | Días en que el usuario **ajustó o modificó** (AJUSTES/MODIF, salvo 'Prueba en Serie') = incidencia confirmada |
| Variables | `src/modelo.py` | Exceso sobre el umbral propio, deriva frente a ORION, contador bloqueado, efecto del ramal, contrastación (CONTRAS/CONTRAS_OBS), ajustes previos |
| Modelo | `src/modelo.py` | Isolation Forest (no supervisado) + LightGBM (supervisado). Partición temporal: entrena hasta oct-2024, calibra nov-dic 2024, evalúa ene-jun 2025 |
| 3 niveles | `src/modelo.py` | Validación automática (conserva el 93 % de incidencias fuera), recomendada, prioritaria (≥ 80 % precisión) |
| Explicación | `src/explicar.py` | SHAP nativo de LightGBM → frases con valores reales + causa probable + recomendación |
| IA generativa (opcional) | `src/llm.py` | Solo redacta. JSON validado con Pydantic y rechazo de cifras inventadas |
| Métricas | `src/evaluar.py` | Revisiones/día, precisión, recall, F1, % validación automática, incidencias escapadas, AUC-PR |
| Base de datos | `src/db.py` | SQLite local / PostgreSQL Azure (tablas `um_dia`, `metricas`, `decisiones`) |
| Panel | `app.py` | Bandeja del día por riesgo, detalle con gráficos y tabla de criterios estándar vs propios, trazabilidad por fuente, decisiones DLC, comparativa y vista mensual |

## Resultados con datos sintéticos (120 UM × 18 meses; prueba: 181 días no vistos)

| Enfoque | UM a revisar/día | Precisión | Recall | F1 |
|---|---|---|---|---|
| Regla estándar (actual) | 56,6 | 0,08 | 0,92 | 0,14 |
| Regla adaptativa por UM | 4,0 | 0,66 | 0,57 | 0,61 |
| Modelo IA: prioritaria + recomendada | 23,4 | 0,18 | 0,91 | 0,30 |
| Modelo IA: solo prioritaria | 5,5 | 0,63 | 0,75 | 0,68 |

- **Misma detección que la regla actual (91 % vs 92 %) con un 59 % menos de revisiones manuales.**
- **80 % de UM-día candidatas a validación automática.**
- Detectadas por tipo: fallo de comunicación, PCS erróneo y contador bloqueado 100 %; picos 97 %; derivas 85 %.
- Las derivas que se escapan están en UM muy ruidosas (ciclos combinados, UM pequeñas): una deriva del 2-6 %
  queda dentro de su variación normal. Para ellas, la herramienta es la contrastación periódica.

## El día del reto (datos reales + Azure)
1. **Preguntar al mentor**: umbrales estándar actuales de cada criterio, formato de cada fuente, cómo se
   identifican los ajustes/modificaciones (será la etiqueta) y si hay un listado de incidencias confirmadas.
2. Poner los CSV en una carpeta y `DIR_DATOS=...` en `.env`. Si los nombres de columna difieren, ajustar
   `src/datos.py` o `MAPEO_COLUMNAS` en `config.py`.
3. Cambiar fechas de partición (`FECHA_FIN_ENTRENAMIENTO`, `FECHA_FIN_CALIBRACION`) según el histórico disponible.
4. Azure: `DATABASE_URL` de PostgreSQL y `LLM_PROVEEDOR=azure` + claves en `.env`. El procesado puede ir a
   Databricks copiando `src/` a un notebook (todo es pandas).

## Guion de pitch (6 min)
1. **Problema (40 s)**: hoy los criterios son iguales para todas las UM → 57 de 120 UM en alerta cada día, 92 % falsas alarmas.
2. **Idea (40 s)**: cada UM tiene su "normal". Pestaña *Estándar vs adaptativa*: gráfico de revisiones/día.
3. **Demo bandeja (2 min)**: una prioritaria con PCS erróneo → causa probable, gráfico Neptuno vs ORION, tabla de criterios estándar vs propios, trazabilidad por fuente.
4. **Validación automática (45 s)**: una UM verde donde la regla estándar saltaba → "en esta UM lo normal llega a 3,7 %".
5. **Humano en el bucle (30 s)**: validar / regularizar / escalar → BD → reentrenar (aprendizaje continuo).
6. **Métricas y límites (45 s)**: −59 % revisiones, 80 % automático, qué se escapa y por qué. No sustituye al experto.
7. **Camino a SLM (20 s)**: el score y la explicación se pueden escribir como columnas en SLM.
