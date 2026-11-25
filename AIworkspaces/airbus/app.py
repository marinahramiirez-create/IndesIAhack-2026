"""
Demo Airbus: informe de auditoría de cumplimiento (Part-IS) con revisión humana. Bilingüe (ES / EN).

Ejecutar desde la carpeta airbus/:
    python -m streamlit run app.py
(antes: python -m src.pipeline)

Idioma: botón ES | EN arriba a la derecha (se recuerda en la URL: ?lang=en).
  - Español: la norma se muestra con el texto OFICIAL en español (Reg. de Ejecución (UE) 2023/203, DOUE).
  - Inglés:  la norma se muestra con el original de EASA (Easy Access Rules).
  - Los requisitos se muestran siempre en su idioma original (inglés): son la evidencia auditada.
Estilo visual inspirado en el enunciado del reto. Prototipo del equipo: no usa el logo de Airbus.
"""
import html
import json
import re
from datetime import datetime
from types import SimpleNamespace

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import auth, db, llm, normativa, normativa_es, textos

st.set_page_config(page_title="Part-IS audit", page_icon="🛡️", layout="wide")

# --------------------------------------------------------------------------- idioma
if "lang" not in st.session_state:
    st.session_state.lang = "en" if st.query_params.get("lang") == "en" else "es"
_, col_lang = st.columns([6, 1])
eleccion = col_lang.segmented_control("Idioma / Language", ["ES", "EN"], default=st.session_state.lang.upper(),
                                      label_visibility="collapsed", key="sel_lang")
LANG = (eleccion or st.session_state.lang.upper()).lower()
if LANG != st.session_state.lang:
    st.session_state.lang = LANG
if st.query_params.get("lang", "es") != LANG:   # solo si cambia: reescribirla en cada recarga provoca un bucle
    st.query_params["lang"] = LANG
T = textos.UI[LANG]


def V(veredicto: str) -> str:
    return textos.v(veredicto, LANG)


# --------------------------------------------------------------------------- paleta (del PDF del enunciado)
MARINO, CIAN, CIAN_TXT = "#14284B", "#009FE3", "#0077B0"   # CIAN_TXT: cian con contraste AA sobre blanco
FONDO, BORDE, GRIS = "#F2F6FB", "#D5DEEA", "#5B6B82"
COLOR = {"Cumple": "#2E9E5B", "No cumple": "#D64545", "Revisar": "#C98A00", "No aplica": "#7A8699"}
ORDEN = {"No cumple": 0, "Revisar": 1, "Cumple": 2, "No aplica": 3}

st.markdown(f"""
<style>
  .block-container {{ padding-top: 1.2rem; max-width: 1320px; }}
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
           font-style: italic; color: {MARINO}; white-space: pre-line; }}
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
  /* panel lateral: la ventana de detalle (st.dialog) se pega a la derecha y ocupa todo el alto */
  [data-testid="stDialog"] > div {{ position: fixed; top: 0; right: 0; bottom: 0; margin: 0;
      width: min(780px, 94vw); max-width: none; height: 100vh; animation: panel-in .25s ease-out; }}
  [data-testid="stDialog"] section[role="dialog"] {{ width: 100%; height: 100vh; max-height: 100vh; overflow-y: auto;
      border-radius: 14px 0 0 14px; margin: 0; }}
  @keyframes panel-in {{ from {{ transform: translateX(100%); }} to {{ transform: translateX(0); }} }}
  .pie {{ color: {GRIS}; font-size: .8rem; text-align: center; margin-top: 28px; border-top: 1px solid {BORDE}; padding-top: 10px; }}
</style>""", unsafe_allow_html=True)

# --------------------------------------------------------------------------- inicio de sesión
# Sin sesión iniciada se muestra la pantalla de login y la app se detiene aquí (src/auth.py).
# Para la demo sin login: AUTH_ACTIVADA=false en .env
USUARIO = auth.requerir_login(LANG)
auth.mostrar_sesion(USUARIO, LANG)

if not db.existe_tabla("hallazgos"):
    st.error(T["no_datos"])
    st.code("python datos_sinteticos/generar.py\npython -m src.pipeline")
    st.stop()


