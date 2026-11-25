# Acerinox — Asistente inteligente de inventario comercial (voz y texto)

Proyecto **independiente**: tiene su propio entorno, su propia base de datos y su propia app.
El comercial escribe (o dice) la petición como la diría el cliente — *"una chapa brillante de 2 mm que aguante el mar"* —
y el asistente la traduce a especificaciones técnicas, busca el bulto en el stock o propone cómo transformar uno
según las reglas de negocio, sin inventar nada que no esté en el catálogo o en el inventario.

## Instalación (una sola vez)

**Windows (PowerShell)**
```powershell
cd acerinox
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
copy .env.example .env
```
**Mac**
```bash
cd acerinox
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Ejecutar (con el entorno activado, dentro de `acerinox/`)
```
python datos_sinteticos/generar.py     # 1. catálogo, stock, reglas y casos de prueba
python -m src.evaluar                  # 2. métricas con el banco de peticiones de prueba
python -m streamlit run app.py         # 3. asistente en el navegador
```
> `python -m streamlit` funciona en todos los equipos (en los que tienen Smart App Control, `streamlit run` falla).

## Qué hace

| Paso | Archivo | Cómo |
|---|---|---|
| Catálogo | `src/catalogo.py` | Valores válidos (grados, acabados, formatos, espesores) + diccionario coloquial → técnico. **Cada traducción cita su sección del catálogo** |
| Intérprete | `src/interprete.py` | Frase → ficha (grado, acabado, espesor, formato, medidas, cantidad) con evidencias. Entiende "18/8", "brillo", "rollo", "dos milímetros", "1250 por 2500", "aguante el mar" → 316L/2205… |
| Preguntas con sentido | `src/interprete.py` / `src/asistente.py` | Sin formato o espesor → repregunta. Sin grado/acabado/cantidad → busca igual y pregunta para afinar. Conversación de varios turnos |
| Prohibido inventar | `src/catalogo.py` | Rechaza grados fuera de catálogo (904L, 310S) y propiedades imposibles ("acero mágico", "que no se raye nunca") |
| Búsqueda | `src/inventario.py` | **Consulta SQL determinista** (grado, espesor, disponible) sobre la BD de stock |
| Transformaciones | `src/transformaciones.py` | Reglas R1–R6 del TXT como código: corte longitudinal, corte transversal, cizalla, satinado, espejo, film. Nada fuera de ellas |
| Criterio de negocio | `src/inventario.py` | Cubre la cantidad > exacto > menos operaciones > menos merma > no romper bultos grandes > FIFO |
| Validador | `src/inventario.py` | Antes de enseñar una propuesta comprueba otra vez: el ID existe, está disponible, grado/espesor correctos y transformación posible |
| LLM (opcional) | `src/llm.py` | Rellena huecos de la ficha (validado contra catálogo; el número debe aparecer en lo dicho), redacta más natural (rechaza IDs o cifras nuevas), voz con Whisper |
| Demanda no atendida | `src/db.py` + app | Lo que se pidió y no había queda registrado → compras/producción |
| Interfaz | `app.py` | Chat, voz, ficha con evidencias, tarjetas de bultos con operaciones y merma, SQL ejecutado, stock, demanda, métricas, catálogo |

## Resultados (sin LLM, solo reglas)

| Conjunto | Traducción al dato | Acción correcta | Bulto correcto | Bultos inventados |
|---|---|---|---|---|
| Casos de prueba (15) | 100 % | 100 % | 100 % | 0 |
| **Prueba ciega** (8 frases nuevas) | 98 % | 100 % | 100 % | 0 |

Ojo: los casos y el código se escribieron a la vez, así que el 100 % está inflado. La prueba ciega
(`python datos_sinteticos/prueba_ciega.py`) es más honesta, y tiene un fallo real: en *"quiero 8"* no entiende
que son 8 chapas. Ese tipo de hueco es el que cubre el LLM el día del reto.

## El día del reto
1. **Preguntar al mentor**: columnas del stock, qué estados hay (reservado, bloqueado…), formato de las reglas TXT,
   y qué criterio de negocio prefieren (¿FIFO? ¿no romper bultos grandes? ¿almacén más cercano?).
2. Stock: poner el CSV/export en `DIR_DATOS` y renombrar columnas en `MAPEO_COLUMNAS` (`config.py`).
3. Catálogo: `CATALOGO=catalogo.pdf`. Revisar `GRADOS`, `ACABADOS` y `PROPIEDADES` en `src/catalogo.py` con el PDF real
   (las citas deben apuntar a sus secciones o páginas).
4. Reglas: leer el TXT y ajustar las constantes de `src/transformaciones.py`.
5. Escribir 15-20 peticiones reales del mentor en `casos_prueba.csv` y medir con `python -m src.evaluar`.
6. LLM y voz: `LLM_PROVEEDOR=azure` + claves + `AZURE_OPENAI_DEPLOYMENT` y `AZURE_OPENAI_WHISPER`.

## Guion de pitch (6 min)
1. **Problema (40 s)**: el comercial traduce a mano "chapa brillante que aguante el mar" a 316L BA y busca en varios sistemas.
2. **Demo principal (2 min)**: esa frase → ficha con evidencias (cada valor con su cita al catálogo) → B-1001, encaje exacto, FIFO.
3. **Transformación (1 min)**: "fleje de 316L de 300 mm" → no hay fleje; propone cortar la bobina B-1020 en 4 tiras (R1), merma 4 %, mejor que B-1021 (10 %).
4. **Sentido común (40 s)**: "algo que aguante el mar" → repregunta formato y espesor; la conversación recuerda lo anterior.
5. **Prohibido inventar (40 s)**: "904L" y "acero mágico que no se raye" → rechazo explicado. Validador: 0 bultos inventados.
6. **Negocio (40 s)**: criterio de ranking (no romper bultos grandes, FIFO) y demanda no atendida para compras.
7. **Métricas y siguiente paso (20 s)**: tabla de métricas, voz con Whisper, conexión a la BD real.
