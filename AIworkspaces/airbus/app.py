"""
Demo Airbus: informe de auditoría de cumplimiento (Part-IS) con revisión humana.

Ejecutar desde la carpeta airbus/:
    python -m streamlit run app.py
(antes: python -m src.pipeline)

Estilo visual inspirado en el enunciado del reto (azul marino, acento cian, tarjetas claras).
Es un prototipo del equipo: no usa el logo de Airbus ni se presenta como herramienta oficial.
"""
import html
import json
import re
from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import db, llm, normativa

st.set_page_config(page_title="Auditoría Part-IS", page_icon="🛡️", layout="wide")

# --------------------------------------------------------------------------- paleta (del PDF del enunciado)
MARINO, CIAN, CIAN_TXT = "#14284B", "#009FE3", "#0077B0"   # CIAN_TXT: cian con contraste AA sobre blanco
FONDO, BORDE, GRIS = "#F2F6FB", "#D5DEEA", "#5B6B82"
COLOR = {"Cumple": "#2E9E5B", "No cumple": "#D64545", "Revisar": "#C98A00", "No aplica": "#7A8699"}
ORDEN = {"No cumple": 0, "Revisar": 1, "Cumple": 2, "No aplica": 3}

st.markdown(f"""
<style>
  .block-container {{ padding-top: 1.6rem; max-width: 1320px; }}
  h1, h2, h3, h4 {{ color: {MARINO}; }}
  .hero {{ background: {MARINO}; color: #fff; border-radius: 14px; padding: 22px 28px 18px; margin-bottom: 18px; }}
  .hero .eyebrow {{ color: {CIAN}; font-weight: 700; letter-spacing: .06em; font-size: .78rem; text-transform: uppercase; }}
  .hero h1 {{ color: #fff; font-size: 1.95rem; margin: 4px 0 0; padding: 0; line-height: 1.2; }}
  .hero .rule {{ width: 110px; height: 4px; background: {CIAN}; border-radius: 2px; margin: 12px 0 10px; }}
  .hero .sub {{ color: #C9D6EA; font-size: .95rem; }}
  .pill {{ display: inline-block; border: 1px solid rgba(255,255,255,.35); border-radius: 999px;
          padding: 2px 11px; font-size: .78rem; margin: 10px 6px 0 0; color: #E6EEF8; }}
  .kpi {{ background: {FONDO}; border: 1px solid {BORDE}; border-radius: 12px; padding: 14px 18px;
         display: flex; align-items: center; gap: 12px; box-shadow: 0 1px 2px rgba(20,40,75,.06); }}
  .kpi .dot {{ width: 20px; height: 20px; border-radius: 50%; flex: none; }}
  .kpi .num {{ font-size: 2.35rem; font-weight: 800; line-height: 1; }}
  .kpi .lbl {{ font-weight: 600; color: {MARINO}; line-height: 1.15; }}
  .met {{ background: {MARINO}; color: #fff; border-radius: 12px; padding: 14px 18px; }}
  .met .v {{ font-size: 2rem; font-weight: 800; line-height: 1.1; }}
  .met .t {{ color: #C9D6EA; font-size: .85rem; }}
  .met .ref {{ font-size: .78rem; margin-top: 4px; }}
  .ok {{ color: #7BE0A6; font-weight: 700; }} .ko {{ color: #FF9C9C; font-weight: 700; }}
  .sec {{ display: flex; align-items: center; gap: 10px; font-size: 1.3rem; font-weight: 700; color: {MARINO}; margin: 6px 0 10px; }}
  .sec .n {{ width: 32px; height: 32px; border-radius: 50%; background: {CIAN}; color: #fff; display: grid;
            place-items: center; font-weight: 800; font-size: 1rem; flex: none; }}
  .card {{ border: 1px solid {BORDE}; border-radius: 12px; overflow: hidden; background: #fff; margin-bottom: 12px; }}
  .card .hd {{ background: {MARINO}; color: #fff; padding: 9px 16px; font-weight: 700; font-size: .95rem; }}
  .card .hd small {{ color: #C9D6EA; font-weight: 400; }}
  .card .bd {{ padding: 14px 16px; color: #1B2333; }}
  .quote {{ border-left: 4px solid {CIAN}; background: {FONDO}; padding: 10px 14px; border-radius: 0 8px 8px 0;
           font-style: italic; color: {MARINO}; }}
  .req {{ border-left: 4px solid var(--c); background: {FONDO}; padding: 10px 14px; border-radius: 0 8px 8px 0; font-size: 1.02rem; }}
  .chip {{ color: #fff; padding: 3px 12px; border-radius: 999px; font-size: .82rem; font-weight: 700; white-space: nowrap; }}
  .tag {{ display: inline-block; background: #FFF1F1; border: 1px solid #F3C4C4; color: #8A1F1F; border-radius: 6px;
         padding: 1px 8px; margin: 2px 4px 2px 0; font-size: .85rem; }}
  .nota {{ border-left: 3px solid {CIAN}; padding: 6px 12px; color: {GRIS}; font-size: .9rem; background: #F7FAFD; }}
  .bar {{ height: 8px; background: #E3EAF3; border-radius: 4px; overflow: hidden; margin-top: 4px; }}
  .bar > div {{ height: 100%; background: {CIAN_TXT}; }}
  mark {{ background: #FFD9D9; color: #5A0F0F; padding: 0 2px; border-radius: 3px; }}
  .stTabs [data-baseweb="tab"] {{ font-weight: 600; color: {GRIS}; }}
  .stTabs [aria-selected="true"] {{ color: {CIAN_TXT}; }}
  .pie {{ color: {GRIS}; font-size: .8rem; text-align: center; margin-top: 28px; border-top: 1px solid {BORDE}; padding-top: 10px; }}
</style>""", unsafe_allow_html=True)

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
    return f"<span class='chip' style='background:{COLOR.get(v, '#999')}'>{v}</span>"