@st.cache_data(show_spinner=False)
def cargar():
    h = db.leer_df("SELECT * FROM hallazgos")
    for c in ["resaltar", "faltan", "violaciones", "vaguedad", "candidatas", "llm_votos", "detalle"]:
        if c in h:
            h[c] = h[c].apply(json.loads)
    if "tema_en" not in h:
        h["tema_en"] = h["tema"]
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
h = h.copy()
h["veredicto_ia"] = h["veredicto"]
h["veredicto"] = h.apply(lambda r: final.get(r.req_id, r.veredicto_ia), axis=1)
h["revisado"] = h.req_id.isin(revisado)
h["orden"] = h.veredicto.map(ORDEN)
h["tema_l"] = h.tema if LANG == "es" else h.tema_en
h["just_l"] = h.apply(lambda r: textos.justificacion(r.detalle, LANG) if isinstance(r.get("detalle"), dict) else r.justificacion, axis=1)
h = h.sort_values(["orden", "confianza", "req_id"])


def chip(v: str) -> str:
    return f"<span class='chip' style='background:{COLOR.get(v, '#999')}'>{V(v)}</span>"


def resaltar(texto: str, trozos: list[str]) -> str:
    t = html.escape(texto)
    for trozo in sorted({x for x in trozos if x}, key=len, reverse=True):
        t = re.sub(re.escape(html.escape(trozo)), lambda m: f"<mark>{m.group(0)}</mark>", t, flags=re.I)
    return t


def seccion(n: int, titulo: str):
    st.markdown(f"<div class='sec'><span class='n'>{n}</span>{titulo}</div>", unsafe_allow_html=True)


def ubic(u: str) -> str:
    """'párrafo 26' / 'página 3' / 'tabla 1, fila 4' → en inglés si toca."""
    if LANG == "es" or not isinstance(u, str):
        return u
    for a, b in [("párrafo", "paragraph"), ("página", "page"), ("tabla", "table"), ("fila", "row"), ("línea", "line")]:
        u = u.replace(a, b)
    return u


def num(x: float, dec: int = 2) -> str:
    s = f"{x:.{dec}f}"
    return s.replace(".", ",") if LANG == "es" else s


# --------------------------------------------------------------------------- cabecera
juez = T["juez_llm"] if llm.disponible() else T["juez_reglas"]
st.markdown(f"""
<div class="hero">
  <div class="eyebrow">{T['eyebrow']}</div>
  <h1>{T['titulo']}</h1>
  <div class="rule"></div>
  <div class="sub">{T['sub']}</div>
  <span class="pill">{T['pill_norma']}</span>
  <span class="pill">{len(h)} {T['requisitos']}</span>
  <span class="pill">{T['juez']}: {juez}</span>
  <span class="pill">{h.revisado.sum()}/{len(h)} {T['revisados']}</span>
</div>""", unsafe_allow_html=True)

c = h.veredicto.value_counts()
ev = metricas.get("evaluacion")

# --------------------------------------------------------------------------- menú lateral (sustituye a las pestañas)
ICONOS = {"metricas": ":material/monitoring:", "hallazgos": ":material/fact_check:",
          "consistencia": ":material/compare_arrows:", "cobertura": ":material/grid_on:", "agentes": ":material/hub:"}
st.markdown(f"""<style>
  [data-testid="stSidebar"] .menu-t {{ color: {GRIS}; font-size: .75rem; font-weight: 700; letter-spacing: .06em;
      text-transform: uppercase; margin: 18px 0 4px 4px; }}
  [data-testid="stSidebar"] [role="radiogroup"] {{ gap: 2px; }}
  [data-testid="stSidebar"] [role="radiogroup"] label {{ display: flex; width: 100%; padding: 8px 12px; border-radius: 8px; margin: 0; }}
  [data-testid="stSidebar"] [role="radiogroup"] label:hover {{ background: #EAF1F8; }}
  [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) {{ background: #E6F4FB; }}
  [data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p {{ color: {CIAN_TXT}; font-weight: 700; }}
  [data-testid="stSidebar"] [role="radiogroup"] label p {{ color: {MARINO}; font-weight: 600; font-size: .95rem; }}
</style>""", unsafe_allow_html=True)
with st.sidebar:
    st.markdown(f"<div class='menu-t'>{T['menu']}</div>", unsafe_allow_html=True)
    pagina = st.radio(T["menu"], list(T["nav"]), key="pagina", label_visibility="collapsed",
                      format_func=lambda k: f"{ICONOS[k]} {T['nav'][k]}")

