"""
Auditor Airbus · una sola orden: entra una carpeta de PDF, sale respuestas.csv (guía §4 y §6.2).

    .venv\\Scripts\\python auditar.py <carpeta_pdf> [--salida respuestas.csv] [--sin-llm] [--hilos 6]

Fases:
  1. Ingesta de todos los PDF (los escaneados se transcriben con visión; caché en disco).
  2. Referencias una sola vez: Part-IS + STD-SEC-001 VIGENTE + LISTA-DOC.
  3. Auditoría documento a documento, en paralelo y sin estado compartido:
       reglas deterministas + agente LLM → verificación por código → deduplicación.
- Un documento que falla no tumba la ejecución: se registra y se sigue.
- El CSV se reescribe tras cada documento: si se acaba el tiempo, lo hecho ya está entregado.
- traza.jsonl: cada propuesta con su origen y, si se descartó, el motivo (explicabilidad).
"""
import argparse
import csv
import json
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from src import ingesta, referencias, registros, reglas
from src.modelo import COLUMNAS, EXTRA
from src.verificar import ANCLA, ANCLA_GENERICA, verificar

_lock = threading.Lock()


def escribir(hallazgos, ruta: Path):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(".tmp")
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNAS + EXTRA)
        w.writeheader()
        for h in sorted(hallazgos, key=lambda x: (x.documento, x.ubicacion)):
            w.writerow(h.fila())
    tmp.replace(ruta)


SISTEMA_UBIC = re.compile(r"\b[A-Z][A-Z0-9]{2}\b")
FECHA_UBIC = re.compile(r"\d{4}-\d{2}-\d{2}")


def clave_defecto(h) -> tuple:
    """Dos filas son el mismo defecto si comparten documento y primer identificador de la ubicación.
    Si ese identificador es genérico («Tabla 2»), se añaden el sistema y la fecha de la fila, para no fundir
    filas distintas de una misma tabla («Tabla 2, OPC (2026-01-22)» ≠ «Tabla 2, MPS (2026-09-12)»)."""
    a = ANCLA.findall(h.ubicacion)
    if not a:
        return (h.documento, h.ubicacion)
    if not ANCLA_GENERICA.match(a[0]):
        return (h.documento, a[0])
    literal = next((x for x in a[1:] if not ANCLA_GENERICA.match(x)), "")    # «Tabla 1 (falta E-1242)»
    resto = h.ubicacion.replace(a[0], " ")
    s, f = SISTEMA_UBIC.findall(resto), FECHA_UBIC.findall(resto)
    return (h.documento, a[0], literal, s[0] if s else "", f[0] if f else "")


def deduplicar(hallazgos):
    mejor = {}
    for h in hallazgos:
        k = clave_defecto(h)
        if k not in mejor or h.confianza > mejor[k].confianza:
            mejor[k] = h
    # Una propuesta del LLM sin fecha («Tabla 1, TLM») es la misma fila que una regla con fecha
    # («Tabla 1, TLM (2026-05-30)»): se queda la de la regla, que trae el cálculo exacto.
    # Igual con una propuesta del LLM que solo dice «Tabla 2»: si una regla ya ha revisado esa tabla fila a fila,
    # la mención genérica sobra (sería un duplicado de alguna fila).
    regla = [k for k, h in mejor.items() if len(k) == 5 and h.origen.startswith("regla")]
    con_regla, tablas_regla = {k[:4] for k in regla}, {k[:2] for k in regla}

    def sobra(k, h):
        if len(k) != 5 or h.origen.startswith("regla"):
            return False
        if not k[4] and k[3] and k[:4] in con_regla:
            return True
        return not (k[2] or k[3] or k[4]) and k[:2] in tablas_regla

    return [h for k, h in mejor.items() if not sobra(k, h)]


