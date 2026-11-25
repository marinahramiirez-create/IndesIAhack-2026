"""
Genera datos de prueba que imitan lo que dará Acerinox el día del reto:

  salida/catalogo.md                 catálogo de productos (el real será un PDF): grados, acabados, formatos, usos
  salida/stock.csv                   inventario: un bulto por fila, con ID único y especificaciones
  salida/reglas_transformacion.txt   operaciones permitidas sobre un bulto (el real llegará como TXT)
  salida/casos_prueba.csv            peticiones coloquiales + lo que el asistente debería entender/hacer

El catálogo usa información técnica pública y general del acero inoxidable (EN 10088): no son datos de Acerinox.
Ejecutar desde acerinox/:   python datos_sinteticos/generar.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

SALIDA = Path(__file__).resolve().parent / "salida"

CATALOGO = """# Catálogo de productos planos de acero inoxidable (muestra sintética)

## 1. Grados (composición y usos)

### 1.1 AISI 304 · EN 1.4301
Austenítico al cromo-níquel (18 % Cr, 8 % Ni, conocido como "18/8" o "A2"). Grado de uso general.
Buena resistencia a la corrosión en ambientes interiores, urbanos y rurales. Apto para contacto con alimentos.
Excelente conformabilidad y soldabilidad. No magnético en estado recocido.
No recomendado en ambientes marinos o con cloruros.

### 1.2 AISI 304L · EN 1.4307
Versión de bajo carbono del 304. Recomendado para soldadura de espesores gruesos (evita la sensibilización).

### 1.3 AISI 316L · EN 1.4404
Austenítico con molibdeno (2-2,5 % Mo), conocido como "A4". Mayor resistencia a la corrosión por picaduras
en presencia de cloruros: ambientes marinos y costeros, piscinas, industria química y alimentaria. Bajo carbono: buena soldabilidad.

### 1.4 AISI 430 · EN 1.4016
Ferrítico al 17 % Cr, sin níquel: magnético y más económico. Electrodomésticos, menaje y decoración interior.
No recomendado para exteriores agresivos.

### 1.5 AISI 441 · EN 1.4509
Ferrítico estabilizado (Ti, Nb), magnético. Buena resistencia a la oxidación a alta temperatura y a la fatiga
térmica: sistemas de escape de automoción, quemadores.

### 1.6 Dúplex 2205 · EN 1.4462
Austeno-ferrítico. Límite elástico aproximadamente el doble que el 304 y excelente resistencia a cloruros y a la
corrosión bajo tensión: offshore, desalinizadoras, depósitos químicos.

## 2. Acabados superficiales (EN 10088-2)

### 2.1 1D
Laminado en caliente, recocido y decapado. Superficie mate y rugosa. Habitual en espesores de 3 mm o más.
### 2.2 2D
Laminado en frío, recocido y decapado. Superficie mate.
### 2.3 2B
Laminado en frío, recocido, decapado y skin-pass. Superficie lisa y semibrillante. Acabado estándar más común.
### 2.4 BA (2R)
Laminado en frío y recocido brillante en atmósfera controlada. Superficie brillante y reflectante.
Solo se obtiene en fábrica.
### 2.5 Satinado (2J / Nº4)
Cepillado o pulido con abrasivo (grano 180-240). Aspecto mate sedoso. Se obtiene a partir de 2B o BA.
### 2.6 Espejo (2P / Nº8)
Pulido especular de alta reflexión. Se obtiene a partir de BA.

## 3. Formatos
### 3.1 Bobina
Producto enrollado. Ancho de 1000 a 1500 mm.
### 3.2 Fleje
Bobina estrecha (ancho inferior a 600 mm) obtenida por corte longitudinal.
### 3.3 Chapa
Hojas planas cortadas a largo, suministradas en paquetes. Medidas habituales 1000x2000, 1250x2500, 1500x3000, 2000x6000 mm.

## 4. Gama de espesores disponibles
0,5 · 0,6 · 0,8 · 1,0 · 1,2 · 1,5 · 2,0 · 3,0 · 4,0 · 5,0 · 6,0 mm.
"""

REGLAS_TXT = """REGLAS DE TRANSFORMACIÓN DE BULTOS (muestra sintética)

R1 CORTE LONGITUDINAL (slitter): una bobina o fleje se corta en tiras de ancho menor.
   - Refilado mínimo: 10 mm del ancho original se pierden siempre.
   - Ancho mínimo de tira: 20 mm. Si el ancho resultante es inferior a 600 mm, el producto es fleje.
R2 CORTE TRANSVERSAL (línea de corte a largo): una bobina se corta en chapas.
   - Largo de chapa entre 500 y 6000 mm. El ancho de la chapa es el de la bobina. Merma estimada 1 %.
R3 CIZALLA: una chapa se corta a medidas menores (ancho y/o largo). Nunca se puede aumentar una medida.
R4 SATINADO: se puede satinar material con acabado 2B o BA, espesor mínimo 0,5 mm.
R5 PULIDO ESPEJO: solo a partir de acabado BA y espesor máximo 3,0 mm.
R6 FILM PROTECTOR: se puede añadir film de PVC a cualquier bulto.