if aviso := st.session_state.pop("aviso", None):
    st.toast(aviso, icon=":material/check_circle:")

st.write("")
# --------------------------------------------------------------------------- 1 · métricas
if pagina == "metricas":
    seccion(1, T["s0"])
    for col, v in zip(st.columns(4), ["Cumple", "No cumple", "Revisar", "No aplica"]):
        etiqueta = T["requiere_revision"] if v == "Revisar" else V(v)
        col.markdown(f"<div class='kpi'><span class='dot' style='background:{COLOR[v]}'></span>"
                     f"<span class='num' style='color:{COLOR[v]}'>{c.get(v, 0)}</span>"
                     f"<span class='lbl'>{etiqueta}</span></div>", unsafe_allow_html=True)

    st.write("")
    if ev:
        e, s = ev["deteccion_estricta"], ev["deteccion_senalados"]
        cobm = metricas["cobertura"]

        def met(col, titulo, valor, ref_txt, ok):
            marca = "" if ok is None else (f"<span class='ok'>{T['ok']}</span>" if ok else f"<span class='ko'>{T['ko']}</span>")
            col.markdown(f"<div class='met'><div class='t'>{titulo}</div><div class='v'>{valor}</div>"
                         f"<div class='ref'>{ref_txt} {marca}</div></div>", unsafe_allow_html=True)

        m1, m2, m3, m4 = st.columns(4)
        met(m1, T["m_f1"], num(e["f1"]), T["m_ref_f1"], e["f1"] >= 0.8)
        met(m2, T["m_f1s"], num(s["f1"]), T["m_f1s_ref"], None)
        met(m3, T["m_traz"], f"{ev['trazabilidad_pct']:.0%}", T["m_traz_ref"], ev["trazabilidad_pct"] >= 0.9)
        met(m4, T["m_cob"], f"{cobm['cubiertas']}/{cobm['total']}", T["m_cob_ref"], None)

    st.write("")


