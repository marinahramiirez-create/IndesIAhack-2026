"""
Detectores de trazabilidad.

  referencias_rotas      cita a un identificador que no existe en ningún documento del corpus
                         (p. ej. un requisito que remite a SEC-REQ-099 o un informe que verifica C2L-SEC-935).
  ids_duplicados         el mismo identificador de requisito definido dos veces en un documento.
  clausula_incoherente   un requisito cita una cláusula que no corresponde ni a su sección ni a la que usan
                         los demás requisitos de su mismo tipo en el documento.
  version_sustituida     el documento invoca una versión que la lista maestra declara sustituida.
"""
import re
from collections import Counter

from nimbus.conocimiento import norm
from nimbus.detectores.comun import clausula_valida, hallazgo, requisitos_de, sec, tabla_ref, ubic_req

RE_REF = re.compile(r"\b((?:[A-Z0-9]{2,4}-SEC)|SEC-REQ)-(\d{3})\b")


def referencias_rotas(doc, k):
    salida, vistos = [], set()
    def rota(i, prefijo):
        conocidos = k.ids_por_prefijo.get(prefijo)
        return conocidos and i not in conocidos
    for r in requisitos_de(doc):
        for m in RE_REF.finditer(r.texto):
            i = m.group(0)
            if i != r.id and rota(i, m.group(1)) and (r.id, i) not in vistos:
                vistos.add((r.id, i))
                salida.append(hallazgo(doc, f"{r.id}{sec(r.seccion)}", "Trazabilidad incorrecta", "—",
                                       f"Referencia cruzada rota: cita {i}, que no existe.", "trazabilidad.referencias_rotas",
                                       evidencia=r.texto[:240], confianza=0.9, pagina=r.pagina))
    for t in doc.tablas:
        for f in t.filas:
            for celda in f:
                for m in RE_REF.finditer(celda):
                    i = m.group(0)
                    if rota(i, m.group(1)) and ("T", i) not in vistos:
                        vistos.add(("T", i))
                        salida.append(hallazgo(doc, f"{tabla_ref(t)}, {i}", "Trazabilidad incorrecta", "IS.I.OR.210",
                                               f"La tabla cita {i}, que no existe en la especificación correspondiente.",
                                               "trazabilidad.referencias_rotas", evidencia=" | ".join(f)[:240],
                                               confianza=0.85, pagina=t.pagina))
    return salida


def ids_duplicados(doc, k):
    cuenta = Counter(r.id for r in doc.requisitos)
    return [hallazgo(doc, i, "Trazabilidad incorrecta", "—", f"Identificador {i} definido {n} veces en el documento.",
                     "trazabilidad.ids_duplicados", confianza=0.85) for i, n in cuenta.items() if n > 1]


def clausula_incoherente(doc, k):
    reqs = [r for r in requisitos_de(doc) if r.clausula.startswith("IS.I.OR")]
    if len(reqs) < 5:
        return []
    secciones = {s.numero: s.clausulas for s in doc.secciones}
    por_tipo = {}
    for r in reqs:
        por_tipo.setdefault(norm(r.tipo), []).append(r.clausula)
    mayoria = {}
    for tipo, cl in por_tipo.items():
        c, n = Counter(cl).most_common(1)[0]
        if len(cl) >= 3 and n / len(cl) >= 0.7:
            mayoria[tipo] = c
    salida = []
    for r in reqs:
        de_seccion = secciones.get(r.seccion, [])
        esperada_tipo = mayoria.get(norm(r.tipo))
        if not de_seccion or r.clausula in de_seccion:
            continue
        if esperada_tipo and r.clausula == esperada_tipo:
            continue                                  # sección genérica, pero coherente con su tipo
        if _por_contenido(r.texto) == r.clausula:
            continue                                  # el contenido justifica la cláusula (registros → 245)
        esperada = esperada_tipo or (de_seccion[0] if len(de_seccion) == 1 else None)
        if not esperada:
            continue
        salida.append(hallazgo(doc, ubic_req(r), "Trazabilidad incorrecta", esperada,
                               f"Requisito de tipo «{r.tipo}» mapeado a {r.clausula}; por su contenido y su sección "
                               f"(§{r.seccion}: {', '.join(de_seccion)}) corresponde a {esperada}.",
                               "trazabilidad.clausula_incoherente", evidencia=r.texto[:200], confianza=0.8, pagina=r.pagina))
    return salida


# Temas cuyo contenido determina la cláusula aunque el requisito esté en otra sección
TEMAS = [(r"conserv|retenci", "IS.I.OR.245"), (r"notific\w* a la autoridad", "IS.I.OR.230"),
         (r"proveedor|contratad|subcontrat", "IS.I.OR.235")]


def _por_contenido(texto: str):
    t = norm(texto)
    return next((c for patron, c in TEMAS if re.search(patron, t)), None)


def version_sustituida(doc, k):
    salida = []
    for codigo, versiones in k.sustituidas.items():
        if doc.codigo == codigo:
            continue
        for v in versiones:
            patron = re.compile(re.escape(codigo) + r"[^\n]{0,80}?versi[oó]n\s+" + re.escape(v) + r"\b", re.I)
            m = patron.search(doc.texto)
            if not m:
                continue
            donde = next((f"{tabla_ref(t)}, «{codigo}»" for t in doc.tablas
                          if any(codigo in c and v in " ".join(f) for f in t.filas for c in f)), f"«{codigo}»")
            salida.append(hallazgo(doc, donde, "Trazabilidad incorrecta", "IS.I.OR.200",
                                   f"Invoca {codigo} versión {v}, sustituida según la lista maestra (vigente: "
                                   f"{k.vigentes.get(codigo, '?')}).", "trazabilidad.version_sustituida",
                                   evidencia=m.group(0), confianza=0.7))
    return salida