def resaltar(texto: str, trozos: list[str]) -> str:
    t = html.escape(texto)
    for trozo in sorted({x for x in trozos if x}, key=len, reverse=True):
        t = re.sub(re.escape(html.escape(trozo)), lambda m: f"<mark>{m.group(0)}</mark>", t, flags=re.I)
    return t


def seccion(n: int, titulo: str):
    st.markdown(f"<div class='sec'><span class='n'>{n}</span>{titulo}</div>", unsafe_allow_html=True)


# --------------------------------------------------------------------------- cabecera
juez = "reglas + LLM" if llm.disponible() else "reglas (sin LLM)"
doc = h["ubicacion"].iloc[0] if len(h) else ""
st.markdown(f"""
<div class="hero">
  <div class="eyebrow">IndesIAhack 2026 · Reto Airbus Defence and Space</div>
  <h1>Verificación de cumplimiento normativo · EASA Part-IS</h1>
  <div class="rule"></div>
  <div class="sub">Cada requisito del documento se contrasta con la cláusula de la norma que le aplica.
  La IA propone; el revisor decide.</div>
  <span class="pill">Normativa: Reg. (UE) 2023/203 · 2022/1645</span>
  <span class="pill">{len(h)} requisitos</span>
  <span class="pill">Juez: {juez}</span>
  <span class="pill">{h.revisado.sum()}/{len(h)} revisados</span>
</div>""", unsafe_allow_html=True)

c = h.veredicto.value_counts()
for col, v in zip(st.columns(4), ["Cumple", "No cumple", "Revisar", "No aplica"]):
    etiqueta = "Requiere revisión" if v == "Revisar" else v
    col.markdown(f"<div class='kpi'><span class='dot' style='background:{COLOR[v]}'></span>"
                 f"<span class='num' style='color:{COLOR[v]}'>{c.get(v, 0)}</span>"
                 f"<span class='lbl'>{etiqueta}</span></div>", unsafe_allow_html=True)

