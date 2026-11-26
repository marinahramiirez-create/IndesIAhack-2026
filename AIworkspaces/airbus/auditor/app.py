"""
Revisión de hallazgos · Reto Airbus (diseño del prototipo de Valentina, con los datos reales del auditor).
Se alimenta SOLO de los ficheros que genera auditar.py (respuestas.csv + traza): sin lógica de auditoría propia,
para que lo que ve el revisor y lo que se entrega no puedan discrepar.

    .venv\\Scripts\\python -m streamlit run app.py

Pantallas: Inicio (documentos) · Revisión (PDF con la cita resaltada + aprobar/rechazar) · Panel de control IA
(flujo de agentes con cifras reales + métricas del puntuador) · Histórico (hallazgos, asistente, exportar) ·
Configuración (reglas y criterio de aceptación, usuarios y roles).
La versión anterior de la app está en app_clasica.py.
"""
import csv
import html
import io
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
DECISIONES = SALIDAS / "decisiones_revisor.csv"     # Aprobado / Rechazado + comentario (feedback, no toca el CSV oficial)
OMITIDOS = SALIDAS / "omitidos_revisor.csv"         # lo que la IA no señaló (comentario sin hallazgo)
EASA_URL = "https://www.easa.europa.eu/en/document-library/easy-access-rules/easy-access-rules-information-security-part"
TIPOS = ["No cumple", "Inconsistencia", "Cobertura faltante", "Trazabilidad incorrecta", "No verificable"]
PATRON_ID = re.compile(r"\b[A-Z][A-Z0-9]{1,6}(?:-[A-Z0-9]{1,8}){0,3}-\d{2,4}\b|\b[A-Z]-\d{2,4}\b|\bu\d{3,5}\b")

st.set_page_config(page_title="Revisión de hallazgos · Airbus", page_icon="🛡️", layout="wide")

# ------------------------------------------------------------------ estilo (paleta del prototipo)
st.markdown("""<style>
:root{--bg:#f2f2f7;--card:#fff;--text:#1c1c1e;--sec:#6e6e73;--sep:#d1d1d6;--tint:#0a84ff;--ok:#34c759;--warn:#ff9f0a;--err:#ff3b30}
html,body,[class*="css"],.stApp{font-family:-apple-system,BlinkMacSystemFont,"Inter","Segoe UI",system-ui,sans-serif}
.stApp{background:var(--bg)}
header[data-testid="stHeader"]{background:transparent}
.block-container{padding-top:2.6rem;max-width:1500px}
div[data-testid="stVerticalBlockBorderWrapper"]:has(> div > div > .tarjeta),
.st-key-card_izq,.st-key-card_der,.st-key-card,[class*="st-key-card"]{background:#fff;border-radius:14px;padding:18px;
  box-shadow:0 1px 2px rgba(0,0,0,.04);border:0}
.topbar{display:flex;align-items:center;gap:14px;background:rgba(255,255,255,.92);border:1px solid var(--sep);
  border-radius:14px;padding:10px 20px;margin-bottom:16px}
.topbar .t{font-weight:600;font-size:17px}.topbar .sp{flex:1}
.topbar .marca{font-weight:700;letter-spacing:.12em;font-size:13px;color:var(--sec)}
h2.v{font-size:22px;margin:0 0 2px;padding:0}.sub{color:var(--sec);margin:0 0 14px}
.small{font-size:13px;color:var(--sec)}
.note{font-size:12px;color:var(--sec);background:#f7f7fa;border-radius:10px;padding:10px;margin-top:12px}
.st{display:inline-flex;align-items:center;gap:7px;font-size:13px;font-weight:600;color:var(--text);white-space:nowrap}
.st i{width:8px;height:8px;border-radius:50%;background:var(--c);display:inline-block}
.motivo{padding:14px 16px;background:#fafafc;border:1px solid var(--sep);border-radius:14px;margin:6px 0}
.rule{background:#f7f7fa;border-radius:10px;padding:12px;font-size:14px;margin:8px 0 0}
.ev{border-left:4px solid var(--warn);background:#fff8ec;padding:8px 12px;border-radius:0 10px 10px 0;font-size:14px;margin-top:6px}
.barra{flex:1;height:8px;background:#e5e5ea;border-radius:999px;overflow:hidden}
.barra div{height:100%;background:var(--ok)}
.kpi{background:var(--bg);border-radius:10px;padding:10px 12px}.kpi b{font-size:20px;display:block}
.user{padding:14px;border-radius:12px;background:var(--bg);margin-bottom:8px}
.user b{display:block;font-size:16px}.user span{color:var(--sec);font-size:13px}
.m{padding:10px 13px;border-radius:14px;max-width:88%;font-size:14px;margin:6px 0}
.m.u{margin-left:auto;background:var(--tint);color:#fff}.m.a{background:var(--bg)}
mark{background:#ffe27a;padding:0 2px;border-radius:3px}
/* menú lateral tipo cajón */
section[data-testid="stSidebar"]{background:#fff}
section[data-testid="stSidebar"] .stButton button{justify-content:flex-start;border:0;background:none;color:var(--text);
  font-size:15px;padding:8px 12px;border-radius:10px}
section[data-testid="stSidebar"] .stButton button:hover{background:#f0f0f5;color:var(--text)}
section[data-testid="stSidebar"] .stButton button[kind="primary"]{background:#e5f1ff;color:var(--tint);font-weight:600}
[class*="st-key-navsub_"] button{padding-left:30px!important;font-size:14px!important}
.st-key-logout button{background:#e5e5ea!important;justify-content:center!important}
/* botones de decisión */
.st-key-aprobar button{background:var(--ok);color:#fff;border:0}
.st-key-rechazar button{background:var(--warn);color:#fff;border:0}
.st-key-aprobar button:hover,.st-key-rechazar button:hover{opacity:.9;color:#fff}
[class*="st-key-foco_"] button{border:0;background:none;font-weight:600;justify-content:flex-start;padding:2px 4px}
[class*="st-key-focoon_"] button{border:0;background:#e5f1ff;font-weight:600;justify-content:flex-start;padding:2px 4px;color:var(--tint)}
.st-key-login{background:#fff;border-radius:20px;padding:36px;box-shadow:0 8px 30px rgba(0,0,0,.08);max-width:420px;margin:8vh auto 0}
</style>""", unsafe_allow_html=True)


