"""
Informe de auditoría para el revisor (frontend opcional, guía §9.7).
Se alimenta SOLO de los ficheros que genera auditar.py (respuestas.csv + traza): sin lógica propia, para que
lo que ve el revisor y lo que se entrega no puedan discrepar.

    .venv\\Scripts\\python -m streamlit run app.py
"""
import csv
import html
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd
import plotly.express as px
import pymupdf
import streamlit as st

RAIZ = Path(__file__).resolve().parent
SALIDAS = RAIZ / "salidas"
from src.rutas import CORPUS  # noqa: E402  (ruta del corpus: .env o carpetas habituales)
DECISIONES = SALIDAS / "decisiones_revisor.csv"

st.set_page_config(page_title="Auditoría Part-IS · NIMBUS", page_icon="🛡️", layout="wide")
MARINO, CIAN = "#14284B", "#0077B0"
COLOR_TIPO = {"No cumple": "#D64545", "Inconsistencia": "#C98A00", "Cobertura faltante": "#7A4FD6",
              "Trazabilidad incorrecta": "#0077B0", "No verificable": "#5B6B82"}
st.markdown(f"""<style>
.block-container {{ padding-top: 1.4rem; max-width: 1400px; }}
.hero {{ background:{MARINO}; color:#fff; border-radius:14px; padding:18px 26px; margin-bottom:14px; }}
.hero h1 {{ color:#fff; font-size:1.7rem; margin:0; }} .hero .sub {{ color:#C9D6EA; }}
.kpi {{ background:#F2F6FB; border:1px solid #D5DEEA; border-radius:12px; padding:12px 16px; }}
.kpi .v {{ font-size:1.9rem; font-weight:800; color:{MARINO}; line-height:1.1; }} .kpi .t {{ color:#5B6B82; font-size:.85rem; }}
.chip {{ color:#fff; padding:2px 10px; border-radius:999px; font-size:.8rem; font-weight:700; }}
.ev {{ border-left:4px solid {CIAN}; background:#F2F6FB; padding:8px 12px; border-radius:0 8px 8px 0; font-style:italic; }}
mark {{ background:#FFD9D9; padding:0 2px; border-radius:3px; }}
</style>""", unsafe_allow_html=True)


# ------------------------------------------------------------------ datos
@st.cache_data
def cargar(ruta_csv: str):
    df = pd.read_csv(ruta_csv)
    traza_f = Path(ruta_csv).with_name(Path(ruta_csv).stem + "_traza.jsonl")
    traza = [json.loads(l) for l in open(traza_f, encoding="utf-8")] if traza_f.exists() else []
    return df, pd.DataFrame(traza)


@st.cache_data
def indice_corpus():
    """código de documento → (ruta, familia, texto por páginas). Usa la caché de transcripciones."""
    from src import ingesta
    idx = {}
    for f in sorted(CORPUS.rglob("*.pdf")):
        try:
            d = ingesta.leer(f, vision=True)
        except Exception:
            continue
        if d.codigo:
            idx[d.codigo] = {"ruta": str(f), "familia": f.parent.name, "paginas": d.paginas, "escaneado": d.escaneado}
    return idx


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[|«»\"]", " ", str(t).lower())).strip()


def pagina_de(evidencia: str, paginas: list[str]) -> int | None:
    ev = norm(evidencia)[:60]
    for i, p in enumerate(paginas, 1):
        if ev and ev in norm(p):
            return i
    return None


@st.cache_data
def png_pagina(ruta: str, n: int) -> bytes:
    return pymupdf.open(ruta)[n - 1].get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).tobytes("png")


def decisiones() -> dict:
    if not DECISIONES.exists():
        return {}
    d = {}
    for r in csv.DictReader(open(DECISIONES, encoding="utf-8")):
        d[(r["documento"], r["ubicacion"])] = r["decision"]
    return d


