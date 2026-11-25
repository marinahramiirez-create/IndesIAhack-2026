# RBE — Radar de anomalías y cambios de tendencia en ventas

Proyecto **independiente**: tiene su propio entorno, su propia base de datos y su propia app.

## Instalación (una sola vez)

Abre la terminal de VSCode (`Ctrl + ñ`) y ejecuta:

**Windows (PowerShell)**
```powershell
cd rbe
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```
> Si PowerShell bloquea la activación: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` y repite.

**Mac**
```bash
cd rbe
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Ejecutar (con el entorno activado, dentro de `rbe/`)

```
python datos_sinteticos/generar.py     # 1. crea datos de prueba con anomalías inyectadas
python -m src.pipeline                 # 2. detecta, explica, calcula F1 y guarda en la BD
streamlit run app.py                   # 3. abre la demo en el navegador
```

## Qué hace

| Paso | Archivo | Cómo |
|---|---|---|
| Cargar datos | `src/datos.py` | CSV → pandas. **El día del reto solo se toca esto** (o `MAPEO_COLUMNAS` en `config.py`). |
| Patrón esperado | `src/deteccion.py` | Mediana del mismo día de la semana en las 6 semanas anteriores (sin usar el propio día ni el futuro) |
| Quitar ruido | `src/deteccion.py` | Restar lo que les pasa el mismo día a sus pares: marca (campañas) y tipología (festivos), con *median polish*. Si la mayoría de la zona se desvía igual → evento externo, se descarta |
| Puntuales | `src/deteccion.py` | z robusto (mediana/MAD) ≥ 5 **y** desviación ≥ 25 % (estadísticamente raro y relevante para negocio) |
| Tendencias | `src/deteccion.py` | Serie semanal relativa a pares + `ruptures` (PELT), cambio ≥ 10 %. Las puntuales de las semanas siguientes se agrupan en la tendencia |
| Prioridad | `src/deteccion.py` | impacto € × severidad → semáforo alta/media/baja |
| Explicación | `src/explicar.py` | Plantillas con números calculados + recomendación por reglas |
| Copiloto IA (opcional) | `src/llm.py` | Reescribe en lenguaje natural. JSON validado con Pydantic y **rechaza cifras que no estén en los datos** |
| Métricas | `src/evaluar.py` | F1 por tipo, precision@20, % de ruido filtrado |
| Base de datos | `src/db.py` | SQLite local / PostgreSQL Azure (tablas `alertas`, `serie_esperada`, `metricas`, `decisiones`) |
| Interfaz | `app.py` | Bandeja priorizada, gráfico real vs esperado, trazabilidad, aprobar/descartar |

## Pasar a Azure (el día del reto)

Edita `rbe/.env`:
```
DATABASE_URL=postgresql+psycopg://USUARIO:CLAVE@SERVIDOR.postgres.database.azure.com:5432/rbe?sslmode=require
LLM_PROVEEDOR=azure
AZURE_OPENAI_ENDPOINT=https://....openai.azure.com/
AZURE_OPENAI_KEY=...
AZURE_OPENAI_DEPLOYMENT=nombre-del-despliegue
DIR_DATOS=C:/ruta/a/los/csv/reales
```
y vuelve a ejecutar `python -m src.pipeline` y `streamlit run app.py`. No se toca código.

Con datos reales no hay etiquetas → no hay F1 automático. La métrica pasa a ser
**precision@K revisada** (los botones Confirmar / Falsa alarma de la app la van calculando)
y se puede hacer backtesting inyectando anomalías artificiales sobre los datos reales.

### Calibrar umbrales con datos reales
Los umbrales por defecto (`UMBRAL_Z_PUNTUAL=5`, `UMBRAL_DESVIACION_MIN=0.25`) se eligieron
probando combinaciones contra las anomalías sintéticas. Con datos reales pueden cambiarse en el `.env`
sin tocar código. Regla práctica: si la bandeja tiene demasiadas alertas, sube `UMBRAL_Z_PUNTUAL`;
si se escapan caídas importantes, baja `UMBRAL_DESVIACION_MIN`. **Preguntar al mentor el primer día**
qué desviación considera RBE relevante.

## Resultados con datos sintéticos (30 restaurantes × 3 canales × 18 meses)
| Métrica | Valor |
|---|---|
| F1 global | 0,89 |
| F1 puntuales / tendencias | 0,88 / 0,94 |
| precision@20 | 1,00 |
| Ruido filtrado (calendario, campañas, eventos de zona) | 84 % |

## Guion de pitch (6 min)

1. **Problema (30 s)**: cientos de restaurantes × canales × días. Las alertas por umbral fijo saltan con cada festivo o campaña → nadie las mira.
2. **Idea (45 s)**: "un restaurante es raro si se comporta distinto a sus parecidos ese mismo día". Enseñar la pestaña *Calidad*: X % de ruido eliminado.
3. **Demo bandeja (2 min)**: la primera alerta (mayor € en riesgo). Gráfico real vs esperado. Explicación: ¿tickets o ticket medio? Recomendación. Trazabilidad.
4. **Cambio de tendencia (1 min)**: una alerta de tipo tendencia con su impacto acumulado.
5. **Humano en el bucle (30 s)**: confirmar / falsa alarma → se guarda en BD y mide la precisión real.
6. **Métrica (45 s)**: F1 por tipo y precision@20. La IA solo redacta: si inventa una cifra, se rechaza.
7. **Siguiente paso (30 s)**: alertas diarias por email al gerente de zona; aprender umbrales con las decisiones.
