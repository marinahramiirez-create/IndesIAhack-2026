"""
Demo Airbus: informe de auditoría de cumplimiento (Part-IS) con revisión humana.

Ejecutar desde la carpeta airbus/:
    streamlit run app.py
(antes: python -m src.pipeline)
"""
import html
import json
import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import streamlit as st

from src import db, normativa

st.set_page_config(page_title="Airbus · Auditoría Part-IS", page_icon="✈️", layout="wide")

COLOR = {"Cumple": "#2e9e5b", "No cumple": "#d64545", "Revisar": "#e0a100", "No aplica": "#8a94a6"}
ORDEN = {"No cumple": 0, "Revisar": 1, "Cumple": 2, "No aplica": 3}

if not db.existe_tabla("hallazgos"):
    st.error("Todavía no hay auditoría. En la terminal, dentro de la carpeta airbus/, ejecuta:")
    st.code("python datos_sinteticos/generar.py\npython -m src.pipeline")
    st.stop()


@st.cache_data(show_spinner=False)
def cargar():
    h = db.leer_df("SELECT * FROM hallazgos")
    for c in ["resaltar", "faltan", "violaciones", "vaguedad", "candidatas", "llm_votos"]:
        h[c] = h[c].apply(json.loads)
    m = {r.clave: json.loads(r.valor) for r in db.leer_df("SELECT * FROM metricas").itertuples()}
    return (h, db.leer_df("SELECT * FROM contradicciones"), db.leer_df("SELECT * FROM homogeneidad"),
            db.leer_df("SELECT * FROM cobertura"), db.leer_df("SELECT * FROM traza"), m)


@st.cache_data(show_spinner=False)
def clausulas():
    return normativa.por_id()


h, contra, homo, cob, traza, metricas = cargar()
dec = db.ultimas_decisiones()
final = dict(zip(dec.req_id, dec.veredicto_final)) if not dec.empty else {}
revisado = set(dec.req_id) if not dec.empty else set()
h["veredicto_ia"] = h["veredicto"]
h["veredicto"] = h.apply(lambda r: final.get(r.req_id, r.veredicto_ia), axis=1)
h["revisado"] = h.req_id.isin(revisado)
h["orden"] = h.veredicto.map(ORDEN)
h = h.sort_values(["orden", "confianza", "req_id"])


def chip(v: str) -> str:
    return (f"<span style='background:{COLOR.get(v, '#999')};color:white;padding:2px 10px;"
            f"border-radius:12px;font-size:0.85em;font-weight:600'>{v}</span>")


def resaltar(texto: str, trozos: list[str]) -> str:
    t = html.escape(texto)
    for trozo in sorted({x for x in trozos if x}, key=len, reverse=True):
        t = re.sub(re.escape(html.escape(trozo)), lambda m: f"<mark style='background:#ffd6d6'>{m.group(0)}</mark>", t, flags=re.I)
    return t


# --------------------------------------------------------------------------- cabecera
st.title("✈️ Auditoría de cumplimiento · EASA Part-IS")
st.caption("Cada requisito del documento se contrasta con la cláusula de la norma que le aplica. "
           "La IA propone; el revisor decide.")

c = h.veredicto.value_counts()
cols = st.columns(5)
for col, v in zip(cols, ["Cumple", "No cumple", "Revisar", "No aplica"]):
    col.markdown(f"<div style='border:1px solid #ddd;border-radius:10px;padding:10px 16px'>"
                 f"<span style='font-size:2.2em;font-weight:700;color:{COLOR[v]}'>{c.get(v, 0)}</span>"
                 f"&nbsp; {v}</div>", unsafe_allow_html=True)
cols[4].markdown(f"<div style='border:1px solid #ddd;border-radius:10px;padding:10px 16px'>"
                 f"<span style='font-size:2.2em;font-weight:700'>{h.revisado.sum()}/{len(h)}</span>"
                 f"&nbsp; revisados</div>", unsafe_allow_html=True)

