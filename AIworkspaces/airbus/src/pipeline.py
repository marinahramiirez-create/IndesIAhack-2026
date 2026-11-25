"""
Pipeline completo: ejecuta el grafo de agentes, evalúa contra el gold set y guarda en la BD.

Ejecutar desde la carpeta airbus/:
    python -m src.pipeline                          # documento por defecto (config.DOCUMENTO)
    python -m src.pipeline ruta/al/documento.docx   # otro documento
"""
import json
import sys
import time

import pandas as pd

from src import db, evaluar, grafo


def main(ruta: str | None = None):
    t0 = time.time()
    print("Ejecutando el grafo de agentes (LangGraph)...")
    estado = grafo.ejecutar(ruta)
    for linea in estado["traza"]:
        print("   ·", linea)

    h = pd.DataFrame(list(estado["hallazgos"].values()))
    for col in ["resaltar", "faltan", "violaciones", "vaguedad", "candidatas", "llm_votos"]:
        h[col] = h[col].apply(lambda v: json.dumps(v, ensure_ascii=False))
    contra = pd.DataFrame(estado["contradicciones"], columns=["req_a", "req_b", "parametro", "valor_a", "valor_b", "explicacion"])
    homo = pd.DataFrame(estado["homogeneidad"], columns=["req_id", "palabras", "motivo"])
    cob = pd.DataFrame(estado["cobertura"])

    print("\nResumen:", h.veredicto.value_counts().to_dict())
    metricas = {"resumen": h.veredicto.value_counts().to_dict(),
                "cobertura": {"cubiertas": int(cob.cubierta.sum()), "total": len(cob)}}
    if evaluar.gold_disponible():
        m = evaluar.evaluar(h, contra)
        metricas["evaluacion"] = m
        e, s = m["deteccion_estricta"], m["deteccion_senalados"]
        print(f"F1 detección (solo 'No cumple'):          {e['f1']:.2f}  (P {e['precision']:.2f} · R {e['recall']:.2f})")
        print(f"F1 detección ('No cumple' + 'Revisar'):   {s['f1']:.2f}  (P {s['precision']:.2f} · R {s['recall']:.2f})")
        print(f"Trazabilidad hallazgo → cláusula correcta: {m['trazabilidad_pct']:.0%}   (referencia del jurado ≥ 90 %)")
        if "contradicciones" in m:
            c = m["contradicciones"]
            print(f"Contradicciones: {c['tp']} de {c['tp'] + c['fn']} detectadas, {c['fp']} falsas")
        if m["errores_trazabilidad"]:
            print("Cláusula distinta de la del gold:", m["errores_trazabilidad"])
    else:
        print("(sin gold set: no se calculan métricas)")

    db.inicializar()
    db.guardar_df(h, "hallazgos")
    db.guardar_df(contra, "contradicciones")
    db.guardar_df(homo, "homogeneidad")
    db.guardar_df(cob, "cobertura")
    db.guardar_df(pd.DataFrame({"paso": estado["traza"]}), "traza")
    db.guardar_df(pd.DataFrame([{"clave": k, "valor": json.dumps(v, ensure_ascii=False)} for k, v in metricas.items()]), "metricas")
    print(f"\nHecho en {time.time() - t0:.0f} s. Ahora: streamlit run app.py")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
