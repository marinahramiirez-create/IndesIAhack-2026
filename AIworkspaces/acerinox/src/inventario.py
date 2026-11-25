"""
Inventario: ficha técnica → propuestas de bultos (exactos o transformables), ordenadas con criterio de negocio.

  1. Filtro SQL determinista sobre la BD de stock: grado, espesor (no se puede cambiar) y estado = disponible.
  2. Para cada bulto: ¿encaja tal cual? ¿o con qué operaciones de las reglas? (src/transformaciones.py)
  3. Ranking (criterio "en la piel de Acerinox"):
       cubre la cantidad > encaje exacto > menos operaciones > menos merma > no romper un bulto grande
       (más de FACTOR_BULTO_GRANDE veces lo pedido) > el más antiguo primero (FIFO)
  4. Validador: comprueba otra vez cada propuesta contra la BD y las reglas antes de enseñarla.
"""
import math
from functools import lru_cache

import pandas as pd

import config
from src import db, transformaciones as tr
from src.interprete import Ficha

DENSIDAD = {"304": 7.93, "304L": 7.93, "316L": 8.0, "430": 7.7, "441": 7.7, "2205": 7.8}


def cargar_stock_en_bd():
    df = pd.read_csv(config.DIR_DATOS / config.STOCK).rename(columns=config.MAPEO_COLUMNAS)
    df["grado"] = df["grado"].astype(str)
    db.guardar_df(df, "stock")
    stock.cache_clear()
    return df


@lru_cache(maxsize=1)
def stock() -> pd.DataFrame:
    if not db.existe_tabla("stock"):
        cargar_stock_en_bd()
    return db.leer_df("SELECT * FROM stock")


def _sql_candidatos(f: Ficha, incluir_no_disponibles: bool = False) -> pd.DataFrame:
    condiciones = ["ABS(espesor_mm - :e) <= :tol"]
    params = {"e": f.espesor_mm, "tol": config.TOLERANCIA_ESPESOR_MM}
    if f.grados:
        marcas = ", ".join(f":g{i}" for i in range(len(f.grados)))
        condiciones.append(f"grado IN ({marcas})")
        params.update({f"g{i}": g for i, g in enumerate(f.grados)})
    if not incluir_no_disponibles:
        condiciones.append("estado = 'disponible'")
    sql = "SELECT * FROM stock WHERE " + " AND ".join(condiciones)
    return db.leer_df(sql, params), sql, params


def peso_pedido(f: Ficha, grado: str) -> float | None:
    if f.cantidad_kg:
        return f.cantidad_kg
    if f.piezas and f.ancho_mm and f.largo_mm:
        return f.espesor_mm * f.ancho_mm * f.largo_mm * f.piezas * DENSIDAD.get(grado, 7.9) / 1e6
    return None


def evaluar_bulto(b: dict, f: Ficha) -> dict:
    """Encaje de un bulto con la ficha: exacto / transformable / imposible (con motivo)."""
    ops_ac, motivo = tr.acabado(b, None if f.acabado_indiferente else f.acabado)
    if ops_ac is None:
        return {"encaje": "imposible", "motivo": motivo}
    ops_med, merma, k, motivo = tr.formato_y_medidas(b, f.formato, f.ancho_mm, f.largo_mm)
    if ops_med is None:
        return {"encaje": "imposible", "motivo": motivo}
    ops = ops_med + ops_ac

    # ¿cubre la cantidad?
    cubre, detalle_cant = True, ""
    if b["formato"] == "chapa" and f.formato == "chapa" and f.piezas:
        disponibles = int(b["n_hojas"]) * k
        cubre = disponibles >= f.piezas
        hojas = math.ceil(f.piezas / k)
        detalle_cant = f"usa {hojas} de {int(b['n_hojas'])} hojas" + ("" if cubre else f" (solo salen {disponibles} piezas)")
    else:
        necesario = peso_pedido(f, b["grado"])
        util = b["peso_kg"] * (1 - merma)
        if necesario:
            cubre = util >= necesario
            detalle_cant = f"{util:,.0f} kg útiles para {necesario:,.0f} kg pedidos".replace(",", ".")
    necesario = peso_pedido(f, b["grado"])
    grande = bool(necesario and b["peso_kg"] > config.FACTOR_BULTO_GRANDE * necesario)
    return {"encaje": "exacto" if not ops else "transformable", "operaciones": ops, "merma": round(merma, 3),
            "cubre_cantidad": cubre, "detalle_cantidad": detalle_cant, "bulto_grande": grande, "motivo": ""}


