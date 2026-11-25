"""
Pipeline de punta a punta:  datos → detección → explicación → métricas → base de datos.

Ejecutar desde la carpeta rbe/:
    python -m src.pipeline
"""
import json
import time

import pandas as pd

from src import datos as carga
from src import db
from src.deteccion import detectar
from src.evaluar import evaluar
from src.explicar import explicacion_plantilla, recomendacion


def main():
    t0 = time.time()
    print("1/4 Cargando datos...")
    d = carga.cargar()
    print(f"    {len(d['ventas']):,} filas de ventas, {d['ventas'].restaurante_id.nunique()} restaurantes")

    print("2/4 Detectando anomalías (patrón semanal + pares + z robusto + cambios de nivel)...")
    alertas, serie, ruido = detectar(d)
    alertas["explicacion"] = alertas.apply(explicacion_plantilla, axis=1)
    alertas["recomendacion"] = alertas.apply(recomendacion, axis=1)
    print(f"    {len(alertas)} alertas  ({(alertas.tipo == 'puntual').sum()} puntuales, "
          f"{(alertas.tipo == 'tendencia').sum()} tendencias)")
    print(f"    Ruido filtrado por calendario/pares: {ruido['alertas_sin_filtrar']} → "
          f"{ruido['alertas_tras_filtrar']} días anómalos ({ruido['ruido_reducido_pct']} % menos)")

    print("3/4 Evaluando...")
    metricas = evaluar(alertas, d["etiquetas"])
    if metricas.empty:
        print("    Sin etiquetas (datos reales): se evaluará con precision@K revisada en la interfaz.")
    else:
        print(metricas.to_string(index=False))

    print("4/4 Guardando en la base de datos...")
    db.inicializar()
    db.guardar_df(alertas, "alertas")
    db.guardar_df(serie, "serie_esperada")
    resumen = pd.DataFrame([{"clave": "ruido", "valor": json.dumps(ruido)},
                            {"clave": "evaluacion", "valor": metricas.to_json(orient="records")}])
    db.guardar_df(resumen, "metricas")
    print(f"Hecho en {time.time() - t0:.0f} s. Ahora: streamlit run app.py")


if __name__ == "__main__":
    main()
