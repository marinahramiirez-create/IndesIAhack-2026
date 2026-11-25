"""
Demo Acerinox: asistente comercial de inventario por voz y texto.

Ejecutar desde la carpeta acerinox/:
    python -m streamlit run app.py
(antes, una vez: python datos_sinteticos/generar.py)
"""
import json

import pandas as pd
import streamlit as st

import config
from src import catalogo, db, inventario, llm, transformaciones
from src.asistente import Conversacion

st.set_page_config(page_title="Acerinox · Asistente de inventario", page_icon="🔩", layout="wide")

if not (config.DIR_DATOS / config.STOCK).exists():
    st.error("No hay datos. En la terminal, dentro de la carpeta acerinox/, ejecuta:")
    st.code("python datos_sinteticos/generar.py")
    st.stop()
if not db.existe_tabla("stock"):
    inventario.cargar_stock_en_bd()

if "conv" not in st.session_state:
    st.session_state.conv = Conversacion()
    st.session_state.mensajes = []
    st.session_state.ultima = None

EJEMPLOS = [
    "Una chapa brillante de 2 milímetros que aguante el mar, 1250x2500, 10 chapas",
    "Fleje de 316L 2B de 0,8 mm y 300 mm de ancho, 2 toneladas",
    "Chapa espejo de 304 de 1 mm, 1000x2000, 5 chapas",
    "Algo de acero que aguante el mar",
    "Bobina de 904L BA de 1 mm",
]


def enviar(texto: str):
    texto = texto.strip()
    if not texto:
        return
    st.session_state.mensajes.append({"rol": "user", "texto": texto})
    r = st.session_state.conv.responder(texto)
    st.session_state.mensajes.append({"rol": "assistant", "texto": r["respuesta_natural"] or r["respuesta"]})
    st.session_state.ultima = r


# --------------------------------------------------------------------------- barra lateral
with st.sidebar:
    st.header("🔩 Asistente de inventario")
    if st.button("🆕 Nueva consulta", width="stretch"):
        st.session_state.conv.nueva()
        st.session_state.mensajes, st.session_state.ultima = [], None
        st.rerun()
    st.caption("Ejemplos:")
    for e in EJEMPLOS:
        if st.button(e, width="stretch"):
            st.session_state.conv.nueva()
            st.session_state.mensajes = []
            enviar(e)
            st.rerun()
    st.divider()
    st.subheader("🎙️ Voz")
    if llm.voz_disponible():
        audio = st.audio_input("Pulsa y habla")
        if audio is not None and st.session_state.get("audio_id") != hash(audio.getvalue()):
            st.session_state.audio_id = hash(audio.getvalue())
            texto = llm.transcribir(audio.getvalue())
            if texto:
                enviar(texto)
                st.rerun()
    else:
        st.info("Voz desactivada: configura en .env el despliegue de Whisper "
                "(AZURE_OPENAI_WHISPER) o LLM_PROVEEDOR=openai.")
    st.caption(f"LLM: {'activo (' + config.LLM_PROVEEDOR + ')' if llm.disponible() else 'no configurado → solo reglas'}")

tab_chat, tab_stock, tab_demanda, tab_met, tab_reglas = st.tabs(
    ["💬 Asistente", "📦 Stock", "📝 Demanda no atendida", "📊 Métricas", "📘 Catálogo y reglas"])