def buscar(f: Ficha) -> dict:
    """Devuelve {'propuestas': [...], 'descartados': [...], 'no_disponibles': [...], 'sql': ...}."""
    cand, sql, params = _sql_candidatos(f)
    propuestas, descartados = [], []
    for b in cand.to_dict("records"):
        e = evaluar_bulto(b, f)
        if e["encaje"] == "imposible":
            descartados.append({"id_bulto": b["id_bulto"], "motivo": e["motivo"]})
            continue
        propuestas.append({**b, **e})
    propuestas.sort(key=lambda p: (not p["cubre_cantidad"], p["encaje"] != "exacto", len(p["operaciones"]),
                                   p["merma"], p["bulto_grande"], p["fecha_entrada"]))
    for i, p in enumerate(propuestas):
        p["motivo_ranking"] = _motivo(p, propuestas, i)

    # Bultos que encajarían pero no se pueden usar (reservados / bloqueados): útil para el comercial
    todos, _, _ = _sql_candidatos(f, incluir_no_disponibles=True)
    no_disp = [{"id_bulto": b["id_bulto"], "estado": b["estado"]} for b in todos.to_dict("records")
               if b["estado"] != "disponible" and evaluar_bulto(b, f)["encaje"] != "imposible"]
    return {"propuestas": propuestas[: config.MAX_PROPUESTAS], "n_encajan": len(propuestas),
            "descartados": descartados, "no_disponibles": no_disp, "sql": sql, "params": params}


def _motivo(p: dict, todas: list[dict], i: int) -> str:
    m = []
    m.append("encaje exacto, sin transformar" if p["encaje"] == "exacto" else
             f"{len(p['operaciones'])} operación(es), merma {p['merma']:.0%}")
    if not p["cubre_cantidad"]:
        m.append("no cubre toda la cantidad")
    if p["bulto_grande"]:
        m.append("habría que romper un bulto grande")
    if i > 0 or len(todas) > 1:
        m.append(f"entrada {p['fecha_entrada']} (FIFO)")
    return "; ".join(m)


def validar(propuestas: list[dict], f: Ficha) -> list[str]:
    """Comprobación independiente: nada de IDs inventados, bultos no disponibles ni operaciones fuera de reglas."""
    errores = []
    s = stock().set_index("id_bulto")
    for p in propuestas:
        bid = p["id_bulto"]
        if bid not in s.index:
            errores.append(f"{bid}: no existe en el stock")
            continue
        real = s.loc[bid]
        if real.estado != "disponible":
            errores.append(f"{bid}: no está disponible ({real.estado})")
        if f.grados and str(real.grado) not in f.grados:
            errores.append(f"{bid}: grado {real.grado} distinto del pedido")
        if abs(real.espesor_mm - f.espesor_mm) > config.TOLERANCIA_ESPESOR_MM:
            errores.append(f"{bid}: espesor {real.espesor_mm} distinto del pedido")
        for o in p.get("operaciones", []):
            if o["regla"] not in tr.REGLAS:
                errores.append(f"{bid}: operación fuera de las reglas ({o['regla']})")
        again = evaluar_bulto(real.to_dict() | {"id_bulto": bid}, f)
        if again["encaje"] == "imposible":
            errores.append(f"{bid}: la transformación no es posible ({again['motivo']})")
    return errores
