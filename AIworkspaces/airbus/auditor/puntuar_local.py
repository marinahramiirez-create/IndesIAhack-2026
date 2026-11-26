"""
Puntuador PROVISIONAL (imita las reglas de la guía §6.2 hasta tener el oficial del kit de desarrollo):
  - acierto si coincide el documento y la ubicación comparte un identificador con un defecto de la clave
  - cada defecto de la clave se empareja una sola vez
  - cláusula correcta = igualdad exacta
  - se ignoran los hallazgos de documentos que no están en la clave
Uso: python puntuar_local.py respuestas.csv clave.csv
"""
import re
import sys

import pandas as pd

PID = re.compile(r"[A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]{1,8}){0,3}-\d{2,4}|(?:Tabla|Figura) \d+|§\s?\d+(?:\.\d+)*|DIR-\d+")


def ids(ubic: str) -> set[str]:
    s = set(m.replace("§ ", "§") for m in PID.findall(str(ubic)))
    # "SEC-REQ-011 ↔ 010": el número suelto hereda el prefijo del primer ID
    base = next(iter(sorted(x for x in s if "-" in x)), None)
    if base:
        for n in re.findall(r"(?:↔|/|,)\s*(\d{2,4})\b", str(ubic)):
            s.add(base.rsplit("-", 1)[0] + "-" + n)
    return s


def puntuar(resp: pd.DataFrame, clave: pd.DataFrame) -> dict:
    docs = set(clave.documento)
    resp = resp[resp.documento.isin(docs)].reset_index(drop=True)
    usados, aciertos, clausula_ok, detalle = set(), 0, 0, []
    for _, r in resp.iterrows():
        ir = ids(r.ubicacion)
        hit = None
        for j, c in clave.iterrows():
            if j in usados or c.documento != r.documento:
                continue
            if ir & ids(c.ubicacion):
                hit = j
                break
        if hit is not None:
            usados.add(hit)
            aciertos += 1
            ok = str(r.clausula).strip() == str(clave.loc[hit, "clausula"]).strip()
            clausula_ok += ok
        detalle.append((r.ubicacion, r.tipo, "ACIERTO" if hit is not None else "falso +"))
    p = aciertos / len(resp) if len(resp) else 0
    rc = aciertos / len(clave) if len(clave) else 0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0
    faltan = [clave.loc[j, "ubicacion"] for j in range(len(clave)) if j not in usados]
    return {"presentados": len(resp), "aciertos": aciertos, "precision": p, "recall": rc, "f1": f1,
            "clausula_ok": f"{clausula_ok}/{aciertos}", "detalle": detalle, "no_encontrados": faltan}


if __name__ == "__main__":
    r = puntuar(pd.read_csv(sys.argv[1]), pd.read_csv(sys.argv[2]))
    print(f"Presentados {r['presentados']} · aciertos {r['aciertos']} · P {r['precision']:.2f} · "
          f"R {r['recall']:.2f} · F1 {r['f1']:.2f} · cláusula correcta {r['clausula_ok']}")
    for d in r["detalle"]:
        print("  ", d)
    print("No encontrados:", r["no_encontrados"])