ev = metricas.get("evaluacion")
st.write("")
if ev:
    e, s = ev["deteccion_estricta"], ev["deteccion_senalados"]
    cobm = metricas["cobertura"]

    def met(col, titulo, valor, ref_txt, ok):
        marca = "" if ok is None else (f"<span class='ok'>✓ cumple</span>" if ok else f"<span class='ko'>✗ por debajo</span>")
        col.markdown(f"<div class='met'><div class='t'>{titulo}</div><div class='v'>{valor}</div>"
                     f"<div class='ref'>{ref_txt} {marca}</div></div>", unsafe_allow_html=True)

    m1, m2, m3, m4 = st.columns(4)
    met(m1, "F1 detección de incumplimientos", f"{e['f1']:.2f}".replace(".", ","), "Referencia ≥ 0,80 ·", e["f1"] >= 0.8)
    met(m2, "F1 señalados (No cumple + Revisar)", f"{s['f1']:.2f}".replace(".", ","), "Lo que llega al revisor", None)
    met(m3, "Hallazgos enlazados a su regla", f"{ev['trazabilidad_pct']:.0%}", "Referencia ≥ 90 % ·", ev["trazabilidad_pct"] >= 0.9)
    met(m4, "Cobertura reglas IS.I.OR", f"{cobm['cubiertas']}/{cobm['total']}", "Reglas IR tocadas por el documento", None)

st.write("")
tab_h, tab_m, tab_c, tab_cob, tab_a, tab_x = st.tabs(
    ["Hallazgos", "Matriz requisitos × reglas", "Consistencia", "Cobertura", "Agentes y métricas", "Exportar informe"])