def auditar_doc(doc, docs, bloque_ref, usar_llm, std=None):
    # Primero las reglas por código (registros: cuentas exactas); a igual confianza, prevalecen sobre el LLM
    propuestas, texto_cruzado = registros.revisar(doc, docs, std)
    propuestas += reglas.revisar(doc)
    rel = referencias.relacionados(doc, docs)
    if usar_llm:
        from src import agente
        llm_h, _ = agente.auditar(doc, bloque_ref, rel)
        propuestas += llm_h
        try:
            propuestas += agente.auditar_figuras(doc, bloque_ref)   # diagramas: visión solo donde hay figuras
        except Exception as e:                                        # un fallo de visión no tumba el documento
            print(f"  aviso: figuras de {doc.codigo} no analizadas: {e!r}")
    texto_rel = "\n".join(r.texto for r in rel) + "\n" + texto_cruzado
    aceptados, traza = [], []
    for h in propuestas:
        ok = verificar(h, doc.texto, texto_rel)
        traza.append({"documento": h.documento, "ubicacion": h.ubicacion, "tipo": h.tipo, "clausula": h.clausula,
                      "origen": h.origen, "confianza": h.confianza, "evidencia": h.evidencia,
                      "justificacion": h.justificacion, "fuente": h.fuente, "aceptado": ok is not None,
                      "descarte": h.descarte, "relacionados": [r.codigo for r in rel]})
        if ok:
            aceptados.append(ok)
    return deduplicar(aceptados), traza


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("carpeta", nargs="?", default="",
                    help="carpeta con los PDF (si se omite, se busca sola: ver src/rutas.py)")
    ap.add_argument("--salida", default=str(Path("salidas") / "respuestas.csv"))
    ap.add_argument("--sin-llm", action="store_true", help="solo reglas deterministas")
    ap.add_argument("--hilos", type=int, default=6)
    ap.add_argument("--solo", default="", help="auditar solo los códigos indicados (coma), para pruebas")
    a = ap.parse_args()
    t0 = time.time()
    salida = Path(a.salida)
    salida.parent.mkdir(parents=True, exist_ok=True)     # en una copia nueva del repo, salidas/ aún no existe
    ftraza = salida.with_name(salida.stem + "_traza.jsonl")

    # 1. Ingesta
    from src.rutas import ayuda_corpus, buscar_corpus
    carpeta = Path(a.carpeta) if a.carpeta else buscar_corpus()
    pdfs = sorted(carpeta.rglob("*.pdf")) if carpeta and carpeta.is_dir() else []
    if not pdfs and a.carpeta:                      # la ruta escrita no vale: se prueba a buscarla sola
        carpeta = buscar_corpus()
        pdfs = sorted(carpeta.rglob("*.pdf")) if carpeta else []
        if pdfs:
            print(f"Aviso: en «{a.carpeta}» no hay PDF; uso los de {carpeta}")
    if not pdfs:
        sys.exit(ayuda_corpus())
    print(f"Corpus: {carpeta} ({len(pdfs)} PDF)")
    docs, errores = [], []

    def leer(f):
        return ingesta.leer(f, vision=not a.sin_llm)

    with ThreadPoolExecutor(a.hilos) as ex:
        fut = {ex.submit(leer, f): f for f in pdfs}
        for fu in as_completed(fut):
            try:
                docs.append(fu.result())
            except Exception as e:
                errores.append((fut[fu].name, repr(e)))
                print(f"ERROR leyendo {fut[fu].name}: {e!r}")
    docs.sort(key=lambda d: d.ruta)
    print(f"Ingesta: {len(docs)} documentos en {time.time() - t0:.0f} s")

    # 2. Referencias (una vez)
    bloque = referencias.bloque(docs)
    std = referencias.estandar_vigente(docs)
    print(f"Referencias: Part-IS + {std.codigo + ' v' + std.version if std else 'SIN ESTÁNDAR'} + LISTA-DOC")

    # 3. Auditoría en paralelo
    auditables = [d for d in docs if d.codigo and not d.codigo.startswith(referencias.CODIGOS_REFERENCIA)]
    if a.solo:
        auditables = [d for d in auditables if d.codigo in a.solo.split(",")]
    todos = []
    open(ftraza, "w", encoding="utf-8").close()
    with ThreadPoolExecutor(a.hilos) as ex:
        fut = {ex.submit(auditar_doc, d, docs, bloque, not a.sin_llm, std): d for d in auditables}
        for i, fu in enumerate(as_completed(fut), 1):
            d = fut[fu]
            try:
                hall, traza = fu.result()
            except Exception as e:
                errores.append((d.codigo, repr(e)))
                print(f"[{i}/{len(auditables)}] ERROR en {d.codigo}: {e!r}")
                continue
            with _lock:
                todos = deduplicar(todos + hall)
                escribir(todos, salida)
                with open(ftraza, "a", encoding="utf-8") as f:
                    for t in traza:
                        f.write(json.dumps(t, ensure_ascii=False) + "\n")
            desc = sum(1 for t in traza if not t["aceptado"])
            print(f"[{i}/{len(auditables)}] {d.codigo}: {len(hall)} hallazgos ({desc} descartados) "
                  f"· {time.time() - t0:.0f} s")
    escribir(todos, salida)
    print(f"\n{len(todos)} hallazgos → {salida} · {len(errores)} errores · {time.time() - t0:.0f} s")
    for e in errores:
        print("  error:", e)


if __name__ == "__main__":
    main()
