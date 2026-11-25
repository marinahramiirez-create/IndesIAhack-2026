"""
UNA ORDEN: carpeta de PDF → respuestas.csv

    python -m nimbus.ejecutar RUTA_CARPETA [--salida respuestas.csv] [--procesos 4]

1. Ingesta en paralelo (un proceso por documento, sin estado compartido; con caché por huella del PDF).
2. Conocimiento: vigencias, estándar vigente, plazos de Part-IS y requisitos definidos (a partir del corpus).
3. Detectores por documento. Un fallo en un documento se registra y se sigue con los demás.
4. Deduplicación, validación de formato y escritura del CSV + traza (respuestas.traza.json) para la app.
"""
import argparse
import json
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import asdict
from pathlib import Path

from nimbus import conocimiento, detectores, ingesta, salida


def _ingerir(ruta: str):
    try:
        return ingesta.ingerir(Path(ruta), familia=Path(ruta).parent.name), None
    except Exception as e:
        return None, f"{Path(ruta).name}: {e}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Auditoría Part-IS: carpeta de PDF → respuestas.csv")
    ap.add_argument("carpeta")
    ap.add_argument("--salida", default="respuestas.csv")
    ap.add_argument("--procesos", type=int, default=4)
    a = ap.parse_args(argv)

    t0 = time.time()
    pdfs = sorted(str(p) for p in Path(a.carpeta).rglob("*.pdf"))
    print(f"[1/4] Ingesta de {len(pdfs)} PDF con {a.procesos} procesos…")
    docs, errores = [], []
    with ProcessPoolExecutor(max_workers=a.procesos) as ex:
        for fut in as_completed([ex.submit(_ingerir, p) for p in pdfs]):
            d, err = fut.result()
            if d and not d.escaneado and d.codigo == Path(d.archivo).stem:
                continue                      # PDF sin código de documento (p. ej. el enunciado): no es del ISMS
            if d:
                docs.append(d)
            if err:
                errores.append(err)
    docs.sort(key=lambda d: d.archivo)
    esc = [d.codigo for d in docs if d.escaneado]
    print(f"      {len(docs)} documentos ({sum(d.paginas for d in docs)} páginas) · {len(esc)} escaneados "
          f"(pendientes de visión: {', '.join(esc)}) · {time.time() - t0:.0f} s")

    print("[2/4] Conocimiento de referencia…")
    k = conocimiento.construir(docs)
    print(f"      STD-SEC-001 vigente v{k.std.version if k.std else '?'} · {len(k.parametros)} parámetros · "
          f"{len(k.vigentes)} documentos vigentes · sustituidas: {k.sustituidas or '—'}")
    for av in k.avisos:
        print("      ⚠", av)

    print("[3/4] Detectores por documento…")
    todos = []
    for d in docs:
        hs, errs = detectores.ejecutar(d, k)
        todos += hs
        errores += errs

    print("[4/4] Deduplicación, validación y escritura…")
    finales = salida.deduplicar(todos)
    escritor = salida.Escritor(Path(a.salida))
    escritor.escribir(finales)
    escritor.cerrar()
    traza = {"docs": [{"codigo": d.codigo, "archivo": d.archivo, "familia": d.familia, "version": d.version,
                       "paginas": d.paginas, "escaneado": d.escaneado} for d in docs],
             "hallazgos": [asdict(h) for h in finales], "errores": errores,
             "segundos": round(time.time() - t0, 1)}
    Path(a.salida).with_suffix(".traza.json").write_text(json.dumps(traza, ensure_ascii=False, indent=1), encoding="utf-8")

    problemas = salida.comprobar_csv(Path(a.salida))
    por_det = {}
    for h in finales:
        por_det[h.detector] = por_det.get(h.detector, 0) + 1
    print(f"\n✔ {escritor.n} hallazgos → {a.salida}  ({time.time() - t0:.0f} s)")
    print("  por detector: " + " · ".join(f"{k_}: {v}" for k_, v in sorted(por_det.items())))
    print("  formato del CSV: " + ("correcto" if not problemas else f"{len(problemas)} problemas: {problemas[:3]}"))
    if errores:
        print(f"  ⚠ {len(errores)} errores registrados (ver {Path(a.salida).with_suffix('.traza.json').name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
