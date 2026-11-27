"""
Métricas de la revisión (pestaña «Métricas»). Lógica pura, sin HTTP: la usa servidor.py (GET /api/metricas) y se
prueba en tests/test_metricas.py. Es la ÚNICA fuente de las cifras: la página solo las pinta, y una API futura
devolverá exactamente lo mismo.

Las reglas son las de la pantalla de Auditorías, para que los números coincidan siempre:
  - estado del documento: Pendiente / En revisión / Completado / Sin hallazgos (un documento sin hallazgos marcado
    como revisado cuenta como Completado);
  - prioridad: la elegida, o la sugerida (5 o más «No cumple» → Alta; algún hallazgo → Media; ninguno → Baja; un
    documento cargado, la que se eligió al cargarlo);
  - días para responder: plazo común (Configuración → Reglas) menos los días pasados desde el inicio (un documento
    cargado, desde su carga); Completado = respondido; sin hallazgos y no cargado = no necesita respuesta.

Filtros: familia, prioridad, tipo de hallazgo y cláusula acotan documentos y hallazgos; «periodo» (todo, 7, 30 o 90
días) acota la actividad (decisiones, comentarios, devoluciones). Sin nombres de personas: las cifras del equipo
son de conjunto.
"""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from src import permisos as P

TIPO_GRAVE = "No cumple"
SIN_CLAUSULA = "Sin cláusula"
_cl = lambda r: r.get("clausula") if r.get("clausula") not in (None, "", "—", "-") else SIN_CLAUSULA   # respuestas.csv usa «—»
PERIODOS = {"todo": None, "7": 7, "30": 30, "90": 90}
TRAMOS_CONF = [(0.0, 0.6, "< 0,6"), (0.6, 0.7, "0,6–0,7"), (0.7, 0.8, "0,7–0,8"), (0.8, 0.9, "0,8–0,9"), (0.9, 1.01, "≥ 0,9")]
AVISO_HISTORIAL = ("Las decisiones que se deshacen no dejan rastro: los tiempos y la evolución diaria se calculan con "
                   "las decisiones vigentes.")


def _dia(iso: str | None) -> date | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso)[:19]).date() if len(str(iso)) > 10 else date.fromisoformat(str(iso)[:10])
    except ValueError:
        return None


def _media(v: list[float]) -> float | None:
    return round(sum(v) / len(v), 1) if v else None


def _pct(a: int, b: int) -> float | None:
    return round(100 * a / b, 1) if b else None


def documentos(res: list[dict], docs: dict, estado: dict, cargados: list[dict], hoy: date) -> list[dict]:
    """Un registro por documento (corpus + cargados confirmados) con estado, prioridad, días y sus hallazgos."""
    dec, meta = estado.get("dec", {}), estado.get("docs_meta", {})
    cfg = estado.get("config", {})
    plazo, inicio = int(cfg.get("plazo_dias") or 15), _dia(cfg.get("inicio"))
    por_doc = defaultdict(list)
    for r in res:
        por_doc[r["documento"]].append(r)
    fichas = [(c, info, None) for c, info in docs.items()]
    fichas += [(c["clave"], {"familia": c.get("familia") or "Sin familia", "titulo": c.get("titulo") or c.get("archivo", ""),
                             "version": c.get("version", "")}, c) for c in cargados if c.get("clave")]
    salida = []
    for cod, info, cargado in fichas:
        rs = por_doc.get(cod, [])
        claves = [f"{r['documento']}|{r['ubicacion']}" for r in rs]
        est = P.estado_doc(claves, dec)
        if not rs and (meta.get(cod) or {}).get("revisado"):
            est = "Completado"
        if cargado:
            prio_sug = cargado.get("prioridad") or "Media"
        else:
            nc = sum(r["tipo"] == TIPO_GRAVE for r in rs)
            prio_sug = "Alta" if nc >= 5 else "Media" if rs else "Baja"
        prio = ((meta.get(cod) or {}).get("prioridad") or {}).get("valor") or prio_sug
        ini = _dia(cargado.get("fecha")) if cargado else inicio
        if est == "Completado":
            dias = {"tipo": "hecho"}
        elif (est == "Sin hallazgos" and not cargado) or not ini:
            dias = {"tipo": "na"}
        else:
            pasados = (hoy - ini).days
            dias = {"tipo": "dias", "n": plazo - pasados, "pasados": pasados}
        necesita = est in ("Pendiente", "En revisión") or (bool(cargado) and est != "Completado")
        salida.append({"doc": cod, "titulo": info.get("titulo", ""), "familia": info.get("familia", ""), "estado": est,
                       "prioridad": prio, "dias": dias, "necesita": necesita, "cargado": bool(cargado), "hallazgos": rs,
                       "inicio": ini.isoformat() if ini else None,
                       "escalado": bool(estado.get("escalados", {}).get(cod))})
    return salida


