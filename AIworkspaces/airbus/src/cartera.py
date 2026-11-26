"""
Cartera de auditorías para la vista gerencial (página Métricas).

La app audita UN documento; un responsable necesita ver la CARTERA completa. Aquí se construye:
  - 30 auditorías SIMULADAS (semilla fija → siempre las mismas) de varias normas, áreas y fechas.
  - La auditoría ACTUAL, con datos reales: sus 38 requisitos y las validaciones del revisor (tabla decisiones).

Estados de una auditoría:
  - Completa:     la IA emitió su informe y el revisor validó el 100 % de los requisitos.
  - No asegurada: la IA emitió su informe pero falta validación humana → el resultado no está garantizado.
  - Pendiente:    en curso, la IA aún no ha emitido el informe.

El día del reto: si hay una cartera real, basta con que cargar() devuelva las mismas columnas.
"""
from datetime import date, timedelta

import numpy as np
import pandas as pd

ESTADOS = ["Completa", "Pendiente", "No asegurada"]   # orden fijo (colores validados en este orden)
SLA_DIAS = 30                                         # plazo objetivo para cerrar una auditoría

NORMAS = ["EASA Part-IS", "ISO/IEC 27001", "ISO/IEC 27701", "EN 9100", "DO-326A / ED-202A"]
AREAS = {"es": ["Ingeniería", "Producción", "Mantenimiento (MRO)", "TI corporativa", "Proveedores"],
         "en": ["Engineering", "Production", "Maintenance (MRO)", "Corporate IT", "Suppliers"]}

# Cambios normativos con fecha pública de aplicación. El impacto en la cartera se calcula abajo.
CAMBIOS = [
    {"fecha": date(2024, 2, 23), "norma": "ISO/IEC 27001",
     "es": "Amd 1:2024: el SGSI debe considerar el cambio climático en el contexto de la organización",
     "en": "Amd 1:2024: the ISMS must consider climate change in the organisation's context"},
    {"fecha": date(2025, 10, 16), "norma": "EASA Part-IS",
     "es": "Aplicable el Reg. Delegado (UE) 2022/1645 (organizaciones de diseño y producción)",
     "en": "Delegated Reg. (EU) 2022/1645 applies (design and production organisations)"},
    {"fecha": date(2025, 10, 31), "norma": "ISO/IEC 27001",
     "es": "Fin de la transición: los certificados de la versión 2013 dejan de ser válidos",
     "en": "End of transition: certificates to the 2013 version are no longer valid"},
    {"fecha": date(2025, 12, 1), "norma": "EASA Part-IS",
     "es": "Nueva revisión de las Easy Access Rules for Information Security (AMC/GM)",
     "en": "New revision of the Easy Access Rules for Information Security (AMC/GM)"},
    {"fecha": date(2026, 2, 22), "norma": "EASA Part-IS",
     "es": "Aplicable el Reg. de Ejecución (UE) 2023/203 (operadores, CAMO, MRO, ATO…)",
     "en": "Implementing Reg. (EU) 2023/203 applies (operators, CAMO, MRO, ATO…)"},
]


def _simuladas(hoy: date, n: int = 30) -> pd.DataFrame:
    rng = np.random.default_rng(2026)
    filas = []
    for i in range(n):
        norma = NORMAS[rng.choice(len(NORMAS), p=[0.34, 0.26, 0.12, 0.16, 0.12])]
        reqs = int(rng.integers(20, 90))
        estado = rng.choice(ESTADOS, p=[0.45, 0.30, 0.25])
        antig = {"Completa": (10, 120), "Pendiente": (1, 50), "No asegurada": (5, 70)}[estado]
        inicio = hoy - timedelta(days=int(rng.integers(*antig)))
        if estado == "Completa":
            validados = reqs
            cierre = min(hoy, inicio + timedelta(days=int(rng.integers(8, 45))))
        elif estado == "No asegurada":
            validados, cierre = int(reqs * rng.uniform(0.1, 0.85)), None
        else:
            validados, cierre = 0, None
        filas.append({"id": f"AUD-2026-{i + 1:03d}", "norma": norma, "area_i": int(rng.integers(0, 5)),
                      "inicio": inicio, "cierre": cierre, "estado": estado, "requisitos": reqs,
                      "validados": validados, "aprobados": int(validados * rng.uniform(0.7, 0.95)),
                      # ¿se auditó contra la versión vigente de la norma? (si no, hay que re-evaluarla)
                      "version_vigente": bool(rng.random() > 0.25), "real": False})
    return pd.DataFrame(filas)