def estado_html(tipo_o_estado: str, etiqueta: str | None = None) -> str:
    col = {"ok": "var(--ok)", "fail": "var(--err)", "doubt": "var(--warn)", "neutral": "var(--sec)"}
    k = {"No verificable": "doubt", "Aprobado": "ok", "Rechazado": "neutral", "Completado": "ok", "Sin hallazgos": "ok",
         "En revisión": "doubt", "Pendiente": "neutral"}.get(tipo_o_estado, "fail")
    return f"<span class='st' style='--c:{col[k]}'><i></i>{html.escape(etiqueta or tipo_o_estado)}</span>"


# ------------------------------------------------------------------ datos
@st.cache_data
def cargar(ruta_csv: str, _mtime: float):
    df = pd.read_csv(ruta_csv, dtype=str).fillna("")
    df["confianza"] = pd.to_numeric(df.get("confianza", 0), errors="coerce").fillna(0)
    traza_f = Path(ruta_csv).with_name(Path(ruta_csv).stem + "_traza.jsonl")
    traza = [json.loads(l) for l in open(traza_f, encoding="utf-8")] if traza_f.exists() else []
    return df, pd.DataFrame(traza)


@st.cache_data
def indice_corpus():
    """código → ruta, familia, título, texto por páginas, unidades (ID → texto, página). Usa la caché de transcripciones."""
    from src import ingesta
    idx = {}
    for f in sorted(CORPUS.rglob("*.pdf")):
        try:
            d = ingesta.leer(f, vision=True)
        except Exception:
            continue
        if d.codigo:
            idx[d.codigo] = {"ruta": str(f), "familia": f.parent.name, "titulo": d.titulo, "version": d.version,
                             "paginas": d.paginas, "escaneado": d.escaneado, "figuras": len(d.figuras),
                             "tablas": len(d.tablas), "unidades": {u.id: (u.texto, u.pagina) for u in d.unidades}}
    return idx


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[|«»\"“”]", " ", str(t).lower())).strip()


def pagina_hallazgo(r, info) -> int:
    if str(r.get("pagina", "")).strip().isdigit():
        return int(float(r["pagina"]))
    ev = norm(r.get("evidencia", ""))[:60]
    if ev:
        for i, p in enumerate(info["paginas"], 1):
            if ev in norm(p):
                return i
    for i in PATRON_ID.findall(r.get("ubicacion", "")):
        if i in info["unidades"]:
            return info["unidades"][i][1]
    return 1


def fragmentos(evidencia: str) -> list[str]:
    """La cita se busca entera y, si no aparece así (saltos de línea, celdas de tabla), por trozos de 6 palabras."""
    partes = [p.strip(" .«»\"“”") for p in re.split(r"\s*\|\s*|\n", evidencia) if len(p.strip()) >= 6]
    out = []
    for p in partes:
        w = p.split()
        out += [p] if len(w) <= 8 else [" ".join(w[i:i + 6]) for i in range(0, len(w), 6) if len(w[i:i + 6]) >= 3]
    return out


@st.cache_data(max_entries=80)
def png_resaltada(ruta: str, n: int, evidencia: str, ids: tuple) -> tuple[bytes, int]:
    """Página del PDF con la cita resaltada en naranja y el identificador del hallazgo enmarcado."""
    doc = pymupdf.open(ruta)
    pag = doc[n - 1]
    hits = 0
    for frag in fragmentos(evidencia):
        for q in pag.search_for(frag, quads=True):
            a = pag.add_highlight_annot(q)
            a.set_colors(stroke=(1, .62, .04))
            a.update()
            hits += 1
    for i in ids:
        for rect in pag.search_for(i):
            a = pag.add_rect_annot(rect + (-2, -2, 2, 2))
            a.set_colors(stroke=(1, .62, .04))
            a.set_border(width=1.6)
            a.update()
    return pag.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6), annots=True).tobytes("png"), hits


def leer_csv(ruta: Path) -> list[dict]:
    return list(csv.DictReader(open(ruta, encoding="utf-8"))) if ruta.exists() else []