ev = metricas.get("evaluacion")
if ev:
    e, s = ev["deteccion_estricta"], ev["deteccion_senalados"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("F1 detección (No cumple)", f"{e['f1']:.2f}", help="Frente al gold set. Referencia del jurado ≥ 0,80")
    m2.metric("F1 señalados (No cumple + Revisar)", f"{s['f1']:.2f}")
    m3.metric("Trazabilidad hallazgo → cláusula", f"{ev['trazabilidad_pct']:.0%}", help="Referencia del jurado ≥ 90 %")
    cobm = metricas["cobertura"]
    m4.metric("Cobertura reglas IS.I.OR", f"{cobm['cubiertas']}/{cobm['total']}")

tab_h, tab_m, tab_c, tab_cob, tab_a, tab_x = st.tabs(
    ["📋 Hallazgos", "🧩 Matriz requisitos × reglas", "⚠️ Consistencia", "🗺️ Cobertura", "🤖 Agentes y métricas", "📤 Exportar"])

# --------------------------------------------------------------------------- hallazgos
with tab_h:
    f1, f2, f3 = st.columns(3)
    estados = f1.multiselect("Estado", list(ORDEN), default=["No cumple", "Revisar", "Cumple"])
    reglas = f2.multiselect("Regla", sorted(x for x in h.clausula.unique() if x))
    solo_pend = f3.toggle("Solo pendientes de revisar", value=False)
    vista = h[h.veredicto.isin(estados)]
    if reglas:
        vista = vista[vista.clausula.isin(reglas)]
    if solo_pend:
        vista = vista[~vista.revisado]

    tabla = vista.assign(
        Requisito=vista.req_id + " · " + vista.tema.replace("", "—"),
        Regla=("Part-IS · " + vista.clausula + " " + vista.apartado).where(vista.clausula != "", "—"),
        Estado=vista.veredicto, Confianza=vista.confianza,
        Revisado=vista.revisado.map({True: "✅", False: ""}),
        Justificación=vista.justificacion.str.slice(0, 160),
    )[["Requisito", "Regla", "Estado", "Confianza", "Revisado", "Justificación"]]
    sel = st.dataframe(tabla, hide_index=True, width="stretch", on_select="rerun",
                       selection_mode="single-row", height=min(420, 38 + 35 * len(tabla)),
                       column_config={"Confianza": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f")})

    filas = sel.selection.rows if sel and sel.selection else []
    rid = vista.iloc[filas[0]].req_id if filas else (vista.iloc[0].req_id if len(vista) else None)
    if rid:
        r = h[h.req_id == rid].iloc[0]
        st.divider()
        st.markdown(f"### {r.req_id} &nbsp; {chip(r.veredicto)}"
                    + (f" &nbsp; <small>(IA proponía {r.veredicto_ia})</small>" if r.veredicto != r.veredicto_ia else ""),
                    unsafe_allow_html=True)
        izq, der = st.columns(2)
        with izq:
            st.markdown(f"**Requisito** · {r.documento if 'documento' in r else ''} {r.ubicacion} · {r.seccion}")
            st.markdown(f"<div style='border-left:4px solid {COLOR[r.veredicto]};padding:8px 12px;background:rgba(127,127,127,0.07)'>"
                        f"{resaltar(r.texto, r.resaltar)}</div>", unsafe_allow_html=True)
            st.markdown(f"**Justificación** (confianza {r.confianza:.2f} · juez: {r.juez})")
            st.write(r.justificacion)
            if r.faltan:
                st.markdown("**Elementos exigidos que faltan:** " + ", ".join(r.faltan))
            if isinstance(r.get("reflexion"), str) and r.reflexion:
                st.info("🔁 Bucle de reflexión: " + r.reflexion)
            if r.llm_votos:
                st.caption(f"Autoconsistencia LLM: {', '.join(r.llm_votos)}")
        with der:
            if r.clausula:
                st.markdown(f"**Regla aplicable** · [{r.clausula} {r.apartado}]({normativa.url_clausula(r.clausula)}) — {r.tema}")
                st.markdown(f"<div style='border-left:4px solid #1f3b73;padding:8px 12px;background:rgba(31,59,115,0.06)'>"
                            f"<i>{html.escape(r.texto_norma)}</i></div>", unsafe_allow_html=True)
                cl = clausulas().get(r.clausula)
                if cl:
                    with st.expander(f"Texto completo de {r.clausula} · {cl['titulo']} ({cl['fuente']})"):
                        st.text(cl["texto"])
                st.caption("Cláusulas candidatas recuperadas (RAG): " + " · ".join(r.candidatas))
            else:
                st.markdown("**Sin regla aplicable** (fuera del alcance de Part-IS)")

        st.markdown("**Decisión del revisor** (humano en el bucle)")
        d1, d2, d3 = st.columns([1, 1, 2])
        nuevo = d2.selectbox("Veredicto final", list(ORDEN), index=list(ORDEN).index(r.veredicto), key=f"v_{rid}")
        comentario = d3.text_input("Comentario", key=f"c_{rid}")
        if d1.button("✅ Aprobar propuesta", key=f"a_{rid}", width="stretch"):
            db.registrar_decision(rid, "aprobado", r.veredicto_ia, comentario)
            st.rerun()
        if d1.button("✏️ Guardar corrección", key=f"g_{rid}", width="stretch"):
            db.registrar_decision(rid, "corregido", nuevo, comentario)
            st.rerun()

# --------------------------------------------------------------------------- matriz
with tab_m:
    st.caption("Qué requisito se apoya en qué regla y con qué resultado. Huecos en una columna = regla sin cubrir.")
    ap = h[h.clausula != ""].copy()
    reglas_ir = [x for x in cob.clausula] if len(cob) else sorted(ap.clausula.unique())
    mat = pd.DataFrame(index=sorted(ap.req_id), columns=reglas_ir, dtype=float)
    for row in ap.itertuples():
        mat.loc[row.req_id, row.clausula] = {"Cumple": 1, "Revisar": 0, "No cumple": -1}.get(row.veredicto, None)
    fig = px.imshow(mat.astype(float), color_continuous_scale=[COLOR["No cumple"], COLOR["Revisar"], COLOR["Cumple"]],
                    zmin=-1, zmax=1, aspect="auto")
    fig.update_layout(height=40 + 18 * len(mat), coloraxis_showscale=False, margin=dict(l=0, r=0, t=10, b=0))
    fig.update_xaxes(side="top", tickangle=-45)
    st.plotly_chart(fig, width="stretch")
    st.caption("🟩 Cumple · 🟨 Revisar · 🟥 No cumple")

# --------------------------------------------------------------------------- consistencia
with tab_c:
    st.subheader("Contradicciones entre requisitos")
    if contra.empty:
        st.success("No se han detectado contradicciones.")
    for row in contra.itertuples():
        ta = h.loc[h.req_id == row.req_a, "texto"].iloc[0]
        tb = h.loc[h.req_id == row.req_b, "texto"].iloc[0]
        with st.container(border=True):
            st.markdown(f"**{row.parametro}** — {row.explicacion}")
            a, b = st.columns(2)
            a.markdown(f"**{row.req_a}**: {resaltar(ta, [row.valor_a])}", unsafe_allow_html=True)
            b.markdown(f"**{row.req_b}**: {resaltar(tb, [row.valor_b])}", unsafe_allow_html=True)
    st.subheader("Homogeneidad del detalle")
    st.caption("Requisitos mucho más escuetos que el resto de su sección o sin criterio verificable.")
    st.dataframe(homo, hide_index=True, width="stretch")

# --------------------------------------------------------------------------- cobertura
with tab_cob:
    st.caption("Reglas obligatorias (IR) de Part-IS para organizaciones (IS.I.OR) y qué requisitos las cubren.")
    st.dataframe(cob.assign(cubierta=cob.cubierta.map({True: "✅", False: "❌", 1: "✅", 0: "❌"})),
                 hide_index=True, width="stretch")

# --------------------------------------------------------------------------- agentes
with tab_a:
    st.subheader("Qué hizo cada agente (LangGraph)")
    st.code("SUPERVISOR → Extractor → Auditor → Reflexión (si confianza baja) → Trazabilidad → Crítico → [revisión humana] → Cierre",
            language=None)
    for p in traza.paso:
        st.markdown(f"- {p}")
    if ev:
        st.subheader("Evaluación contra el gold set")
        filas = []
        for nombre, k in [("Detección estricta (No cumple)", "deteccion_estricta"),
                          ("Detección señalados (No cumple + Revisar)", "deteccion_senalados")]:
            filas.append({"métrica": nombre, **{x: ev[k][x] for x in ["precision", "recall", "f1", "tp", "fp", "fn"]}})
        if "contradicciones" in ev:
            filas.append({"métrica": "Contradicciones", **{x: ev["contradicciones"][x] for x in ["precision", "recall", "f1", "tp", "fp", "fn"]}})
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
        st.write(f"Trazabilidad: **{ev['trazabilidad_pct']:.0%}** de hallazgos citan la cláusula del gold · "
                 f"exactitud del veredicto: **{ev['exactitud_veredicto']:.0%}**")

# --------------------------------------------------------------------------- exportar
with tab_x:
    st.caption("Informe HTML autocontenido con el estado actual (incluye las decisiones del revisor).")

    def informe_html() -> str:
        filas = "".join(
            f"<tr><td><b>{x.req_id}</b><br><small>{html.escape(x.tema or '')}</small></td>"
            f"<td>{x.clausula} {x.apartado}</td><td>{chip(x.veredicto)}{' ✅' if x.revisado else ''}</td>"
            f"<td>{resaltar(x.texto, x.resaltar)}</td><td>{html.escape(x.justificacion)}</td></tr>"
            for x in h.itertuples())
        contr = "".join(f"<li><b>{x.parametro}</b>: {html.escape(x.explicacion)}</li>" for x in contra.itertuples())
        res = " · ".join(f"{k}: <b>{c.get(k, 0)}</b>" for k in ORDEN)
        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Informe auditoría Part-IS</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:24px;color:#1b2333}} table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid #ddd;padding:8px;vertical-align:top;font-size:14px}} th{{background:#14284b;color:white;text-align:left}}
mark{{background:#ffd6d6}}</style></head><body>
<h1>Informe de auditoría de cumplimiento · EASA Part-IS</h1>
<p>Generado: {datetime.now():%d/%m/%Y %H:%M} · {res} · revisados {h.revisado.sum()}/{len(h)}</p>
<h2>Hallazgos</h2><table><tr><th>Requisito</th><th>Regla</th><th>Estado</th><th>Texto</th><th>Justificación</th></tr>{filas}</table>
<h2>Contradicciones</h2><ul>{contr or '<li>Ninguna</li>'}</ul></body></html>"""

    st.download_button("⬇️ Descargar informe HTML", informe_html(), file_name="informe_auditoria_part_is.html",
                       mime="text/html", type="primary")
    st.download_button("⬇️ Descargar hallazgos CSV",
                       h.drop(columns=["orden"]).to_csv(index=False).encode("utf-8"), file_name="hallazgos.csv")