def cargar(hallazgos: pd.DataFrame, decisiones: pd.DataFrame, lang: str = "es", hoy: date | None = None) -> pd.DataFrame:
    """Cartera = auditorías simuladas + la auditoría actual (real)."""
    hoy = hoy or date.today()
    df = _simuladas(hoy)
    n, val = len(hallazgos), int(decisiones.req_id.nunique()) if not decisiones.empty else 0
    aprob = int((decisiones.decision == "aprobado").sum()) if not decisiones.empty else 0
    inicio = pd.to_datetime(decisiones.fecha_hora).min().date() if not decisiones.empty else hoy
    actual = {"id": "AUD-2026-031", "norma": "EASA Part-IS", "area_i": 0, "inicio": min(inicio, hoy),
              "cierre": hoy if val >= n else None, "estado": "Completa" if val >= n else "No asegurada",
              "requisitos": n, "validados": val, "aprobados": aprob, "version_vigente": True, "real": True}
    df = pd.concat([df, pd.DataFrame([actual])], ignore_index=True)
    df["area"] = df.area_i.map(lambda i: AREAS[lang][i])
    df["dias"] = df.apply(lambda r: ((r.cierre or hoy) - r.inicio).days, axis=1)
    df["fuera_sla"] = (df.estado != "Completa") & (df.dias > SLA_DIAS)
    return df


def tramos_antiguedad(df: pd.DataFrame, lang: str = "es") -> pd.DataFrame:
    """Auditorías abiertas (Pendiente + No asegurada) por días que llevan abiertas."""
    etiquetas = {"es": ["0-7 días", "8-15 días", "16-30 días", "> 30 días"],
                 "en": ["0-7 days", "8-15 days", "16-30 days", "> 30 days"]}[lang]
    abiertas = df[df.estado != "Completa"].copy()
    abiertas["tramo"] = pd.cut(abiertas.dias, [-1, 7, 15, 30, 10_000], labels=etiquetas)
    t = abiertas.groupby(["tramo", "estado"], observed=False).size().unstack(fill_value=0)
    return t.reindex(columns=[e for e in ESTADOS if e != "Completa"], fill_value=0)


def cambios_norma(df: pd.DataFrame, lang: str = "es") -> pd.DataFrame:
    """Cambios normativos y, para el último de cada norma, cuántas auditorías ABIERTAS se hicieron contra la
    versión anterior (hay que re-evaluarlas)."""
    desfasadas = df[(df.estado != "Completa") & ~df.version_vigente].groupby("norma").size()
    ultimo = {}
    for c in sorted(CAMBIOS, key=lambda c: c["fecha"]):
        ultimo[c["norma"]] = c["fecha"]
    filas = [{"fecha": c["fecha"], "norma": c["norma"], "cambio": c[lang],
              "afectadas": int(desfasadas.get(c["norma"], 0)) if ultimo[c["norma"]] == c["fecha"] else 0}
             for c in CAMBIOS]
    return pd.DataFrame(filas).sort_values("fecha", ascending=False)


def validaciones_semana(df: pd.DataFrame, decisiones: pd.DataFrame | None = None, semanas: int = 8,
                        hoy: date | None = None) -> pd.DataFrame:
    """Validaciones humanas por semana (simuladas: repartidas entre el inicio y el cierre de cada auditoría)."""
    hoy = hoy or date.today()
    rng = np.random.default_rng(7)
    fechas = []
    for r in df[~df.real].itertuples():
        fin = r.cierre or hoy
        span = max((fin - r.inicio).days, 1)
        fechas += [r.inicio + timedelta(days=int(d)) for d in rng.integers(0, span + 1, r.validados)]
    if decisiones is not None and not decisiones.empty:          # validaciones reales de la auditoría actual
        fechas += list(pd.to_datetime(decisiones.fecha_hora).dt.date)
    s = pd.Series(1, index=pd.to_datetime(fechas)).resample("W-MON", label="left", closed="left").sum()
    desde = pd.Timestamp(hoy) - pd.Timedelta(weeks=semanas)
    s = s[s.index >= desde]
    return s.rename("validaciones").reset_index().rename(columns={"index": "semana"})