# --------------------------------------------------------------------------- panel lateral de detalle
def panel_detalle(rid: str):
    """Detalle de un requisito en un panel que entra por la derecha (st.dialog con estilo de cajón lateral)."""

    @st.dialog(f"{T['requisito']} {rid}", width="large")
    def _panel():
        r = h[h.req_id == rid].iloc[0]
        det = r.detalle if isinstance(r.get("detalle"), dict) else {}

        # --- requisito y veredicto
        ia = (f" · <small>{T['ia_proponia']} {V(r.veredicto_ia)}</small>" if r.veredicto != r.veredicto_ia else "")
        faltan = "".join(f"<span class='tag'>{html.escape(x[LANG])}</span>" for x in det.get("faltan", []))
        refl = textos.reflexion(det.get("reflexion"), LANG)
        nota_req = f"<p style='color:{GRIS};font-size:.8rem;margin:6px 0 0'>{T['nota_req']}</p>" if T["nota_req"] else ""
        juez_r = r.juez if LANG == "es" else r.juez.replace("reglas", "rules")
        st.markdown(f"""
<div class="card"><div class="hd">{T['requisito']} {r.req_id} <small>· {html.escape(r.seccion)} · {ubic(r.ubicacion)}</small></div>
<div class="bd">
  <div class="req" style="--c:{COLOR[r.veredicto]}">{resaltar(r.texto, r.resaltar)}</div>{nota_req}
  <div style="display:flex;align-items:center;gap:12px;margin:14px 0 4px">{chip(r.veredicto)}
    <span style="color:{GRIS};font-size:.88rem">{T['confianza']} {num(r.confianza)} · {T['juez_min']}: {juez_r}{ia}</span></div>
  <div class="bar"><div style="width:{r.confianza * 100:.0f}%"></div></div>
  <p style="margin:12px 0 6px"><b>{T['justificacion']}</b> {html.escape(r.just_l)}</p>
  {f"<p style='margin:6px 0'><b>{T['faltan']}</b><br>{faltan}</p>" if faltan else ""}
  {f"<div class='nota'>{T['reflexion']} · {html.escape(refl)}</div>" if refl else ""}
  {f"<div class='nota'>{T['autocons']}: {', '.join(r.llm_votos)}</div>" if r.llm_votos else ""}
</div></div>""", unsafe_allow_html=True)

        # --- regla de la norma que aplica
        if r.clausula:
            cl = clausulas().get(r.clausula)                                       # inglés (EASA)
            cl_es = normativa_es.cargar().get("clausulas", {}).get(r.clausula)     # español oficial (DOUE)
            texto_es = normativa_es.texto_obligacion(r.clausula, r.apartado)
            if LANG == "es" and texto_es:
                cita, origen = texto_es, T["fuente_es"]
                titulo = cl_es["titulo"] if cl_es else ""
            elif LANG == "es":
                cita, origen, titulo = r.texto_norma, T["fuente_en_fallback"], (cl["titulo"] if cl else "")
            else:
                cita, origen, titulo = r.texto_norma, T["fuente_en"], (cl["titulo"] if cl else "")
            st.markdown(f"""
<div class="card"><div class="hd">{T['regla_aplicable']} · {r.clausula} {r.apartado} <small>· {html.escape(r.tema_l)}</small></div>
<div class="bd">
  <div class="quote">{html.escape(cita)}</div>
  <p style="margin:10px 0 0;color:{GRIS};font-size:.85rem"><b>{html.escape(titulo)}</b><br>{T['fuente']}: {origen}</p>
</div></div>""", unsafe_allow_html=True)
            b1, b2 = st.columns(2)
            b1.link_button(T["btn_eurlex"], normativa_es.URL_EURLEX, width="stretch")
            b2.link_button(f"{r.clausula} {T['btn_easa']}", normativa.url_clausula(r.clausula), width="stretch")
            principal = cl_es["texto"] if (LANG == "es" and cl_es) else (cl["texto"] if cl else "")
            if principal:
                with st.expander(T["completo"].format(c=r.clausula)):
                    st.text(principal)
            with st.expander(T["otro_idioma"]):
                if LANG == "es":
                    st.markdown(f"*{r.texto_norma}*")
                    if cl:
                        st.caption(T["clausula_completa"])
                        st.text(cl["texto"])
                else:
                    if texto_es:
                        st.markdown(f"*{texto_es}*")
                    if cl_es:
                        st.caption(T["clausula_completa"])
                        st.text(cl_es["texto"])
                st.caption(T["nota_idioma"])
            with st.expander(T["rag"]):
                st.write(T["rag_txt"] + " · ".join(r.candidatas))
        else:
            st.markdown(f"""<div class="card"><div class="hd">{T['sin_regla_hd']}</div>
<div class="bd">{T['sin_regla_bd']}</div></div>""", unsafe_allow_html=True)

        # --- decisión del revisor (humano en el bucle)
        st.markdown(f"<div class='card'><div class='hd'>{T['decision']} <small>· {T['hitl']}</small></div></div>",
                    unsafe_allow_html=True)
        st.text_input(T["comentario"], key=f"c_{rid}", placeholder=T["comentario"], label_visibility="collapsed")
        d1, d2, d3 = st.columns(3)
        if d1.button(T["aprobar"], key=f"a_{rid}", type="primary", width="stretch"):
            db.registrar_decision(rid, "aprobado", r.veredicto_ia, st.session_state.get(f"c_{rid}", ""),
                                  usuario=USUARIO["nombre"], usuario_id=USUARIO["id"])
            st.session_state.aviso = T["guardado"].format(rid=rid, v=V(r.veredicto_ia))
            st.rerun()
        nuevo = d2.selectbox(T["veredicto_final"], list(ORDEN), index=list(ORDEN).index(r.veredicto), key=f"v_{rid}",
                             format_func=V, label_visibility="collapsed")
        if d3.button(T["guardar"], key=f"g_{rid}", width="stretch"):
            db.registrar_decision(rid, "corregido", nuevo, st.session_state.get(f"c_{rid}", ""),
                                  usuario=USUARIO["nombre"], usuario_id=USUARIO["id"])
            st.session_state.aviso = T["guardado"].format(rid=rid, v=V(nuevo))
            st.rerun()

    _panel()