# --------------------------------------------------------------------------- chat
with tab_chat:
    izq, der = st.columns([3, 2])
    with izq:
        for m in st.session_state.mensajes:
            with st.chat_message(m["rol"]):
                st.markdown(m["texto"])
        if not st.session_state.mensajes:
            st.info("Escribe una petición como la diría un cliente, p. ej. *«una chapa brillante de 2 mm que aguante el mar»*.")
    pregunta = st.chat_input("¿Qué necesita el cliente?")
    if pregunta:
        enviar(pregunta)
        st.rerun()

    with der:
        r = st.session_state.ultima
        if r:
            f = r["ficha"]
            st.markdown("#### 🧾 Ficha técnica interpretada")
            st.caption("Cada valor con las palabras del cliente que lo justifican y su respaldo en el catálogo.")
            if f.evidencias:
                st.dataframe(pd.DataFrame(f.evidencias).rename(columns={
                    "campo": "Campo", "valor": "Valor", "texto": "Dijo el cliente", "cita": "Respaldo"}),
                    hide_index=True, width="stretch")
            secs = sorted({c.split("§")[1].split(" ")[0].strip(",") for e in f.evidencias
                           for c in [e.get("cita", "")] if "§" in c})
            for s in secs:
                with st.expander(f"Catálogo §{s}"):
                    st.write(catalogo.texto_seccion(s) or "—")

            b = r["busqueda"]
            if b:
                st.markdown("#### 📦 Propuestas")
                for i, p in enumerate(b["propuestas"], 1):
                    color = "#2e9e5b" if p["encaje"] == "exacto" else "#e0a100"
                    with st.container(border=True):
                        st.markdown(f"**{i}. {p['id_bulto']}** &nbsp; <span style='background:{color};color:white;"
                                    f"padding:2px 8px;border-radius:10px'>{p['encaje']}</span>", unsafe_allow_html=True)
                        medidas = f"{p['ancho_mm']:.0f} x {p['largo_mm']:.0f} mm" if p["formato"] == "chapa" else f"ancho {p['ancho_mm']:.0f} mm"
                        st.write(f"{p['formato']} · {p['grado']} · {p['acabado']} · {p['espesor_mm']} mm · {medidas} · "
                                 f"{p['peso_kg']:,.0f} kg · {p['almacen']} · entrada {p['fecha_entrada']}".replace(",", "."))
                        c1, c2 = st.columns(2)
                        c1.metric("Merma", f"{p['merma']:.0%}")
                        c2.metric("Operaciones", len(p["operaciones"]))
                        for o in p["operaciones"]:
                            st.markdown(f"- **{o['regla']}** {o['operacion']}: {o['detalle']}")
                        st.caption(f"Por qué en esta posición: {p['motivo_ranking']}. {p['detalle_cantidad']}")
                if r["errores_validacion"]:
                    st.error("Validador: " + "; ".join(r["errores_validacion"]))
                else:
                    st.success("✔ Validador: todos los bultos existen, están disponibles y las operaciones cumplen las reglas.")
                with st.expander("Trazabilidad: consulta SQL ejecutada sobre el stock"):
                    st.code(b["sql"], language="sql")
                    st.json(b["params"])
                    if b["descartados"]:
                        st.dataframe(pd.DataFrame(b["descartados"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- stock
with tab_stock:
    s = inventario.stock()
    f1, f2, f3 = st.columns(3)
    g = f1.multiselect("Grado", sorted(s.grado.unique()))
    fo = f2.multiselect("Formato", sorted(s.formato.unique()))
    es = f3.multiselect("Estado", sorted(s.estado.unique()), default=["disponible"])
    v = s[(s.grado.isin(g) if g else True) & (s.formato.isin(fo) if fo else True) & (s.estado.isin(es) if es else True)]
    st.dataframe(v, hide_index=True, width="stretch")
    st.caption(f"{len(v)} bultos · {v.peso_kg.sum():,.0f} kg".replace(",", "."))

# --------------------------------------------------------------------------- demanda no atendida
with tab_demanda:
    st.caption("Peticiones sin bulto disponible: información para compras y producción.")
    if db.existe_tabla("peticiones"):
        p = db.leer_df("SELECT fecha_hora, texto, accion, resultado, bulto, ficha FROM peticiones ORDER BY fecha_hora DESC")
        sin = p[p.resultado == "sin_stock"].copy()
        if len(sin):
            fichas = sin.ficha.apply(json.loads)
            sin["producto"] = fichas.apply(lambda x: f"{x.get('formato')} {'/'.join(x.get('grados') or ['?'])} "
                                                     f"{x.get('acabado') or ''} {x.get('espesor_mm')} mm")
            st.dataframe(sin.drop(columns=["ficha"]), hide_index=True, width="stretch")
            st.bar_chart(sin.producto.value_counts())
        else:
            st.success("Todavía no hay demanda no atendida.")
        with st.expander("Todas las peticiones"):
            st.dataframe(p.drop(columns=["ficha"]), hide_index=True, width="stretch")

# --------------------------------------------------------------------------- métricas
with tab_met:
    st.caption("Banco de peticiones de prueba (casos_prueba.csv): `python -m src.evaluar` actualiza estas cifras.")
    if db.existe_tabla("metricas"):
        m = {r.clave: json.loads(r.valor) for r in db.leer_df("SELECT * FROM metricas").itertuples()}
        c = st.columns(4)
        c[0].metric("Traducción al dato", f"{m['traduccion_campos_pct']:.0%}", help="Campos de la ficha bien interpretados")
        c[1].metric("Acción correcta", f"{m['accion_correcta_pct']:.0%}", help="Buscar / repreguntar / rechazar")
        c[2].metric("Bulto correcto (1.ª propuesta)", f"{m['bulto_correcto_pct']:.0%}")
        c[3].metric("Bultos inventados", m["bultos_inventados"], help="Debe ser 0: prohibido inventar")
        st.dataframe(db.leer_df("SELECT texto, accion_esperada, accion, campos_mal, bulto_esperado, bulto_propuesto FROM evaluacion"),
                     hide_index=True, width="stretch")
    else:
        st.info("Ejecuta `python -m src.evaluar` para calcular las métricas.")

# --------------------------------------------------------------------------- catálogo y reglas
with tab_reglas:
    a, b = st.columns(2)
    with a:
        st.subheader("Reglas de transformación")
        st.text((config.DIR_DATOS / config.REGLAS).read_text(encoding="utf-8"))
        st.caption("Implementadas en src/transformaciones.py: " + ", ".join(f"{k} {v}" for k, v in transformaciones.REGLAS.items()))
    with b:
        st.subheader("Catálogo")
        q = st.text_input("Buscar en el catálogo", placeholder="p. ej. ¿qué acabado es el más brillante?")
        for sec in (catalogo.buscar(q) if q else catalogo.secciones()):
            with st.expander(f"§{sec['seccion']} · {sec['titulo']}"):
                st.write(sec["texto"])