# --------------------------------------------------------------------------- 1 · hallazgos
with tab_h:
    seccion(1, "Hallazgos por requisito")
    f1, f2, f3 = st.columns([2, 2, 1])
    estados = f1.multiselect("Estado", list(ORDEN), default=["No cumple", "Revisar", "Cumple"])
    reglas = f2.multiselect("Regla", sorted(x for x in h.clausula.unique() if x), placeholder="Todas")
    solo_pend = f3.toggle("Solo pendientes", value=False)
    vista = h[h.veredicto.isin(estados)]
    if reglas:
        vista = vista[vista.clausula.isin(reglas)]
    if solo_pend:
        vista = vista[~vista.revisado]

    tabla = vista.assign(
        Requisito=vista.req_id + " · " + vista.tema.replace("", "—"),
        Regla=("Part-IS · " + vista.clausula + " " + vista.apartado).where(vista.clausula != "", "—"),
        Estado=vista.veredicto, Confianza=vista.confianza,
        Revisado=vista.revisado.map({True: "✓", False: ""}),
        Justificación=vista.justificacion.str.slice(0, 140),
    )[["Requisito", "Regla", "Estado", "Confianza", "Revisado", "Justificación"]]
    st.caption("Marca la casilla de la izquierda de una fila (o usa el selector de abajo) para ver su detalle y decidir.")
    sel = st.dataframe(tabla, hide_index=True, width="stretch", on_select="rerun",
                       selection_mode="single-row", height=min(330, 38 + 35 * len(tabla)),
                       column_config={"Confianza": st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                                      "Revisado": st.column_config.TextColumn(width="small")})

    # Requisito en detalle: SIEMPRE visible y explícito (antes, sin fila marcada se mostraba el primero de la lista
    # y parecía que el detalle contradecía a la tabla).
    filas = sel.selection.rows if sel and sel.selection else []
    rid = None
    if len(vista):
        ids = list(vista.req_id)
        marcado = ids[filas[0]] if filas and filas[0] < len(ids) else None
        etiquetas = {i: f"{i} · {v} · {t or 'sin regla'}" for i, v, t in zip(vista.req_id, vista.veredicto, vista.tema)}
        rid = st.selectbox("Requisito en detalle", ids, index=ids.index(marcado) if marcado else 0,
                           format_func=etiquetas.get, key=f"detalle_{marcado or 'ninguno'}")
    if rid:
        r = h[h.req_id == rid].iloc[0]
        st.write("")
        izq, der = st.columns(2, gap="medium")
        with izq:
            ia = (f" · <small>la IA proponía {r.veredicto_ia}</small>" if r.veredicto != r.veredicto_ia else "")
            faltan = "".join(f"<span class='tag'>{html.escape(x)}</span>" for x in r.faltan)
            reflexion = r.get("reflexion")
            st.markdown(f"""
<div class="card"><div class="hd">Requisito {r.req_id} <small>· {html.escape(r.seccion)} · {r.ubicacion}</small></div>
<div class="bd">
  <div class="req" style="--c:{COLOR[r.veredicto]}">{resaltar(r.texto, r.resaltar)}</div>
  <div style="display:flex;align-items:center;gap:12px;margin:14px 0 4px">{chip(r.veredicto)}
    <span style="color:{GRIS};font-size:.88rem">confianza {r.confianza:.2f} · juez: {r.juez}{ia}</span></div>
  <div class="bar"><div style="width:{r.confianza * 100:.0f}%"></div></div>
  <p style="margin:12px 0 6px"><b>Justificación.</b> {html.escape(r.justificacion)}</p>
  {f"<p style='margin:6px 0'><b>Elementos exigidos que faltan:</b><br>{faltan}</p>" if faltan else ""}
  {f"<div class='nota'>Bucle de reflexión · {html.escape(reflexion)}</div>" if isinstance(reflexion, str) and reflexion else ""}
  {f"<div class='nota'>Autoconsistencia LLM: {', '.join(r.llm_votos)}</div>" if r.llm_votos else ""}
</div></div>""", unsafe_allow_html=True)
        with der:
            if r.clausula:
                cl = clausulas().get(r.clausula)
                fuente = cl["fuente"] if cl else ""
                st.markdown(f"""
<div class="card"><div class="hd">Regla aplicable · {r.clausula} {r.apartado} <small>· {html.escape(r.tema)}</small></div>
<div class="bd">
  <div class="quote">{html.escape(r.texto_norma)}</div>
  <p style="margin:10px 0 0;color:{GRIS};font-size:.88rem">{html.escape(cl['titulo']) if cl else ''} · {fuente}</p>
</div></div>""", unsafe_allow_html=True)
                st.link_button(f"Abrir {r.clausula} en EASA ↗", normativa.url_clausula(r.clausula))
                if cl:
                    with st.expander(f"Texto completo de {r.clausula}"):
                        st.text(cl["texto"])
                with st.expander("Detalle técnico de la recuperación (RAG)"):
                    st.write("Obligaciones candidatas y su puntuación BM25: " + " · ".join(r.candidatas))
            else:
                st.markdown(f"""<div class="card"><div class="hd">Sin regla aplicable</div>
<div class="bd">El requisito no trata de seguridad de la información: queda fuera del alcance de Part-IS.</div></div>""",
                            unsafe_allow_html=True)

        st.markdown(f"<div class='card'><div class='hd'>Decisión del revisor <small>· humano en el bucle</small></div></div>",
                    unsafe_allow_html=True)
        d1, d2, d3, d4 = st.columns([1.1, 1.3, 2.2, 1.1])
        if d1.button("Aprobar propuesta", key=f"a_{rid}", type="primary", width="stretch"):
            db.registrar_decision(rid, "aprobado", r.veredicto_ia, st.session_state.get(f"c_{rid}", ""))
            st.rerun()
        nuevo = d2.selectbox("Veredicto final", list(ORDEN), index=list(ORDEN).index(r.veredicto), key=f"v_{rid}",
                             label_visibility="collapsed")
        d3.text_input("Comentario", key=f"c_{rid}", placeholder="Comentario (opcional)", label_visibility="collapsed")
        if d4.button("Guardar corrección", key=f"g_{rid}", width="stretch"):
            db.registrar_decision(rid, "corregido", nuevo, st.session_state.get(f"c_{rid}", ""))
            st.rerun()

