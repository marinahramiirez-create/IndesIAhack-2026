"""
Métricas con el banco de peticiones de prueba (casos_prueba.csv), una por criterio del jurado:

  - Traducción al dato:      % de campos de la ficha bien interpretados
  - Preguntas con sentido:   % de acciones correctas (buscar / repreguntar / rechazar / sin stock)
  - Prohibido inventar:      nº de bultos inventados o no disponibles propuestos (debe ser 0)
  - Identificación correcta: % de casos donde la primera propuesta es el bulto esperado

Ejecutar desde acerinox/:   python -m src.evaluar
"""
import json

import pandas as pd

import config
from src import db, inventario
from src.asistente import Conversacion

CAMPOS = ["grado", "acabado", "espesor_mm", "formato", "ancho_mm", "largo_mm", "cantidad_kg", "piezas"]


def _valor(f, campo):
    if campo == "grado":
        return "|".join(sorted(f.grados)) if f.grados else None
    return getattr(f, campo)


def _igual(esperado, obtenido, campo) -> bool:
    if pd.isna(esperado):
        return obtenido is None
    if campo == "grado":
        return obtenido == "|".join(sorted(str(esperado).split("|")))
    if campo in ("acabado", "formato"):
        return obtenido == esperado
    return obtenido is not None and abs(float(obtenido) - float(esperado)) < 1e-6


def evaluar() -> tuple[pd.DataFrame, dict]:
    casos = pd.read_csv(config.DIR_DATOS / config.CASOS, dtype={"grado": str})
    ids_stock = set(inventario.stock().id_bulto)
    filas = []
    for c in casos.itertuples():
        conv = Conversacion()
        r = conv.responder(c.texto)
        f = r["ficha"]
        props = (r["busqueda"] or {}).get("propuestas", [])
        accion = r["accion"]
        if accion == "buscar" and not props:
            accion = "sin_stock"
        campos_ok = {k: _igual(getattr(c, k), _valor(f, k), k) for k in CAMPOS}
        inventados = [p["id_bulto"] for p in props if p["id_bulto"] not in ids_stock or p["estado"] != "disponible"]
        top = props[0]["id_bulto"] if props else ""
        filas.append({
            "texto": c.texto, "accion_esperada": c.accion, "accion": accion, "accion_ok": accion == c.accion,
            "campos_ok": sum(campos_ok.values()), "campos_mal": ", ".join(k for k, v in campos_ok.items() if not v),
            "bulto_esperado": c.bulto_esperado if isinstance(c.bulto_esperado, str) else "",
            "bulto_propuesto": top, "errores_validacion": len(r["errores_validacion"]), "inventados": len(inventados),
            "ficha": json.dumps({k: _valor(f, k) for k in CAMPOS}, ensure_ascii=False),
        })
    df = pd.DataFrame(filas)
    con_bulto = df[df.bulto_esperado != ""]
    m = {
        "casos": len(df),
        "traduccion_campos_pct": round(df.campos_ok.sum() / (len(df) * len(CAMPOS)), 3),
        "accion_correcta_pct": round(df.accion_ok.mean(), 3),
        "bulto_correcto_pct": round((con_bulto.bulto_esperado == con_bulto.bulto_propuesto).mean(), 3) if len(con_bulto) else None,
        "bultos_inventados": int(df.inventados.sum()),
        "errores_validador": int(df.errores_validacion.sum()),
    }
    return df, m


if __name__ == "__main__":
    inventario.cargar_stock_en_bd()
    df, m = evaluar()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 60)
    print(df[["texto", "accion_esperada", "accion", "campos_mal", "bulto_esperado", "bulto_propuesto"]].to_string())
    print()
    print(f"Traducción al dato (campos bien interpretados): {m['traduccion_campos_pct']:.0%}")
    print(f"Acción correcta (buscar/repreguntar/rechazar):  {m['accion_correcta_pct']:.0%}")
    print(f"Bulto correcto en primera posición:             {m['bulto_correcto_pct']:.0%}")
    print(f"Bultos inventados o no disponibles propuestos:  {m['bultos_inventados']}")
    db.guardar_df(df, "evaluacion")
    db.guardar_df(pd.DataFrame([{"clave": k, "valor": json.dumps(v)} for k, v in m.items()]), "metricas")