NO PERMITIDO:
   - Cambiar el grado (composición) o el espesor de un bulto.
   - Obtener acabado BA, 2B, 2D o 1D en almacén (son acabados de fábrica).
   - Aumentar el ancho o el largo.
   - Usar bultos reservados o bloqueados por calidad.
"""

# --------------------------------------------------------------- bultos diseñados para los casos de prueba
# (id, formato, grado, acabado, espesor, ancho, largo, peso_kg, n_hojas, almacen, estado, fecha_entrada)
DISENADOS = [
    ("B-1001", "chapa", "316L", "BA", 2.0, 1250, 2500, 0, 20, "Algeciras", "disponible", "2025-03-10"),
    ("B-1002", "chapa", "316L", "BA", 2.0, 1250, 2500, 0, 20, "Algeciras", "disponible", "2026-01-15"),
    ("B-1010", "bobina", "304", "2B", 1.0, 1500, None, 8000, 0, "Algeciras", "disponible", "2025-06-01"),
    ("B-1011", "bobina", "304", "2B", 1.0, 1250, None, 22000, 0, "Algeciras", "disponible", "2025-02-01"),
    ("B-1020", "bobina", "316L", "2B", 0.8, 1250, None, 6000, 0, "Algeciras", "disponible", "2025-09-01"),
    ("B-1021", "bobina", "316L", "2B", 0.8, 1000, None, 4000, 0, "Ponferrada", "disponible", "2025-05-01"),
    ("B-1030", "chapa", "430", "2B", 1.5, 1000, 2000, 0, 50, "Algeciras", "disponible", "2025-07-01"),
    ("B-1031", "chapa", "430", "2D", 1.5, 1000, 2000, 0, 50, "Algeciras", "disponible", "2025-01-01"),
    ("B-1040", "chapa", "304", "BA", 1.0, 1000, 2000, 0, 10, "Igualada", "disponible", "2025-08-01"),
    ("B-1041", "chapa", "304", "2B", 1.0, 1000, 2000, 0, 30, "Igualada", "disponible", "2025-04-01"),
    ("B-1050", "chapa", "441", "2D", 1.2, 1250, 2500, 0, 40, "Algeciras", "disponible", "2025-10-01"),
    ("B-1060", "chapa", "2205", "2B", 3.0, 2000, 6000, 0, 8, "Algeciras", "reservado", "2025-03-01"),
    ("B-1061", "chapa", "2205", "2B", 3.0, 1500, 3000, 0, 12, "Algeciras", "disponible", "2025-03-01"),
    ("B-1070", "bobina", "430", "2B", 0.6, 1250, None, 5000, 0, "Algeciras", "disponible", "2025-11-01"),
    ("B-1080", "chapa", "316L", "1D", 4.0, 2000, 6000, 0, 10, "Algeciras", "disponible", "2025-06-15"),
    ("B-1100", "chapa", "304", "BA", 2.0, 1250, 2500, 0, 15, "Igualada", "disponible", "2025-12-01"),
]

# texto, grado(s) esperados, acabado, espesor, formato, ancho, largo, cantidad_kg, piezas, acción, bulto esperado
CASOS = [
    ("Una chapa brillante de 2 milímetros que aguante el mar, 1250x2500, 10 chapas",
     "316L|2205", "BA", 2.0, "chapa", 1250, 2500, None, 10, "buscar", "B-1001"),
    ("Necesito bobina de 304 2B de 1 mm, unas 5 toneladas", "304", "2B", 1.0, "bobina", None, None, 5000, None, "buscar", "B-1010"),
    ("Fleje de 316L 2B de 0,8 mm y 300 mm de ancho, 2 toneladas", "316L", "2B", 0.8, "fleje", 300, None, 2000, None, "buscar", "B-1020"),
    ("Chapa satinada de 430 de 1,5 mm, 1000x2000, 30 hojas", "430", "satinado", 1.5, "chapa", 1000, 2000, None, 30, "buscar", "B-1030"),
    ("Algo de acero que aguante el mar", "316L|2205", None, None, None, None, None, None, None, "repreguntar", ""),
    ("Chapa de acero inoxidable mágico que no se raye nunca de 2mm", None, None, 2.0, "chapa", None, None, None, None, "rechazar", ""),
    ("Bobina de 904L BA de 1 mm", None, "BA", 1.0, "bobina", None, None, None, None, "rechazar", ""),
    ("Chapa espejo de 304 de 1 mm, 1000x2000, 5 chapas", "304", "espejo", 1.0, "chapa", 1000, 2000, None, 5, "buscar", "B-1040"),
    ("Necesito chapa para tubos de escape, 2D de 1,2 mm, 1250x2500, 20 hojas", "441", "2D", 1.2, "chapa", 1250, 2500, None, 20, "buscar", "B-1050"),
    ("Chapa dúplex 2205 2B de 3 mm, 2000x6000, 4 chapas", "2205", "2B", 3.0, "chapa", 2000, 6000, None, 4, "sin_stock", ""),
    ("Bobina magnética y barata de 0,6 en 2B", "430", "2B", 0.6, "bobina", None, None, None, None, "buscar", "B-1070"),
    ("Chapa de 316 de 4 mm 1500x3000 mate laminado en caliente, 6 piezas", "316L", "1D", 4.0, "chapa", 1500, 3000, None, 6, "buscar", "B-1080"),
    ("Una chapa brillante de 2 milímetros", None, "BA", 2.0, "chapa", None, None, None, None, "buscar", ""),
    ("Me hace falta una plancha de inox 18/8 brillo de dos milímetros, medidas 1250 por 2500, 10 unidades",
     "304", "BA", 2.0, "chapa", 1250, 2500, None, 10, "buscar", "B-1100"),
    ("¿Tienes rollos de 316L 2B de 0,8?", "316L", "2B", 0.8, "bobina", None, None, None, None, "buscar", ""),
]

GRADOS = ["304", "304L", "316L", "430", "441", "2205"]
ACABADOS = {"bobina": ["2B", "BA", "2D"], "chapa": ["2B", "BA", "2D", "1D", "satinado"]}
ESPESORES = [0.5, 0.6, 0.8, 1.0, 1.2, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0]
MEDIDAS = [(1000, 2000), (1250, 2500), (1500, 3000)]
DENSIDAD = {"304": 7.93, "304L": 7.93, "316L": 8.0, "430": 7.7, "441": 7.7, "2205": 7.8}


def peso_chapas(grado, e, a, l, n):
    return round(e * a * l * n * DENSIDAD[grado] / 1e6, 0)


def relleno(n: int, rng) -> list[tuple]:
    """Bultos aleatorios que NO repiten las combinaciones de los casos de prueba (para que la respuesta esperada sea única)."""
    usados = {(d[2], d[3], d[4]) for d in DISENADOS} | {("2205", "BA", 2.0), ("441", "2B", 0.6), ("430", "satinado", 1.5)}
    filas, i = [], 0
    while len(filas) < n:
        i += 1
        formato = rng.choice(["bobina", "chapa"])
        grado = rng.choice(GRADOS)
        acabado = rng.choice(ACABADOS[formato])
        e = float(rng.choice(ESPESORES))
        if acabado == "1D" and e < 3:
            e = 3.0
        if acabado != "1D" and e > 3:
            e = 2.0
        if (grado, acabado, e) in usados:
            continue
        estado = rng.choice(["disponible"] * 8 + ["reservado", "bloqueado_calidad"])
        fecha = str(pd.Timestamp("2024-06-01") + pd.Timedelta(days=int(rng.integers(0, 540))))[:10]
        if formato == "bobina":
            filas.append((f"B-{2000 + i}", "bobina", grado, acabado, e, int(rng.choice([1000, 1250, 1500])), None,
                          int(rng.integers(3, 20)) * 1000, 0, rng.choice(["Algeciras", "Ponferrada", "Igualada"]), estado, fecha))
        else:
            a, l = MEDIDAS[rng.integers(0, len(MEDIDAS))]
            filas.append((f"B-{2000 + i}", "chapa", grado, acabado, e, a, l, 0, int(rng.integers(5, 60)),
                          rng.choice(["Algeciras", "Ponferrada", "Igualada"]), estado, fecha))
    return filas


def main():
    SALIDA.mkdir(exist_ok=True)
    rng = np.random.default_rng(7)
    cols = ["id_bulto", "formato", "grado", "acabado", "espesor_mm", "ancho_mm", "largo_mm", "peso_kg",
            "n_hojas", "almacen", "estado", "fecha_entrada"]
    stock = pd.DataFrame(DISENADOS + relleno(45, rng), columns=cols)
    stock["peso_kg"] = stock["peso_kg"].astype(float)
    es_chapa = stock.formato == "chapa"
    stock.loc[es_chapa, "peso_kg"] = [peso_chapas(r.grado, r.espesor_mm, r.ancho_mm, r.largo_mm, r.n_hojas)
                                      for r in stock[es_chapa].itertuples()]
    stock["norma_en"] = stock.grado.map({"304": "1.4301", "304L": "1.4307", "316L": "1.4404", "430": "1.4016",
                                         "441": "1.4509", "2205": "1.4462"})
    stock.to_csv(SALIDA / "stock.csv", index=False)
    (SALIDA / "catalogo.md").write_text(CATALOGO, encoding="utf-8")
    (SALIDA / "reglas_transformacion.txt").write_text(REGLAS_TXT, encoding="utf-8")
    pd.DataFrame(CASOS, columns=["texto", "grado", "acabado", "espesor_mm", "formato", "ancho_mm", "largo_mm",
                                 "cantidad_kg", "piezas", "accion", "bulto_esperado"]).to_csv(SALIDA / "casos_prueba.csv", index=False)
    print(f"{len(stock)} bultos ({(stock.estado == 'disponible').sum()} disponibles), catálogo, reglas y "
          f"{len(CASOS)} casos de prueba → {SALIDA}")


if __name__ == "__main__":
    main()