# --------------------------------------------------------------------------- 2 · hallazgos
if pagina == "hallazgos":
    seccion(2, T["s1"])
    f1, f2, f3 = st.columns([2, 2, 1])
    estados = f1.multiselect(T["estado"], list(ORDEN), default=["No cumple", "Revisar", "Cumple"], format_func=V)
    reglas = f2.multiselect(T["regla"], sorted(x for x in h.clausula.unique() if x), placeholder=T["todas"])
    solo_pend = f3.toggle(T["pendientes"], value=False)
    vista = h[h.veredicto.isin(estados)]
    if reglas:
        vista = vista[vista.clausula.isin(reglas)]
    if solo_pend:
        vista = vista[~vista.revisado]

    tabla = pd.DataFrame({
        T["c_req"]: vista.req_id + " · " + vista.tema_l.replace("", "—"),
        T["c_regla"]: ("Part-IS · " + vista.clausula + " " + vista.apartado).where(vista.clausula != "", "—"),
        T["c_estado"]: vista.veredicto.map(V), T["c_conf"]: vista.confianza,
        T["c_rev"]: vista.revisado.map({True: "✓", False: ""}),
        T["c_just"]: vista.just_l.str.slice(0, 140),
    })
    st.caption(T["ayuda_tabla"])
    sel = st.dataframe(tabla, hide_index=True, width="stretch", on_select="rerun",
                       selection_mode="single-row", height=min(640, 38 + 35 * len(tabla)),
                       column_config={T["c_conf"]: st.column_config.ProgressColumn(min_value=0, max_value=1, format="%.2f"),
                                      T["c_rev"]: st.column_config.TextColumn(width="small")})

    # Al marcar una fila se abre su detalle en el panel lateral. Solo se abre cuando cambia la selección:
    # así, al cerrarlo o tras guardar una decisión, no vuelve a saltar solo.
    filas = sel.selection.rows if sel and sel.selection else []
    ids = list(vista.req_id)
    marcado = ids[filas[0]] if filas and filas[0] < len(ids) else None
    if marcado and st.session_state.get("panel_abierto") != marcado:
        st.session_state.panel_abierto = marcado
        panel_detalle(marcado)
    elif not marcado:
        st.session_state.panel_abierto = None

# --------------------------------------------------------------------------- 3 · consistencia
if pagina == "consistencia":
    seccion(3, T["s3"])
    abrir = None   # requisito a revisar en el panel lateral (solo se puede abrir un panel por ejecución)
    veredicto_de = dict(zip(h.req_id, h.veredicto))
    st.markdown(f"**{T['contradicciones']}**")
    if contra.empty:
        st.success(T["sin_contra"])
    for row in contra.itertuples():
        ta = h.loc[h.req_id == row.req_a, "texto"].iloc[0]
        tb = h.loc[h.req_id == row.req_b, "texto"].iloc[0]
        st.markdown(f"""
<div class="card"><div class="hd">{html.escape(textos.parametro(row.parametro, LANG).capitalize())}
 <small>· {html.escape(row.valor_a)} {T['frente']} {html.escape(row.valor_b)}</small></div>
<div class="bd">
  <p style="margin:0 0 10px;color:{GRIS}">{html.escape(textos.contradiccion(row, LANG))}</p>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">
    <div><b>{row.req_a}</b> {chip(veredicto_de.get(row.req_a, ""))}<br>{resaltar(ta, [row.valor_a])}</div>
    <div><b>{row.req_b}</b> {chip(veredicto_de.get(row.req_b, ""))}<br>{resaltar(tb, [row.valor_b])}</div>
  </div>
</div></div>""", unsafe_allow_html=True)
        # Llamada a la acción: revisar cada requisito de la contradicción en el panel lateral
        ba, bb = st.columns(2)
        for col, rid_c, lado in [(ba, row.req_a, "a"), (bb, row.req_b, "b")]:
            if col.button(T["revisar_req"].format(rid=rid_c), key=f"rev_{row.Index}_{lado}",
                          icon=":material/rate_review:", width="stretch"):
                abrir = rid_c
        st.write("")

    st.markdown(f"**{T['homo']}**")
    st.caption(T["homo_ayuda"] + " " + T["homo_cta"])
    if len(homo) and "escueto" in homo:
        motivos = [textos.homogeneidad(SimpleNamespace(**x), LANG) for x in homo.to_dict("records")]
    else:
        motivos = list(homo.get("motivo", []))
    sel_h = st.dataframe(pd.DataFrame({T["c_req"]: homo.req_id, T["c_estado"]: homo.req_id.map(veredicto_de).map(V),
                                       T["palabras"]: homo.palabras, T["motivo"]: motivos}),
                         hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                         column_config={T["motivo"]: st.column_config.TextColumn(width="large")})
    # Igual que en Hallazgos: el panel se abre solo cuando cambia la fila marcada
    filas_h = sel_h.selection.rows if sel_h and sel_h.selection else []
    marcado_h = homo.req_id.iloc[filas_h[0]] if filas_h and filas_h[0] < len(homo) else None
    if marcado_h and st.session_state.get("panel_homo") != marcado_h:
        st.session_state.panel_homo = marcado_h
        abrir = abrir or marcado_h
    elif not marcado_h:
        st.session_state.panel_homo = None

    if abrir:
        panel_detalle(abrir)