def anadir_csv(ruta: Path, fila: dict):
    nuevo = not ruta.exists()
    with open(ruta, "a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(fila))
        if nuevo:
            w.writeheader()
        w.writerow(fila)


def decisiones() -> dict:
    """(documento, ubicación) → última decisión del revisor."""
    return {(r["documento"], r["ubicacion"]): r for r in leer_csv(DECISIONES)}


def metricas_puntuador(nombre: str) -> dict:
    p = SALIDAS / nombre
    if not p.exists():
        return {}
    t = p.read_text(encoding="utf-8")
    m = {}
    for k, pat in (("precision", r"Precisión ([\d.]+)"), ("recall", r"Recall ([\d.]+)"), ("f1", r"F1 ([\d.]+)")):
        x = re.search(pat, t)
        if x:
            m[k] = float(x.group(1))
    x = re.search(r"cláusula correcta en aciertos: (\d+)/(\d+)", t)
    if x:
        m["clausula"] = int(x.group(1)) / int(x.group(2))
    x = re.search(r"aciertos: (\d+) \| defectos en la clave: (\d+)", t)
    if x:
        m["aciertos"], m["defectos"] = int(x.group(1)), int(x.group(2))
    fam = re.search(r"Recall por familia: (.+)", t)
    m["familias"] = re.findall(r"(\S+) (\d+)/(\d+)", fam.group(1)) if fam else []
    m["texto"] = t
    return m


# ------------------------------------------------------------------ sesión
S = st.session_state
S.setdefault("user", None)
S.setdefault("vista", "inicio")
S.setdefault("doc", None)
S.setdefault("foco", {})
S.setdefault("pag", 1)
S.setdefault("agente", None)
S.setdefault("hl", [])
S.setdefault("msgs", [{"r": "a", "t": "Busco en los hallazgos cargados. Prueba con «cifrado», «MFA», «IS.I.OR.230» o "
                                      "«no verificable»."}])
S.setdefault("umbral", 80)

# ------------------------------------------------------------------ login (prototipo)
if not S.user:
    with st.container(key="login"):
        st.markdown("<h2 class='v'>Revisión de hallazgos</h2><p class='sub'>Prototipo · Reto Airbus</p>",
                    unsafe_allow_html=True)
        with st.form("f_login", border=False):
            correo = st.text_input("Correo corporativo", placeholder="nombre@airbus.example")
            st.text_input("Contraseña", type="password")
            if st.form_submit_button("Entrar", type="primary", width="stretch"):
                nombre = (correo.split("@")[0] or "revisor").replace(".", " ").title()
                S.user = {"nombre": nombre, "correo": correo or "revisor", "cargo": "Auditor · Calidad Part-IS"}
                st.rerun()
        st.caption("Modo prototipo: entra con cualquier correo y contraseña.")
    st.stop()

# ------------------------------------------------------------------ carga
csvs = sorted(SALIDAS.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
csvs = [c for c in csvs if not c.name.startswith(("clave", "decisiones", "omitidos"))]
if not csvs:
    st.error("No hay resultados. Ejecuta primero: .venv\\Scripts\\python auditar.py <carpeta_pdf> --salida salidas\\respuestas.csv")
    st.stop()
pref = next((c for c in csvs if c.name == "respuestas.csv"), csvs[0])
S.setdefault("csv", str(pref))
ruta_csv = Path(S.csv) if Path(S.csv).exists() else pref
df, traza = cargar(str(ruta_csv), ruta_csv.stat().st_mtime)
idx = indice_corpus()
DEC = decisiones()
df["decision"] = [DEC.get((r.documento, r.ubicacion), {}).get("decision", "") for r in df.itertuples()]


def ir(vista: str, **kw):
    S.vista = vista
    for k, v in kw.items():
        S[k] = v


# ------------------------------------------------------------------ menú lateral (cajón)
with st.sidebar:
    st.markdown(f"<div class='user'><b>{html.escape(S.user['nombre'])}</b><span>{html.escape(S.user['cargo'])}</span></div>",
                unsafe_allow_html=True)
    for clave, txt, sub in (("inicio", "Inicio", False), ("ia", "Panel de control IA", False),
                            ("historico", "Histórico", False), ("reglas", "Configuración", False),
                            ("reglas", "Reglas", True), ("usuarios", "Usuarios y roles", True)):
        activo = S.vista == clave or (clave == "inicio" and S.vista == "revision" and not sub)
        st.button(txt, key=("navsub_" if sub else "nav_") + txt, width="stretch",
                  type="primary" if activo and not (txt == "Configuración") else "secondary",
                  on_click=ir, args=(clave,))
    st.write("")
    with st.expander("Resultados cargados", expanded=False):
        elegido = st.selectbox("Fichero", csvs, index=csvs.index(ruta_csv) if ruta_csv in csvs else 0,
                               format_func=lambda p: p.name, label_visibility="collapsed")
        if str(elegido) != S.csv:
            S.csv = str(elegido)
            st.rerun()
    if st.button("Cerrar sesión", key="logout", width="stretch"):
        S.user = None
        S.vista = "inicio"
        st.rerun()

TITULOS = {"inicio": "Inicio", "revision": "Revisión", "ia": "Panel de control IA", "historico": "Histórico",
           "reglas": "Configuración · Reglas", "usuarios": "Configuración · Usuarios y roles"}
st.markdown(f"<div class='topbar'><span class='t'>{TITULOS[S.vista]}</span><span class='sp'></span>"
            f"<span class='marca'>AIRBUS</span></div>", unsafe_allow_html=True)


def resumen_docs() -> pd.DataFrame:
    filas = []
    for cod, info in idx.items():
        hs = df[df.documento == cod]
        pend = int((hs.decision == "").sum())
        if not len(hs):
            est = "Sin hallazgos"
        elif pend == 0:
            est = "Completado"
        elif pend == len(hs):
            est = "Pendiente"
        else:
            est = "En revisión"
        filas.append({"Documento": cod, "Título": info["titulo"], "Familia": re.sub(r"^\d+_", "", info["familia"]).replace("_", " "),
                      "Hallazgos": len(hs), "Por revisar": pend, "Estado": est})
    return pd.DataFrame(filas)


# ================================================================== INICIO
def v_inicio():
    st.markdown("<h2 class='v'>Inicio</h2><p class='sub'>Documentos auditados. Pulsa una fila para revisar sus hallazgos "
                "junto al PDF.</p>", unsafe_allow_html=True)
    docs = resumen_docs()
    c = st.columns([3, 1.3, 1.3, 1.4])
    q = c[0].text_input("Buscar", placeholder="Buscar documento, título o familia", label_visibility="collapsed")
    fam = c[1].selectbox("Familia", ["Todas las familias"] + sorted(docs.Familia.unique()), label_visibility="collapsed")
    est = c[2].selectbox("Estado", ["Todos los estados", "Pendiente", "En revisión", "Completado", "Sin hallazgos"],
                         label_visibility="collapsed")
    subida = c[3].file_uploader("Cargar archivo", type=["pdf"], label_visibility="collapsed")
    if subida:
        st.info(f"«{subida.name}» registrado. Para auditarlo, cópialo a la carpeta del corpus y ejecuta auditar.py.")
    vis = docs
    if q:
        vis = vis[(vis.Documento + " " + vis["Título"] + " " + vis.Familia).str.lower().str.contains(q.lower(), regex=False)]
    if not fam.startswith("Todas"):
        vis = vis[vis.Familia == fam]
    if not est.startswith("Todos"):
        vis = vis[vis.Estado == est]
    vis = vis.sort_values(["Por revisar", "Hallazgos"], ascending=False).reset_index(drop=True)

    k = st.columns(4)
    for col, (val, t) in zip(k, ((len(docs), "documentos auditados"), (int(docs.Hallazgos.sum()), "hallazgos"),
                                 (int(docs["Por revisar"].sum()), "por revisar"),
                                 (int((docs.Estado == "Completado").sum()), "documentos completados"))):
        col.markdown(f"<div class='kpi' style='background:#fff'><span class='small'>{t}</span><b>{val}</b></div>",
                     unsafe_allow_html=True)
    st.write("")
    st.caption(f"{len(vis)} de {len(docs)} documentos")
    sel = st.dataframe(vis, hide_index=True, width="stretch", height=520, on_select="rerun",
                       selection_mode="single-row",
                       column_config={"Hallazgos": st.column_config.NumberColumn(width="small"),
                                      "Por revisar": st.column_config.ProgressColumn(
                                          min_value=0, max_value=int(max(docs.Hallazgos.max(), 1)), format="%d")})
    if sel and sel.selection and sel.selection.rows:
        fila = vis.iloc[sel.selection.rows[0]]
        if fila.Hallazgos:
            abrir(fila.Documento)
            st.rerun()
        else:
            st.success(f"{fila.Documento} no tiene hallazgos: el auditor lo da por conforme.")
    st.markdown("<p class='note'>Al cargar un archivo, el prototipo solo lo registra. La auditoría la hace auditar.py "
                "(una sola orden: carpeta de PDF → respuestas.csv).</p>", unsafe_allow_html=True)


def abrir(cod: str):
    hs = df[df.documento == cod].reset_index(drop=True)
    pend = [i for i, r in hs.iterrows() if not r.decision]
    i = pend[0] if pend else 0
    S.doc = cod
    S.foco[cod] = i
    S.pag = pagina_hallazgo(hs.iloc[i], idx[cod]) if cod in idx and len(hs) else 1
    S.vista = "revision"


# ================================================================== REVISIÓN
@st.dialog("Criterios de validación", width="large")
def dlg_criterios(hs: pd.DataFrame):
    st.markdown("<p class='sub'>Contra qué se valida cada documento. Cuando dos fuentes discrepan, manda la de mayor "
                "rango.</p>", unsafe_allow_html=True)
    st.markdown(TABLA_JERARQUIA, unsafe_allow_html=True)
    st.markdown("#### Hallazgos contrastados")
    for _, r in hs.iterrows():
        st.markdown(tarjeta_motivo(r), unsafe_allow_html=True)


@st.dialog("Comentario sin hallazgo")
def dlg_omitido(cod: str):
    st.markdown("<p class='small'>Algo que la IA no señaló. Se guarda como retroalimentación (omitidos_revisor.csv) "
                "para mejorar el auditor; no altera respuestas.csv.</p>", unsafe_allow_html=True)
    ref = st.text_input("Referencia (ubicación o texto del documento)")
    txt = st.text_area("Qué debería haber señalado la IA", height=120)
    c1, c2 = st.columns(2)
    if c1.button("Cancelar", width="stretch"):
        st.rerun()
    if c2.button("Guardar comentario", type="primary", width="stretch", disabled=not txt.strip()):
        anadir_csv(OMITIDOS, {"documento": cod, "referencia": ref.strip(), "comentario": txt.strip(),
                              "usuario": S.user["correo"], "fecha_hora": datetime.now().isoformat(timespec="seconds")})
        st.rerun()


def tarjeta_motivo(r) -> str:
    d = DEC.get((r.documento, r.ubicacion))
    dec = (f"<div class='small' style='margin-top:8px'>Tu decisión: <b style='color:var(--text)'>{d['decision']}</b>"
           + (f" · {html.escape(d['comentario'])}" if d.get("comentario") else "") + "</div>") if d else ""
    fuente = r.get("fuente", "") or (traza_de(r).get("fuente", "") if len(traza) else "")
    contr = f"<a href='{EASA_URL}' target='_blank'>Part-IS de EASA · {html.escape(r.clausula)}</a>" if r.clausula != "—" else "—"
    if fuente:
        contr += f" · {html.escape(fuente)}"
    ev = f"<div class='ev'>«{html.escape(r.evidencia)}»</div>" if r.evidencia else \
        "<div class='small'>Sin cita literal (hallazgo por ausencia).</div>"
    return (f"<div class='motivo'><div class='small'>{html.escape(r.ubicacion)} · origen {html.escape(r.origen)} · "
            f"confianza {r.confianza:.2f}</div><div style='margin-top:6px'>{estado_html(r.tipo)}</div>"
            f"<div class='small' style='margin-top:4px'>Cláusula {html.escape(r.clausula)}</div>"
            f"<div class='small' style='margin-top:8px'><b style='color:var(--text)'>Documento revisado:</b> "
            f"{html.escape(r.documento)}</div><div class='small'><b style='color:var(--text)'>Leído del documento:</b></div>"
            f"{ev}<div class='small' style='margin-top:6px'><b style='color:var(--text)'>Contrastado con:</b> {contr}</div>"
            f"<div class='rule'><b>Por qué:</b> {html.escape(r.justificacion)}</div>{dec}</div>")


def traza_de(r) -> dict:
    t = traza[(traza.documento == r.documento) & (traza.ubicacion == r.ubicacion) & (traza.aceptado)]
    return t.iloc[0].to_dict() if len(t) else {}


def decidir(cod: str, decision: str, objetivos: list[str], siguiente: int | None, pag: int | None):
    com = S.get("comentario", "").strip()
    ahora = datetime.now().isoformat(timespec="seconds")
    for u in objetivos:
        anadir_csv(DECISIONES, {"documento": cod, "ubicacion": u, "decision": decision, "comentario": com,
                                "usuario": S.user["correo"], "fecha_hora": ahora})
    for k in [k for k in S.keys() if str(k).startswith(f"sel|{cod}|")]:
        S[k] = False
    S["sel_todos"] = False
    S.comentario = ""
    if siguiente is not None:
        S.foco[cod] = siguiente
        S.pag = pag


def marcar_todos(cod: str, pendientes: list[str]):
    for u in pendientes:
        S[f"sel|{cod}|{u}"] = S.sel_todos


def enfocar(cod: str, i: int, pag: int):
    S.foco[cod] = i
    S.pag = pag


def v_revision():
    cod = S.doc
    if not cod or cod not in idx:
        ir("inicio")
        st.rerun()
    info = idx[cod]
    hs = df[df.documento == cod].reset_index(drop=True)
    n_pag = len(info["paginas"]) or 1
    foco = min(S.foco.get(cod, 0), max(len(hs) - 1, 0))

    c = st.columns([0.9, 5, 1.1, 1])
    c[0].button("← Listado", on_click=ir, args=("inicio",), width="stretch")
    c[1].markdown(f"<h2 class='v'>{cod} <span class='small' style='font-weight:400'>v{info['version']} · "
                  f"{html.escape(info['titulo'])}</span></h2>", unsafe_allow_html=True)
    if c[2].button("💬 Sin hallazgo", help="Comentario sin hallazgo de la IA", width="stretch"):
        dlg_omitido(cod)
    if c[3].button("Criterios", width="stretch"):
        dlg_criterios(hs)

    izq, der = st.columns([1.55, 1], gap="medium")
    hecho = int((hs.decision != "").sum())
    with izq, st.container(key="card_izq"):
        st.markdown(f"<div style='display:flex;align-items:center;gap:12px;margin-bottom:10px'>"
                    f"<span class='small'>Hallazgos revisados</span><div class='barra'><div style='width:"
                    f"{hecho / max(len(hs), 1) * 100:.0f}%'></div></div><b>{hecho}/{len(hs)}</b></div>",
                    unsafe_allow_html=True)
        p = st.columns([1, 2, 1])
        S.pag = max(1, min(S.pag, n_pag))
        p[0].button("← Anterior", disabled=S.pag <= 1, width="stretch", on_click=lambda: S.update(pag=S.pag - 1))
        p[1].markdown(f"<div class='small' style='text-align:center;padding-top:8px'>Página {S.pag} de {n_pag}</div>",
                      unsafe_allow_html=True)
        p[2].button("Siguiente →", disabled=S.pag >= n_pag, width="stretch", on_click=lambda: S.update(pag=S.pag + 1))
        r = hs.iloc[foco] if len(hs) else None
        ev = r.evidencia if r is not None and pagina_hallazgo(r, info) == S.pag else ""
        ids = tuple(PATRON_ID.findall(r.ubicacion)) if r is not None else ()
        png, hits = png_resaltada(info["ruta"], S.pag, ev, ids)
        st.image(png, width="stretch")
        if info["escaneado"]:
            st.caption("Documento escaneado: el texto se transcribió con visión, por eso la cita no se puede resaltar "
                       "sobre la imagen.")
        elif ev and not hits:
            st.caption("La cita no se ha podido localizar exactamente en esta página (texto partido en celdas).")
        omit = [o for o in leer_csv(OMITIDOS) if o["documento"] == cod]
        if omit:
            st.markdown(f"<div class='small' style='margin-top:10px'>Comentarios sin hallazgo guardados: {len(omit)}</div>"
                        + "".join(f"<div class='small'>· <b>{html.escape(o['referencia'] or 'Sin referencia')}</b> "
                                  f"{html.escape(o['comentario'])}</div>" for o in omit), unsafe_allow_html=True)

    with der, st.container(key="card_der"):
        pendientes = [x.ubicacion for x in hs.itertuples() if not x.decision]
        if not pendientes:
            st.markdown("<h2 class='v'>Revisión completa</h2><p class='sub'>Todos los hallazgos tienen decisión.</p>",
                        unsafe_allow_html=True)
            with st.container(height=520, border=False):
                for _, x in hs.iterrows():
                    st.markdown(tarjeta_motivo(x), unsafe_allow_html=True)
            st.button("Volver al listado", type="primary", width="stretch", on_click=ir, args=("inicio",))
            return
        st.checkbox("Seleccionar todos", key="sel_todos", on_change=marcar_todos, args=(cod, pendientes))
        with st.container(height=220, border=False):
            for i, x in hs.iterrows():
                a, b, e = st.columns([0.12, 1, 0.9], vertical_alignment="center")
                a.checkbox(" ", key=f"sel|{cod}|{x.ubicacion}", disabled=bool(x.decision), label_visibility="collapsed")
                b.button(x.ubicacion, key=f"{'focoon' if i == foco else 'foco'}_{i}", width="stretch",
                         on_click=enfocar, args=(cod, i, pagina_hallazgo(x, info)))
                e.markdown(estado_html(x.decision) if x.decision else estado_html(x.tipo), unsafe_allow_html=True)
        with st.container(height=330, border=False):
            st.markdown(tarjeta_motivo(r), unsafe_allow_html=True)
        st.text_area("Comentario", key="comentario", placeholder="Explica tu criterio", height=68)
        sel = [u for u in pendientes if S.get(f"sel|{cod}|{u}")]
        objetivos = sel or ([r.ubicacion] if not r.decision else [])
        # siguiente pendiente después del foco (o el primero)
        resto = [i for i, x in hs.iterrows() if not x.decision and x.ubicacion not in objetivos]
        sig = next((i for i in resto if i > foco), resto[0] if resto else None)
        pag_sig = pagina_hallazgo(hs.iloc[sig], info) if sig is not None else None
        st.caption(f"Se aplicará a: {', '.join(objetivos) if objetivos else '— (ya decidido)'}")
        b1, b2 = st.columns(2)
        b1.button("Aprobar", key="aprobar", width="stretch", disabled=not objetivos,
                  on_click=decidir, args=(cod, "Aprobado", objetivos, sig, pag_sig))
        b2.button("Rechazar", key="rechazar", width="stretch", disabled=not objetivos,
                  on_click=decidir, args=(cod, "Rechazado", objetivos, sig, pag_sig))


# ================================================================== PANEL IA
def v_ia():
    t = traza
    n_docs, n_pag = len(idx), sum(len(i["paginas"]) for i in idx.values())
    esc = sum(i["escaneado"] for i in idx.values())
    figs = sum(i["figuras"] for i in idx.values())
    acept = int(t.aceptado.sum()) if len(t) else 0
    desc = int((~t.aceptado).sum()) if len(t) else 0
    orig = t.origen.astype(str).str.replace(r"^R\d+$", "regla", regex=True).value_counts() if len(t) else pd.Series(dtype=int)
    motivos = t[~t.aceptado].descarte.str.extract(r"^(V\d)")[0].value_counts() if desc else pd.Series(dtype=int)
    ref = [c for c in idx if c.startswith(("STD-SEC-001", "LISTA-DOC"))]
    etapas = [
        ("Lectura del PDF", "Convierte cada documento en texto por página, unidades con ID, tablas y figuras. Los "
         "escaneados se transcriben con visión.",
         [("Documentos", n_docs), ("Páginas", n_pag), ("Escaneados", esc), ("Figuras", figs)],
         ["Extraer el texto de cada página (pymupdf)", "Detectar portada, código y versión",
          "Localizar requisitos, filas de registro y riesgos por su ID", "Transcribir con visión los PDF escaneados"]),
        ("Índice normativo", "Part-IS (IS.I.OR.200 a 260), STD-SEC-001 vigente y LISTA-DOC, una sola vez.",
         [("Cláusulas Part-IS", 13), ("Docs de referencia", len(ref))],
         ["Cargar el texto oficial de Part-IS", "Elegir la versión VIGENTE de STD-SEC-001 según LISTA-DOC",
          "Relacionar cada documento con los que cita"]),
        ("Agente de documentos", "Reglas deterministas + agente LLM (texto) + visión en las páginas con figuras.",
         [("Propuestas", len(t))] + [(k, int(v)) for k, v in orig.items()],
         ["Comparar cada requisito o fila con la norma y el estándar", "Copiar la cita literal que lo demuestra",
          "Dar las fechas de los plazos (el código hace la cuenta)", "Comparar diagramas con el texto"]),
        ("Verificación por código", "Cada propuesta se comprueba: formato, ubicación existente, cita literal, plazo "
         "recalculado y confianza.",
         [("Aceptadas", acept), ("Descartadas", desc)] + [(k, int(v)) for k, v in motivos.items()],
         ["V1 formato oficial de tipo y cláusula", "V2 la ubicación existe en el documento",
          "V3 la cita aparece literalmente", "V4 el plazo calculado incumple de verdad", "V5 umbral de confianza"]),
        ("Generación de respuestas.csv", "Deduplica y escribe las filas en el formato del reto, sin intervención "
         "manual.",
         [("Filas", len(df)), ("Documentos", df.documento.nunique()),
          ("Con cláusula", f"{(df.clausula != '—').mean() * 100:.0f} %" if len(df) else "—")],
         ["Quitar duplicados (mismo documento + mismo ID)", "Ordenar por documento y ubicación",
          "Escribir respuestas.csv y la traza"]),
    ]
    st.markdown("<h2 class='v'>Panel de control IA</h2><p class='sub'>Flujo de agentes de la solución con las cifras "
                f"de la última ejecución ({ruta_csv.name}). Pulsa un agente para ver qué hace.</p>",
                unsafe_allow_html=True)
    with st.container(key="card_flujo"):
        cols = st.columns(len(etapas))
        for i, (col, (nom, _, met, _)) in enumerate(zip(cols, etapas)):
            with col:
                st.button(f"Agente {i + 1}\n\n**{nom}**", key=f"ag_{i}", width="stretch",
                          type="primary" if S.agente == i else "secondary",
                          on_click=lambda i=i: S.update(agente=None if S.agente == i else i))
                st.markdown(f"<div class='small' style='text-align:center'>{estado_html('Completado')} "
                            f"· {met[0][1]} {met[0][0].lower()}</div>", unsafe_allow_html=True)
    if S.agente is not None:
        nom, d, met, act = etapas[S.agente]
        with st.container(key="card_agente"):
            st.markdown(f"### Agente {S.agente + 1} · {nom}\n<p class='small'>{d}</p>", unsafe_allow_html=True)
            k = st.columns(len(met))
            for c, (a, b) in zip(k, met):
                c.markdown(f"<div class='kpi'><span class='small'>{a}</span><b>{b}</b></div>", unsafe_allow_html=True)
            st.markdown("**Actividades**\n" + "\n".join(f"- {a}" for a in act))

    m = metricas_puntuador("metricas_sin_nucleo.txt")
    if m:
        with st.container(key="card_metricas"):
            st.markdown("### Resultado frente a la clave (puntuador oficial)\n<p class='small'>Documentos con clave del kit "
                        "de desarrollo, sin los 5 del núcleo, como en la evaluación final.</p>", unsafe_allow_html=True)
            k = st.columns(5)
            for c, (a, b) in zip(k, (("F1", f"{m.get('f1', 0):.3f}"), ("Precisión", f"{m.get('precision', 0):.3f}"),
                                     ("Recall", f"{m.get('recall', 0):.3f}"),
                                     ("Cláusula correcta", f"{m.get('clausula', 0) * 100:.0f} %"),
                                     ("Defectos encontrados", f"{m.get('aciertos', 0)}/{m.get('defectos', 0)}"))):
                c.markdown(f"<div class='kpi'><span class='small'>{a}</span><b>{b}</b></div>", unsafe_allow_html=True)
            if m["familias"]:
                f = pd.DataFrame(m["familias"], columns=["familia", "ok", "total"]).astype({"ok": int, "total": int})
                f["recall"] = f.ok / f.total
                f["familia"] = f.familia.str.replace(r"^\d+_", "", regex=True).str.replace("_", " ")
                fig = px.bar(f.sort_values("recall"), x="recall", y="familia", orientation="h", text=f.ok.astype(str) + "/" + f.total.astype(str),
                             range_x=[0, 1.08], color_discrete_sequence=["#0a84ff"], title="Defectos encontrados por familia")
                fig.update_layout(height=300, margin=dict(l=0, r=0, t=40, b=0), plot_bgcolor="#fff", paper_bgcolor="#fff",
                                  xaxis_tickformat=".0%", yaxis_title=None, xaxis_title=None)
                st.plotly_chart(fig, width="stretch")
            with st.expander("Salida completa del puntuador"):
                st.code(m["texto"], language=None)

    with st.container(key="card_registro"):
        st.markdown("### Registro de ejecución\n<p class='small'>Propuestas que el verificador descartó y por qué "
                    "(explicabilidad: nada entra en el CSV sin pasar por código).</p>", unsafe_allow_html=True)
        if desc:
            st.dataframe(t[~t.aceptado][["documento", "ubicacion", "tipo", "origen", "descarte", "justificacion"]],
                         hide_index=True, width="stretch", height=260)
        else:
            st.caption("Sin registros todavía.")


# ================================================================== HISTÓRICO
def responder(q: str) -> str:
    """Asistente determinista: busca en los hallazgos ya calculados (no inventa nada)."""
    s = q.lower().strip()
    tipo = next((t for t in TIPOS if t.lower()[:9] in s), None)
    cl = re.search(r"(?:is\.i\.or\.)?(2\d\d)\b", s)
    if tipo:
        hits = df[df.tipo == tipo]
    elif cl:
        hits = df[df.clausula == f"IS.I.OR.{cl.group(1)}"]
    else:
        pal = [w for w in re.findall(r"\w+", s) if len(w) > 2]
        txt = (df.documento + " " + df.ubicacion + " " + df.justificacion + " " + df.tipo).str.lower()
        hits = df[txt.apply(lambda x: any(w in x for w in pal))] if pal else df.iloc[0:0]
    S.hl = list(zip(hits.documento, hits.ubicacion))
    if not len(hits):
        return "No encuentro hallazgos con esos términos."
    muestra = ", ".join(f"<mark>{html.escape(d)} · {html.escape(u)}</mark>" for d, u in S.hl[:8])
    return (f"Encontré {len(hits)} hallazgo{'s' if len(hits) > 1 else ''} en {hits.documento.nunique()} documento(s): "
            f"{muestra}{'…' if len(hits) > 8 else ''}. Están resaltados en la tabla.")


def v_historico():
    st.markdown("<h2 class='v'>Histórico</h2><p class='sub'>Hallazgos de la solución y tus decisiones. Filtra o "
                "pregunta al asistente para resaltar lo que encuentre.</p>", unsafe_allow_html=True)
    izq, der = st.columns([1.6, 1], gap="medium")
    with izq, st.container(key="card_hist"):
        c = st.columns([2, 1.2, 1.2])
        q = c[0].text_input("Buscar", placeholder="Buscar ubicación o texto", label_visibility="collapsed")
        tipo = c[1].selectbox("Tipo", ["Todos los tipos"] + TIPOS, label_visibility="collapsed")
        dec = c[2].selectbox("Decisión", ["Todas", "Pendiente", "Aprobado", "Rechazado"], label_visibility="collapsed")
        v = df.copy()
        if q:
            v = v[(v.documento + " " + v.ubicacion + " " + v.justificacion).str.lower().str.contains(q.lower(), regex=False)]
        if not tipo.startswith("Todos"):
            v = v[v.tipo == tipo]
        if dec != "Todas":
            v = v[v.decision == ("" if dec == "Pendiente" else dec)]
        if S.hl:
            hl = set(S.hl)
            v = v.assign(_hl=[(a, b) in hl for a, b in zip(v.documento, v.ubicacion)]).sort_values("_hl", ascending=False)
        tabla = v.assign(decision=v.decision.replace("", "Pendiente"))
        cols = ["documento", "ubicacion", "tipo", "clausula", "justificacion", "decision"]
        sty = tabla[cols].style
        if S.hl:
            sty = sty.apply(lambda fila: ["background-color:#fff6cc" if (fila.documento, fila.ubicacion) in hl else ""
                                          for _ in fila], axis=1)
        st.caption(f"{len(v)} de {len(df)} hallazgos")
        st.dataframe(sty, hide_index=True, width="stretch", height=470)
        b1, b2 = st.columns(2)
        b1.download_button("Exportar respuestas.csv", ruta_csv.read_bytes(), file_name="respuestas.csv",
                           mime="text/csv", width="stretch")
        b2.download_button("Exportar feedback.csv", feedback_csv(), file_name="feedback.csv", mime="text/csv",
                           type="primary", width="stretch")
        st.markdown("<p class='note'>respuestas.csv sale tal cual de la solución. feedback.csv reúne tus decisiones y "
                    "los comentarios sin hallazgo: sirve para mejorar el auditor y no altera el CSV oficial.</p>",
                    unsafe_allow_html=True)
    with der, st.container(key="card_chat"):
        st.markdown("### Asistente de hallazgos\n<p class='small'>Busca por tipo, cláusula o texto. Solo responde con "
                    "hallazgos ya calculados.</p>", unsafe_allow_html=True)
        with st.container(height=440, border=False):
            st.markdown("".join(f"<div class='m {m['r']}'>{m['t']}</div>" for m in S.msgs), unsafe_allow_html=True)
        with st.form("f_chat", clear_on_submit=True, border=False):
            a, b = st.columns([4, 1])
            pregunta = a.text_input("Pregunta", placeholder="Escribe tu pregunta", label_visibility="collapsed")
            if b.form_submit_button("Enviar", type="primary", width="stretch") and pregunta.strip():
                S.msgs.append({"r": "u", "t": html.escape(pregunta.strip())})
                S.msgs.append({"r": "a", "t": responder(pregunta)})
                st.rerun()
        if S.hl and st.button("Quitar resaltado", type="tertiary"):
            S.hl = []
            st.rerun()


def feedback_csv() -> bytes:
    filas = [{"documento": d["documento"], "ubicacion": d["ubicacion"],
              "ia_tipo": "", "ia_clausula": "", "decision": d["decision"], "nota": d.get("comentario", ""),
              "usuario": d.get("usuario", ""), "fecha": d["fecha_hora"]} for d in DEC.values()]
    ia = {(r.documento, r.ubicacion): r for r in df.itertuples()}
    for f in filas:
        r = ia.get((f["documento"], f["ubicacion"]))
        if r is not None:
            f["ia_tipo"], f["ia_clausula"] = r.tipo, r.clausula
    for o in leer_csv(OMITIDOS):
        filas.append({"documento": o["documento"], "ubicacion": o["referencia"], "ia_tipo": "(sin hallazgo de la IA)",
                      "ia_clausula": "", "decision": "Omitido por la IA", "nota": o["comentario"],
                      "usuario": o.get("usuario", ""), "fecha": o["fecha_hora"]})
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["documento", "ubicacion", "ia_tipo", "ia_clausula", "decision", "nota",
                                        "usuario", "fecha"])
    w.writeheader()
    w.writerows(filas)
    return buf.getvalue().encode("utf-8")


# ================================================================== CONFIGURACIÓN
TABLA_JERARQUIA = f"""<table style='width:100%;border-collapse:collapse;font-size:14px'>
<tr style='color:#6e6e73;text-align:left'><th>Rango</th><th>Fuente</th><th>Qué aporta</th></tr>
<tr><td>1</td><td><b>Part-IS de EASA (IS.I.OR.200 a 260)</b> · <a href='{EASA_URL}' target='_blank'>enlace oficial</a></td>
<td>Obligaciones y plazos legales. Muchos plazos no se repiten en los documentos internos.</td></tr>
<tr><td>2</td><td><b>STD-SEC-001 vigente</b> (estándar corporativo)</td><td>Valores numéricos de NIMBUS y criterios de control operativo.</td></tr>
<tr><td>3</td><td><b>LISTA-DOC</b> (lista maestra)</td><td>Documentos y versiones en vigor. Un documento sustituido no es referencia.</td></tr>
<tr><td>4</td><td><b>Políticas, manual, procedimientos, especificaciones</b></td><td>Deben respetar lo anterior.</td></tr>
<tr><td>5</td><td><b>Registros, informes, declaraciones, actas</b></td><td>Demuestran si lo anterior se cumple en la práctica.</td></tr>
</table>"""


def v_config():
    tab = S.vista
    c = st.columns([1, 1, 6])
    c[0].button("Reglas", type="primary" if tab == "reglas" else "secondary", width="stretch", on_click=ir, args=("reglas",))
    c[1].button("Usuarios y roles", type="primary" if tab == "usuarios" else "secondary", width="stretch",
                on_click=ir, args=("usuarios",))
    if tab == "reglas":
        docs = resumen_docs()
        with st.container(key="card_criterio"):
            st.markdown("### Criterio de aceptación\n<p class='small'>Un documento se aprueba cuando el porcentaje de "
                        "hallazgos que el auditor rechaza como falsos (o sea, el documento sí cumplía) alcanza el "
                        "umbral, o cuando no tiene hallazgos. Con hallazgos aprobados por encima de lo permitido, "
                        "queda rechazado; con pendientes, en revisión.</p>", unsafe_allow_html=True)
            S.umbral = st.number_input("Umbral de aceptación (%)", 0, 100, S.umbral, step=5)
            res = {"Aprobado": 0, "Rechazado": 0, "En revisión": 0}
            for cod in docs.Documento:
                hs = df[df.documento == cod]
                if not len(hs):
                    res["Aprobado"] += 1
                elif (hs.decision == "").any():
                    res["En revisión"] += 1
                else:
                    pct = (hs.decision == "Rechazado").mean() * 100
                    res["Aprobado" if pct >= S.umbral else "Rechazado"] += 1
            k = st.columns(3)
            for col, (a, b) in zip(k, res.items()):
                col.markdown(f"<div class='kpi'><span class='small'>Documentos · {a}</span><b>{b}</b></div>",
                             unsafe_allow_html=True)
        with st.container(key="card_jerarquia"):
            st.markdown("### Jerarquía normativa", unsafe_allow_html=True)
            st.markdown(TABLA_JERARQUIA, unsafe_allow_html=True)
        with st.container(key="card_verif"):
            st.markdown("### Reglas del verificador (código, no LLM)\n"
                        "| Regla | Qué comprueba |\n|---|---|\n"
                        "| V1 | Tipo y cláusula con el formato oficial (IS.I.OR.210(a) → IS.I.OR.210) |\n"
                        "| V2 | La ubicación contiene un identificador que existe en el documento |\n"
                        "| V3 | La evidencia aparece literalmente en el documento auditado |\n"
                        "| V4 | El plazo, recalculado con código a partir de las fechas, incumple de verdad |\n"
                        "| V5 | La confianza declarada supera el umbral |\n\n"
                        "<p class='note'>Las reglas se cargan desde la solución (src/verificar.py y src/agente.py). "
                        "Cambiarlas requiere aprobación de Calidad; esta pantalla no las modifica.</p>",
                        unsafe_allow_html=True)
    else:
        a, b = st.columns(2)
        with a, st.container(key="card_roles"):
            st.markdown("### Roles\n- **Auditor:** revisa hallazgos, aprueba o rechaza y deja comentarios.\n"
                        "- **Consulta:** lee documentos y usa el asistente, sin decidir.\n"
                        "- **Administrador:** gestiona reglas, usuarios y roles.")
        with b, st.container(key="card_usuarios"):
            usuarios = sorted({d.get("usuario", "") for d in DEC.values()} | {S.user["correo"]})
            st.markdown("### Usuarios\n<p class='small'>Quién ha tomado decisiones en esta auditoría (de "
                        "decisiones_revisor.csv). El inicio de sesión real llegará con Entra ID.</p>",
                        unsafe_allow_html=True)
            st.dataframe(pd.DataFrame({"usuario": usuarios,
                                       "decisiones": [sum(d.get("usuario") == u for d in DEC.values()) for u in usuarios]}),
                         hide_index=True, width="stretch")


{"inicio": v_inicio, "revision": v_revision, "ia": v_ia, "historico": v_historico,
 "reglas": v_config, "usuarios": v_config}[S.vista]()
