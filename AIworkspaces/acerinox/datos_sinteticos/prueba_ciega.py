"""
Prueba ciega: peticiones redactadas de otra forma, escritas sin mirar el intérprete y sin ajustarlo después.
Ejecutar desde acerinox/ (después de generar.py):
    python datos_sinteticos/prueba_ciega.py
    (PowerShell)  $env:CASOS="casos_ciegos.csv"; python -m src.evaluar; Remove-Item Env:CASOS
"""
from pathlib import Path

import pandas as pd

CASOS = [
    ("Busco planchas de inoxidable brillantes, dos mm, para una terraza frente al mar, tamaño 1250 x 2500, quiero 8",
     "316L|2205", "BA", 2.0, "chapa", 1250, 2500, None, 8, "buscar", "B-1001"),
    ("Quiero 3 toneladas de rollo en 304 acabado 2B, espesor un milímetro", "304", "2B", 1.0, "bobina", None, None, 3000, None, "buscar", "B-1010"),
    ("¿Tenéis tiras de 316L de 0.8 de 150 mm de ancho?", "316L", None, 0.8, "fleje", 150, None, None, None, "buscar", ""),
    ("Necesito material para una cocina industrial, chapa de 1,5 satinada", "304|316L", "satinado", 1.5, "chapa", None, None, None, None, "sin_stock", ""),
    ("Dame acero inoxidable de grado 310S en bobina de 2 mm", None, None, 2.0, "bobina", None, None, None, None, "rechazar", ""),
    ("Hola, necesito chapa", None, None, None, "chapa", None, None, None, None, "repreguntar", ""),
    ("Una bobina de acero que no se oxide nunca, 1 mm 2B", None, "2B", 1.0, "bobina", None, None, None, None, "rechazar", ""),
    ("Me pasas lo que tengas en 441 para un horno, hoja de 1,2 mate, 1250x2500, 10 piezas",
     "441", "2D", 1.2, "chapa", 1250, 2500, None, 10, "buscar", "B-1050"),
]

cols = ["texto", "grado", "acabado", "espesor_mm", "formato", "ancho_mm", "largo_mm", "cantidad_kg", "piezas", "accion", "bulto_esperado"]
salida = Path(__file__).resolve().parent / "salida" / "casos_ciegos.csv"
pd.DataFrame(CASOS, columns=cols).to_csv(salida, index=False)
print(f"{len(CASOS)} casos → {salida}")