def calcular(res: list[dict], docs: dict, estado: dict, cargados: list[dict], filtros: dict, hoy: date,
             metricas_ia: dict | None = None) -> dict:
    f = {k: str(filtros.get(k) or "") for k in ("familia", "prioridad", "tipo", "clausula", "periodo")}
    dias_periodo = PERIODOS.get(f["periodo"] or "todo")
    desde = hoy - timedelta(days=dias_periodo - 1) if dias_periodo else None
    en_periodo = lambda d: d is not None and (desde is None or d >= desde) and d <= hoy
    dec = estado.get("dec", {})
    cfg = estado.get("config", {})
    plazo, inicio = int(cfg.get("plazo_dias") or 15), _dia(cfg.get("inicio"))

    todos = documentos(res, docs, estado, cargados, hoy)
    ds = [d for d in todos if (not f["familia"] or d["familia"] == f["familia"]) and (not f["prioridad"] or d["prioridad"] == f["prioridad"])]
    pasa_h = lambda r: (not f["tipo"] or r["tipo"] == f["tipo"]) and (not f["clausula"] or r["clausula"] == f["clausula"])
    if f["tipo"] or f["clausula"]:                  # con filtro de hallazgo, solo los documentos que tienen alguno así
        ds = [d for d in ds if any(pasa_h(r) for r in d["hallazgos"])]
    hs = [(d, r) for d in ds for r in d["hallazgos"] if pasa_h(r)]
    clave = lambda r: f"{r['documento']}|{r['ubicacion']}"
    decision = lambda r: dec.get(clave(r))

    # ------------------------------------------------------------ Resumen
    venc = [d for d in ds if d["dias"]["tipo"] == "dias" and d["dias"]["n"] < 0]
    pronto = [d for d in ds if d["dias"]["tipo"] == "dias" and 0 <= d["dias"]["n"] <= 3]
    decididos = [(d, r) for d, r in hs if decision(r)]
    estados = Counter(d["estado"] for d in ds)
    rango_prio = {"Alta": 0, "Media": 1, "Baja": 2}
    valor_dias = lambda d: d["dias"]["n"] if d["dias"]["tipo"] == "dias" else 10**6
    atencion = sorted((d for d in ds if d["necesita"]), key=lambda d: (rango_prio.get(d["prioridad"], 9), valor_dias(d), d["doc"]))[:8]
    # Evolución diaria de hallazgos pendientes (con las decisiones vigentes) y el ritmo necesario para llegar al plazo
    serie = []
    if inicio and hs:
        fin_plazo = inicio + timedelta(days=plazo)
        x0 = max(inicio, desde) if desde else inicio
        fechas_dec = sorted(_dia(decision(r).get("fecha")) or hoy for _, r in decididos)
        total = len(hs)
        d_ = x0
        while d_ <= max(hoy, fin_plazo) and len(serie) < 400:
            real = total - sum(1 for x in fechas_dec if x <= d_) if d_ <= hoy else None
            ideal = max(0.0, round(total * (1 - (d_ - inicio).days / plazo), 1)) if plazo else 0.0
            serie.append({"fecha": d_.isoformat(), "pendientes": real, "ritmo": ideal})
            d_ += timedelta(days=1)
    resumen = {
        "kpis": {"documentos": len(ds), "por_revisar": sum(d["necesita"] for d in ds), "completados": estados.get("Completado", 0),
                 "hallazgos": len(hs), "decididos": len(decididos), "pct_decididos": _pct(len(decididos), len(hs)),
                 "vencidos": len(venc), "vencen_3": len(pronto),
                 "no_cumple_abiertos": sum(1 for _, r in hs if r["tipo"] == TIPO_GRAVE and not decision(r)),
                 "devueltos": sum(d["escalado"] for d in ds)},
        "estados": [{"estado": e, "n": estados.get(e, 0)} for e in ("Completado", "Pendiente", "En revisión", "Sin hallazgos")],
        "serie": serie, "plazo": {"dias": plazo, "inicio": inicio.isoformat() if inicio else None,
                                  "fin": (inicio + timedelta(days=plazo)).isoformat() if inicio else None},
        "atencion": [{"doc": d["doc"], "titulo": d["titulo"], "prioridad": d["prioridad"], "estado": d["estado"], "dias": d["dias"]}
                     for d in atencion]}

    # ------------------------------------------------------------ Cumplimiento
    tipos = Counter(r["tipo"] for _, r in hs)
    abiertos_t = Counter(r["tipo"] for _, r in hs if not decision(r))
    claus = Counter(_cl(r) for _, r in hs)
    fams = sorted({d["familia"] for d, _ in hs})
    cls = [c for c, _ in claus.most_common()]
    celda = Counter((d["familia"], _cl(r)) for d, r in hs)
    por_fam = []
    for fam in sorted({d["familia"] for d in ds}):
        hf = [r for d, r in hs if d["familia"] == fam]
        por_fam.append({"familia": fam, "hallazgos": len(hf), "decididos": sum(1 for r in hf if decision(r)),
                        "aceptados": sum(1 for r in hf if (decision(r) or {}).get("dec") == "approved"),
                        "rechazados": sum(1 for r in hf if (decision(r) or {}).get("dec") == "rejected"),
                        "documentos": sum(1 for d in ds if d["familia"] == fam)})
    alta_sin = [{"doc": d["doc"], "titulo": d["titulo"], "estado": d["estado"], "dias": d["dias"]}
                for d in ds if d["prioridad"] == "Alta" and d["necesita"]]
    cumplimiento = {"por_tipo": [{"tipo": t, "n": n, "abiertos": abiertos_t.get(t, 0)} for t, n in tipos.most_common()],
                    "por_clausula": [{"clausula": c, "n": n} for c, n in claus.most_common(10)],
                    "mapa": {"familias": fams, "clausulas": cls, "celdas": [[celda.get((fa, c), 0) for c in cls] for fa in fams]},
                    "por_familia": por_fam, "alta_sin_revisar": alta_sin}

    # ------------------------------------------------------------ Equipo (de conjunto, sin nombres)
    docs_ok = {d["doc"] for d in ds}
    inicio_de = {d["doc"]: _dia(d["inicio"]) for d in ds}
    dec_p = [(r, decision(r)) for _, r in decididos if en_periodo(_dia(decision(r).get("fecha")))]
    por_dia = defaultdict(lambda: {"aceptadas": 0, "rechazadas": 0})
    for _, x in dec_p:
        por_dia[_dia(x["fecha"]).isoformat()]["aceptadas" if x.get("dec") == "approved" else "rechazadas"] += 1
    x0 = desde or min([_dia(x["fecha"]) for _, x in dec_p] + [inicio or hoy])
    serie_dec, d_ = [], x0
    while d_ <= hoy and len(serie_dec) < 400:
        serie_dec.append({"fecha": d_.isoformat(), **por_dia.get(d_.isoformat(), {"aceptadas": 0, "rechazadas": 0})})
        d_ += timedelta(days=1)
    t_decidir = [(_dia(x["fecha"]) - inicio_de[r["documento"]]).days for r, x in dec_p
                 if inicio_de.get(r["documento"]) and _dia(x["fecha"])]
    coms = [c for c in estado.get("comentarios", []) if str(c.get("key", "")).split("|")[0] in docs_ok and en_periodo(_dia(c.get("fecha")))]
    hist = [h for h in estado.get("escalados_hist", []) if h.get("doc") in docs_ok]
    devueltos_p = [h for h in hist if h.get("accion") in ("escalar", "cambiar") and en_periodo(_dia(h.get("fecha")))]
    t_corregir, abierto = [], {}
    for h in sorted(hist, key=lambda h: h.get("fecha", "")):          # de «devolver» a «corregir», por documento
        if h.get("accion") in ("escalar", "cambiar"):
            abierto[h["doc"]] = _dia(h.get("fecha"))
        elif h.get("accion") == "corregir" and abierto.get(h["doc"]):
            fin = _dia(h.get("fecha"))
            if en_periodo(fin):
                t_corregir.append((fin - abierto.pop(h["doc"])).days)
        elif h.get("accion") == "quitar":
            abierto.pop(h["doc"], None)
    versiones = [v for d in docs_ok for v in estado.get("versiones", {}).get(d, []) if en_periodo(_dia(v.get("fecha")))]
    equipo = {"kpis": {"decisiones": len(dec_p), "aceptadas": sum(1 for _, x in dec_p if x.get("dec") == "approved"),
                       "rechazadas": sum(1 for _, x in dec_p if x.get("dec") == "rejected"),
                       "dias_medios_decidir": _media(t_decidir), "comentarios": len(coms),
                       "devoluciones": len(devueltos_p), "correcciones": len(t_corregir),
                       "dias_medios_corregir": _media(t_corregir), "versiones": len(versiones),
                       "bloqueados": sum(1 for d in ds if d["escalado"] and not (estado.get("escalados", {}).get(d["doc"]) or {}).get("corregido"))},
              "serie_decisiones": serie_dec}

    # ------------------------------------------------------------ Calidad de la IA (lo que el equipo opina de ella)
    def acuerdo(grupo):
        a = sum(1 for r in grupo if (decision(r) or {}).get("dec") == "approved")
        rj = sum(1 for r in grupo if (decision(r) or {}).get("dec") == "rejected")
        return {"aceptados": a, "rechazados": rj, "sin_decidir": len(grupo) - a - rj, "pct_acuerdo": _pct(a, a + rj)}
    todos_h = [r for _, r in hs]
    origen = lambda r: (r.get("origen") or "—").split(" ")[0]
    ediciones = estado.get("ediciones", {})
    ia = {"metricas": metricas_ia or None, "acuerdo": acuerdo(todos_h),
          "por_tipo": [{"tipo": t, **acuerdo([r for r in todos_h if r["tipo"] == t])} for t, _ in tipos.most_common()],
          "por_origen": [{"origen": o, **acuerdo([r for r in todos_h if origen(r) == o])} for o, _ in Counter(map(origen, todos_h)).most_common()],
          "por_confianza": [{"tramo": n, "n": len(g), **acuerdo(g)} for lo, hi, n in TRAMOS_CONF
                            for g in [[r for r in todos_h if lo <= float(r.get("conf") or 0) < hi]] if g],
          "editados": {"n": sum(1 for r in todos_h if ediciones.get(clave(r))), "total": len(todos_h),
                       "pct": _pct(sum(1 for r in todos_h if ediciones.get(clave(r))), len(todos_h))}}

    return {"meta": {"hoy": hoy.isoformat(), "desde": desde.isoformat() if desde else None, "filtros": f,
                     "opciones": {"familias": sorted({d["familia"] for d in todos}),
                                  "tipos": sorted({r["tipo"] for d in todos for r in d["hallazgos"]}),
                                  "clausulas": sorted({r["clausula"] for d in todos for r in d["hallazgos"] if r["clausula"]})},
                     "aviso_historial": AVISO_HISTORIAL},
            "resumen": resumen, "cumplimiento": cumplimiento, "equipo": equipo, "ia": ia}