# --------------------------------------------------------------------------- 2 · matriz
with tab_m:
    seccion(2, "Matriz requisitos × reglas")
    st.caption("Qué requisito se apoya en qué regla y con qué resultado. Una columna vacía es una regla sin cubrir.")
    ap = h[h.clausula != ""].copy()
    columnas = list(cob.clausula) if len(cob) else sorted(ap.clausula.unique())
    filas_m = sorted(ap.req_id)
    z = pd.DataFrame(index=filas_m, columns=columnas, dtype=float)
    for row in ap.itertuples():
        z.loc[row.req_id, row.clausula] = {"Cumple": 1, "Revisar": 0, "No cumple": -1}.get(row.veredicto)
    texto = z.map(lambda v: {1: "Cumple", 0: "Revisar", -1: "No cumple"}.get(v, ""))
    fig = go.Figure(go.Heatmap(
        z=z.values, x=[x.replace("IS.I.OR.", "OR.") for x in columnas], y=filas_m, text=texto.values,
        hovertemplate="%{y} · %{x}<br>%{text}<extra></extra>", zmin=-1, zmax=1, showscale=False, xgap=3, ygap=3,
        colorscale=[[0, COLOR["No cumple"]], [0.5, COLOR["Revisar"]], [1, COLOR["Cumple"]]]))
    fig.update_layout(height=60 + 20 * len(filas_m), margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor=FONDO,
                      font=dict(color=MARINO), xaxis=dict(side="top"), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")
    st.markdown(" ".join(f"{chip(v)}" for v in ["Cumple", "Revisar", "No cumple"]), unsafe_allow_html=True)

# --------------------------------------------------------------------------- 3 · consistencia
with tab_c:
    seccion(3, "Consistencia del documento")
    st.markdown("**Contradicciones entre requisitos**")
    if contra.empty:
        st.success("No se han detectado contradicciones.")
    for row in contra.itertuples():
        ta = h.loc[h.req_id == row.req_a, "texto"].iloc[0]
        tb = h.loc[h.req_id == row.req_b, "texto"].iloc[0]
        st.markdown(f"""
<div class="card"><div class="hd">{html.escape(row.parametro.capitalize())} <small>· {html.escape(row.valor_a)} frente a {html.escape(row.valor_b)}</small></div>
<div class="bd" style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
  <div><b>{row.req_a}</b><br>{resaltar(ta, [row.valor_a])}</div>
  <div><b>{row.req_b}</b><br>{resaltar(tb, [row.valor_b])}</div>
</div></div>""", unsafe_allow_html=True)
    st.markdown("**Homogeneidad del detalle**")
    st.caption("Requisitos mucho más escuetos que el resto de su sección o sin criterio verificable.")
    st.dataframe(homo.rename(columns={"req_id": "Requisito", "palabras": "Palabras", "motivo": "Motivo"}),
                 hide_index=True, width="stretch")

# --------------------------------------------------------------------------- 4 · cobertura
with tab_cob:
    seccion(4, "Cobertura de la normativa")
    st.caption("Reglas obligatorias (IR) de Part-IS para organizaciones (IS.I.OR) y qué requisitos las cubren.")
    st.dataframe(cob.assign(cubierta=cob.cubierta.map({True: "✓", False: "✗", 1: "✓", 0: "✗"})).rename(columns={
        "clausula": "Cláusula", "titulo": "Título", "requisitos": "Requisitos", "cubierta": "Cubierta"}),
        hide_index=True, width="stretch")

# --------------------------------------------------------------------------- 5 · agentes
with tab_a:
    seccion(5, "Arquitectura agéntica (LangGraph)")
    pasos = ["Supervisor", "Extractor", "Auditor", "Reflexión", "Trazabilidad", "Crítico", "Revisión humana", "Cierre"]
    st.markdown("<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px'>" +
                " <span style='color:#9AA8BC'>→</span> ".join(
                    f"<span style='background:{MARINO if i else CIAN};color:#fff;border-radius:8px;padding:6px 12px;"
                    f"font-weight:600;font-size:.88rem'>{p}</span>" for i, p in enumerate(pasos)) + "</div>",
                unsafe_allow_html=True)
    for p in traza.paso:
        st.markdown(f"<div class='nota' style='margin-bottom:6px'>{html.escape(p)}</div>", unsafe_allow_html=True)
    if ev:
        st.markdown("**Evaluación contra el gold set**")
        filas = []
        for nombre, k in [("Detección estricta (No cumple)", "deteccion_estricta"),
                          ("Detección señalados (No cumple + Revisar)", "deteccion_senalados"), ("Contradicciones", "contradicciones")]:
            if k in ev:
                filas.append({"Métrica": nombre, **{x: ev[k][x] for x in ["precision", "recall", "f1", "tp", "fp", "fn"]}})
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
        st.caption(f"Trazabilidad: {ev['trazabilidad_pct']:.0%} de los hallazgos citan la cláusula del gold · "
                   f"exactitud del veredicto: {ev['exactitud_veredicto']:.0%}")

# --------------------------------------------------------------------------- 6 · exportar
with tab_x:
    seccion(6, "Exportar informe")
    st.caption("Informe HTML autocontenido con el estado actual, incluidas las decisiones del revisor.")

    def informe_html() -> str:
        filas = "".join(
            f"<tr><td><b>{x.req_id}</b><br><small>{html.escape(x.tema or '')}</small></td>"
            f"<td>{x.clausula} {x.apartado}</td><td>{chip(x.veredicto)}{' ✓' if x.revisado else ''}</td>"
            f"<td>{resaltar(x.texto, x.resaltar)}</td><td>{html.escape(x.justificacion)}</td></tr>"
            for x in h.itertuples())
        contr = "".join(f"<li><b>{x.parametro}</b>: {html.escape(x.explicacion)}</li>" for x in contra.itertuples())
        kpis = "".join(f"<div class='k'><span style='color:{COLOR[k]}'>{c.get(k, 0)}</span> {k}</div>" for k in ORDEN)
        return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Informe de auditoría Part-IS</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:0;color:#1B2333}} header{{background:{MARINO};color:#fff;padding:24px 32px}}
header .r{{width:110px;height:4px;background:{CIAN};margin:10px 0}} main{{padding:24px 32px}}
.ks{{display:flex;gap:12px;margin-bottom:20px}} .k{{background:{FONDO};border:1px solid {BORDE};border-radius:10px;padding:10px 16px;font-weight:600}}
.k span{{font-size:1.6em;font-weight:800}} table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid {BORDE};padding:8px;vertical-align:top;font-size:14px}} th{{background:{MARINO};color:#fff;text-align:left}}
.chip{{color:#fff;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700}} mark{{background:#FFD9D9}}</style></head><body>
<header><small style="color:{CIAN};font-weight:700">INDESIAHACK 2026 · PROTOTIPO DEL EQUIPO</small>
<h1 style="margin:4px 0 0">Informe de auditoría de cumplimiento · EASA Part-IS</h1><div class="r"></div>
Generado: {datetime.now():%d/%m/%Y %H:%M} · revisados {h.revisado.sum()}/{len(h)}</header>
<main><div class="ks">{kpis}</div>
<h2>Hallazgos</h2><table><tr><th>Requisito</th><th>Regla</th><th>Estado</th><th>Texto</th><th>Justificación</th></tr>{filas}</table>
<h2>Contradicciones</h2><ul>{contr or '<li>Ninguna</li>'}</ul></main></body></html>"""

    a, b = st.columns(2)
    a.download_button("Descargar informe HTML", informe_html(), file_name="informe_auditoria_part_is.html",
                      mime="text/html", type="primary", width="stretch")
    b.download_button("Descargar hallazgos CSV", h.drop(columns=["orden"]).to_csv(index=False).encode("utf-8"),
                      file_name="hallazgos.csv", width="stretch")

st.markdown("<div class='pie'>Prototipo del equipo para IndesIAhack 2026 · datos sintéticos y normativa pública de EASA · "
            "no es una herramienta oficial de Airbus</div>", unsafe_allow_html=True)