# --------------------------------------------------------------------------- 4 · cobertura
if pagina == "cobertura":
    seccion(4, T["s4"])
    st.caption(T["s4_ayuda"])
    titulos_es = {k: v["titulo"] for k, v in normativa_es.cargar().get("clausulas", {}).items()}
    titulos = cob.clausula.map(titulos_es).fillna(cob.titulo) if LANG == "es" else cob.titulo
    st.dataframe(pd.DataFrame({T["clausula"]: cob.clausula, T["titulo_col"]: titulos, T["requisitos_col"]: cob.requisitos,
                               T["cubierta"]: cob.cubierta.map({True: "✓", False: "✗", 1: "✓", 0: "✗"})}),
                 hide_index=True, width="stretch")
    st.caption(T["titulos_fuente"])
    st.write("")
    st.markdown(f"**{T['s2']}**")
    st.caption(T["s2_ayuda"])
    ap = h[h.clausula != ""].copy()
    columnas = list(cob.clausula) if len(cob) else sorted(ap.clausula.unique())
    filas_m = sorted(ap.req_id)
    z = pd.DataFrame(index=filas_m, columns=columnas, dtype=float)
    for row in ap.itertuples():
        z.loc[row.req_id, row.clausula] = {"Cumple": 1, "Revisar": 0, "No cumple": -1}.get(row.veredicto)
    texto = z.map(lambda x: {1: V("Cumple"), 0: V("Revisar"), -1: V("No cumple")}.get(x, ""))
    fig = go.Figure(go.Heatmap(
        z=z.values, x=[x.replace("IS.I.OR.", "OR.") for x in columnas], y=filas_m, text=texto.values,
        hovertemplate="%{y} · %{x}<br>%{text}<extra></extra>", zmin=-1, zmax=1, showscale=False, xgap=3, ygap=3,
        colorscale=[[0, COLOR["No cumple"]], [0.5, COLOR["Revisar"]], [1, COLOR["Cumple"]]]))
    fig.update_layout(height=60 + 20 * len(filas_m), margin=dict(l=0, r=0, t=30, b=0), plot_bgcolor=FONDO,
                      font=dict(color=MARINO), xaxis=dict(side="top"), yaxis=dict(autorange="reversed"))
    st.plotly_chart(fig, width="stretch")
    st.markdown(" ".join(chip(v) for v in ["Cumple", "Revisar", "No cumple"]), unsafe_allow_html=True)


