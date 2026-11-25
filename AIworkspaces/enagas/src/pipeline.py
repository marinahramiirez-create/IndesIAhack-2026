"""
Pipeline de punta a punta:
  5 fuentes → tabla UM-día → criterios estándar y adaptativos → variables → modelo (score + nivel)
  → explicaciones → métricas → base de datos.

Ejecutar desde la carpeta enagas/:
    python -m src.pipeline
"""
import json
import time

import numpy as np
import pandas as pd

from src import criterios, db, explicar, modelo
from src import datos as carga
from src.evaluar import evaluar


def main():
    t0 = time.time()
    print("1/6 Cargando las 5 fuentes (Neptuno, SLM, ORION, calidad de gas, contrastación)...")
    d = carga.cargar()
    df = carga.tabla_um_dia(d)
    print(f"    {df.um_id.nunique()} UM × {df.fecha.nunique()} días = {len(df):,} UM-día")

    print("2/6 Criterios estándar y adaptativos por UM...")
    df = criterios.calcular_criterios(df)
    df = criterios.reglas_estandar(df)
    df = criterios.reglas_adaptativas(df)

    print("3/6 Variables y modelo (Isolation Forest + LightGBM)...")
    df = modelo.construir_variables(df, d["contrastacion"])
    df, info = modelo.entrenar_y_puntuar(df)
    print(f"    umbral validación automática < {info['umbral_auto']:.3f} ≤ recomendada < "
          f"{info['umbral_prioritaria']:.3f} ≤ prioritaria")

    if d["etiquetas"] is not None:
        et = d["etiquetas"][["um_id", "fecha", "tipo_incidencia"]]
        df = df.merge(et, on=["um_id", "fecha"], how="left")
        df["incidencia_real"] = df["tipo_incidencia"].notna()

    print("4/6 Evaluando en el periodo de prueba (no visto por el modelo)...")
    m = evaluar(df)
    comp = pd.DataFrame(m["comparativa"])
    cols = ["enfoque", "revisiones_dia"] + [c for c in comp if c.endswith("incidencia_real") or
                                            (c.endswith("etiqueta_proxy") and "incidencia_real" not in "".join(comp.columns))]
    print(comp[cols].to_string(index=False))
    print("    " + json.dumps(m["resumen"], ensure_ascii=False))
    if m["recall_por_tipo"]:
        print("    detectadas por tipo:", m["recall_por_tipo"])

    print("5/6 Redactando explicaciones...")
    vista = df[df["particion"] != "entrenamiento"].copy()  # el panel muestra calibración + prueba
    vista = explicar.aplicar(vista)

    print("6/6 Guardando en la base de datos...")
    db.inicializar()
    vista = vista.drop(columns=[c for c in ["fecha_contraste"] if c in vista])
    for c in vista.columns:
        if vista[c].dtype == bool:
            vista[c] = vista[c].astype(int)
    vista = vista.replace([np.inf, -np.inf], np.nan)
    db.guardar_df(vista, "um_dia")
    m["modelo"] = info
    db.guardar_df(pd.DataFrame([{"clave": k, "valor": json.dumps(v, ensure_ascii=False, default=str)}
                                for k, v in m.items()]), "metricas")
    print(f"Hecho en {time.time() - t0:.0f} s. Ahora: streamlit run app.py")


if __name__ == "__main__":
    main()