def guardar_decision(doc, ubic, decision, usuario):
    nuevo = not DECISIONES.exists()
    with open(DECISIONES, "a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if nuevo:
            w.writerow(["documento", "ubicacion", "decision", "usuario", "fecha_hora"])
        w.writerow([doc, ubic, decision, usuario, datetime.now().isoformat(timespec="seconds")])


# ------------------------------------------------------------------ cabecera
st.markdown("<div class='hero'><div style='color:#5FC3F0;font-weight:700;font-size:.8rem'>RETO AIRBUS · "
            "AUDITORÍA PART-IS CON IA AGÉNTICA</div><h1>Informe de hallazgos · NIMBUS Aerospace</h1>"
            "<div class='sub'>Cada hallazgo: ubicación exacta, cláusula de Part-IS, evidencia literal verificada "
            "por código y fuente de mayor rango.</div></div>", unsafe_allow_html=True)

csvs = sorted(SALIDAS.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
csvs = [c for c in csvs if not c.name.startswith(("clave", "decisiones"))]
if not csvs:
    st.error("No hay resultados. Ejecuta primero: .venv\\Scripts\\python auditar.py <carpeta_pdf> --salida salidas\\respuestas.csv")
    st.stop()
pref = next((c for c in csvs if c.name == "respuestas.csv"), csvs[0])
elegido = st.sidebar.selectbox("Resultados", csvs, index=csvs.index(pref), format_func=lambda p: p.name)
df, traza = cargar(str(elegido))
idx = indice_corpus()
df["familia"] = df.documento.map(lambda c: idx.get(c, {}).get("familia", "—"))
dec = decisiones()
df["revision"] = [dec.get((r.documento, r.ubicacion), "Pendiente") for r in df.itertuples()]

# filtros
st.sidebar.markdown("### Filtros")
f_fam = st.sidebar.multiselect("Familia", sorted(df.familia.unique()))
f_doc = st.sidebar.multiselect("Documento", sorted(df.documento.unique()))
f_tipo = st.sidebar.multiselect("Tipo de defecto", list(COLOR_TIPO))
f_cl = st.sidebar.multiselect("Cláusula Part-IS", sorted(df.clausula.astype(str).unique()))
f_orig = st.sidebar.multiselect("Origen", sorted(df.origen.astype(str).unique()),
                                help="regla = comprobación determinista · llm = agente de texto · vision = diagramas")
conf_min = st.sidebar.slider("Confianza mínima", 0.0, 1.0, 0.0, 0.05,
                             help="Más umbral = más precisión y menos cobertura")
v = df.copy()
for col, sel in (("familia", f_fam), ("documento", f_doc), ("tipo", f_tipo), ("clausula", f_cl), ("origen", f_orig)):
    if sel:
        v = v[v[col].astype(str).isin(sel)]
v = v[v.confianza.fillna(0) >= conf_min]

# KPIs
k = st.columns(5)
desc = int((~traza.aceptado).sum()) if len(traza) else 0
datos = [(len(v), "hallazgos"), (v.documento.nunique(), "documentos con hallazgos"),
         (f"{(v.clausula != '—').mean() * 100:.0f} %" if len(v) else "—", "con cláusula Part-IS"),
         (desc, "propuestas descartadas por el verificador"),
         ((v.revision != "Pendiente").sum(), "revisados por una persona")]
for c, (val, t) in zip(k, datos):
    c.markdown(f"<div class='kpi'><div class='v'>{val}</div><div class='t'>{t}</div></div>", unsafe_allow_html=True)
st.write("")

tab_h, tab_g, tab_m, tab_t = st.tabs(["Hallazgos", "Panorama", "Métricas", "Trazabilidad del sistema"])

# ------------------------------------------------------------------ hallazgos
with tab_h:
    izq, der = st.columns([1.15, 1])
    with izq:
        tabla = v[["documento", "ubicacion", "tipo", "clausula", "confianza", "origen", "revision"]].reset_index(drop=True)
        sel = st.dataframe(tabla, hide_index=True, width="stretch", height=560, on_select="rerun",
                           selection_mode="single-row",
                           column_config={"confianza": st.column_config.ProgressColumn("confianza", min_value=0, max_value=1)})
        filas = sel.selection.rows if sel and sel.selection else []
    with der:
        if not filas:
            st.info("Selecciona un hallazgo de la tabla para ver su evidencia en el documento.")
        else:
            r = v.reset_index(drop=True).iloc[filas[0]]
            col = COLOR_TIPO.get(r.tipo, "#5B6B82")
            st.markdown(f"### {r.documento} · {r.ubicacion}")
            st.markdown(f"<span class='chip' style='background:{col}'>{r.tipo}</span> &nbsp; **{r.clausula}** · "
                        f"confianza {r.confianza:.2f} · origen `{r.origen}`", unsafe_allow_html=True)
            st.markdown(f"**Justificación:** {r.justificacion}")
            if isinstance(r.evidencia, str) and r.evidencia:
                st.markdown(f"<div class='ev'>«{html.escape(r.evidencia)}»</div>", unsafe_allow_html=True)
            info = idx.get(r.documento)
            if info:
                n = pagina_de(r.evidencia, info["paginas"]) if isinstance(r.evidencia, str) else None
                if n:
                    st.caption(f"Evidencia localizada en la página {n} de {Path(info['ruta']).name}"
                               + (" (documento escaneado, transcrito con visión)" if info["escaneado"] else ""))
                    with st.expander("Ver la página del PDF", expanded=False):
                        st.image(png_pagina(info["ruta"], n), width="stretch")
            st.markdown("**Revisión humana**")
            c1, c2, c3 = st.columns([1, 1, 1.4])
            quien = c3.text_input("Revisor", value="revisor", label_visibility="collapsed")
            if c1.button("✔ Confirmar", type="primary", width="stretch"):
                guardar_decision(r.documento, r.ubicacion, "Confirmado", quien)
                st.rerun()
            if c2.button("✖ Falso positivo", width="stretch"):
                guardar_decision(r.documento, r.ubicacion, "Falso positivo", quien)
                st.rerun()
            st.caption(f"Estado actual: **{r.revision}**")

# ------------------------------------------------------------------ panorama
with tab_g:
    a, b = st.columns(2)
    g1 = v.groupby(["familia", "tipo"]).size().reset_index(name="n")
    a.plotly_chart(px.bar(g1, x="n", y="familia", color="tipo", orientation="h", color_discrete_map=COLOR_TIPO,
                          title="Hallazgos por familia y tipo"), width="stretch")
    g2 = v.clausula.astype(str).value_counts().reset_index()
    g2.columns = ["clausula", "n"]
    b.plotly_chart(px.bar(g2, x="clausula", y="n", title="Hallazgos por cláusula de Part-IS",
                          color_discrete_sequence=[CIAN]), width="stretch")
    g3 = v.groupby("documento").size().reset_index(name="n").sort_values("n", ascending=False).head(25)
    st.plotly_chart(px.bar(g3, x="documento", y="n", title="Documentos con más hallazgos",
                           color_discrete_sequence=[MARINO]), width="stretch")

# ------------------------------------------------------------------ métricas
with tab_m:
    st.markdown("Métricas del **puntuador oficial** del kit de desarrollo (19 documentos con clave). "
                "La evaluación final excluye los 5 documentos del núcleo (`--sin-nucleo`).")
    for nombre, f in (("Sin núcleo (como la evaluación final)", "metricas_sin_nucleo.txt"),
                      ("Corpus completo con clave", "metricas_completo.txt")):
        p = SALIDAS / f
        if p.exists():
            st.markdown(f"**{nombre}**")
            st.code(p.read_text(encoding="utf-8"), language=None)

# ------------------------------------------------------------------ traza
with tab_t:
    st.markdown("Cada propuesta del agente pasa por un **verificador de código**: formato de cláusula, ubicación "
                "existente, cita literal presente en el PDF, plazos recalculados con código y umbral de confianza.")
    if len(traza):
        t = traza.copy()
        t["resultado"] = t.aceptado.map({True: "Aceptado", False: "Descartado"})
        c1, c2 = st.columns([1, 2])
        c1.plotly_chart(px.pie(t, names="resultado", title="Propuestas del agente",
                               color="resultado", color_discrete_map={"Aceptado": "#2E9E5B", "Descartado": "#D64545"}),
                        width="stretch")
        motivos = t[~t.aceptado].descarte.str.extract(r"^(V\d)")[0].value_counts().reset_index()
        motivos.columns = ["regla", "n"]
        if len(motivos):
            c2.plotly_chart(px.bar(motivos, x="regla", y="n", title="Motivo de descarte (V1 formato · V2 ubicación · "
                                   "V3 cita no encontrada · V4 plazo cumplido · V5 confianza)",
                                   color_discrete_sequence=["#D64545"]), width="stretch")
        st.dataframe(t[~t.aceptado][["documento", "ubicacion", "tipo", "descarte", "justificacion"]],
                     hide_index=True, width="stretch")