# --------------------------------------------------------------------------- 5 · agentes
if pagina == "agentes":
    seccion(5, T["s5"])
    st.markdown("<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin-bottom:12px'>" +
                " <span style='color:#9AA8BC'>→</span> ".join(
                    f"<span style='background:{MARINO if i else CIAN};color:#fff;border-radius:8px;padding:6px 12px;"
                    f"font-weight:600;font-size:.88rem'>{p}</span>" for i, p in enumerate(T["pasos"])) + "</div>",
                unsafe_allow_html=True)
    for p in traza.itertuples():
        linea = textos.traza({"clave": p.clave, "datos": json.loads(p.datos)}, LANG) if "clave" in traza else p.paso
        st.markdown(f"<div class='nota' style='margin-bottom:6px'>{html.escape(linea)}</div>", unsafe_allow_html=True)
    if ev:
        st.markdown(f"**{T['eval']}**")
        filas = []
        for nombre, k in [(T["m_estricta"], "deteccion_estricta"), (T["m_senal"], "deteccion_senalados"),
                          (T["m_contra"], "contradicciones")]:
            if k in ev:
                filas.append({T["metrica"]: nombre, **{x: ev[k][x] for x in ["precision", "recall", "f1", "tp", "fp", "fn"]}})
        st.dataframe(pd.DataFrame(filas), hide_index=True, width="stretch")
        st.caption(T["traz_txt"].format(t=f"{ev['trazabilidad_pct']:.0%}", e=f"{ev['exactitud_veredicto']:.0%}"))

# --------------------------------------------------------------------------- informe HTML (ahora sin botón en la interfaz)
def informe_html() -> str:
    filas = "".join(
        f"<tr><td><b>{x.req_id}</b><br><small>{html.escape(x.tema_l or '')}</small></td>"
        f"<td>{x.clausula} {x.apartado}</td><td>{chip(x.veredicto)}{' ✓' if x.revisado else ''}</td>"
        f"<td>{resaltar(x.texto, x.resaltar)}</td><td>{html.escape(x.just_l)}</td></tr>"
        for x in h.itertuples())
    contr = "".join(f"<li><b>{html.escape(textos.parametro(x.parametro, LANG))}</b>: "
                    f"{html.escape(textos.contradiccion(x, LANG))}</li>" for x in contra.itertuples())
    kpis = "".join(f"<div class='k'><span style='color:{COLOR[k]}'>{c.get(k, 0)}</span> {V(k)}</div>" for k in ORDEN)
    return f"""<!doctype html><html lang="{LANG}"><head><meta charset="utf-8"><title>{T['inf_titulo']}</title>
<style>body{{font-family:Segoe UI,Arial,sans-serif;margin:0;color:#1B2333}} header{{background:{MARINO};color:#fff;padding:24px 32px}}
header .r{{width:110px;height:4px;background:{CIAN};margin:10px 0}} main{{padding:24px 32px}}
.ks{{display:flex;gap:12px;margin-bottom:20px}} .k{{background:{FONDO};border:1px solid {BORDE};border-radius:10px;padding:10px 16px;font-weight:600}}
.k span{{font-size:1.6em;font-weight:800}} table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid {BORDE};padding:8px;vertical-align:top;font-size:14px}} th{{background:{MARINO};color:#fff;text-align:left}}
.chip{{color:#fff;padding:2px 10px;border-radius:999px;font-size:12px;font-weight:700}} mark{{background:#FFD9D9}}</style></head><body>
<header><small style="color:{CIAN};font-weight:700">{T['inf_proto']}</small>
<h1 style="margin:4px 0 0">{T['inf_titulo']}</h1><div class="r"></div>
{T['generado']}: {datetime.now():%d/%m/%Y %H:%M} · {T['revisados']} {h.revisado.sum()}/{len(h)}</header>
<main><div class="ks">{kpis}</div>
<h2>{T['hallazgos']}</h2><table><tr><th>{T['c_req']}</th><th>{T['c_regla']}</th><th>{T['c_estado']}</th><th>{T['texto']}</th><th>{T['c_just']}</th></tr>{filas}</table>
<h2>{T['contradicciones']}</h2><ul>{contr or f"<li>{T['ninguna']}</li>"}</ul>
<p style="color:{GRIS};font-size:12px">{T['pie']}</p></main></body></html>"""

st.markdown(f"<div class='pie'>{T['pie']}</div>", unsafe_allow_html=True)
