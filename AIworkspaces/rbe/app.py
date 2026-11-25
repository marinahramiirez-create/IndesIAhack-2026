"""
Demo RBE: bandeja de alertas de ventas priorizada por € en riesgo.

Ejecutar desde la carpeta rbe/:
    streamlit run app.py
(antes: python -m src.pipeline)
"""
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import db, llm
from src.explicar import hechos

st.set_page_config(page_title="RBE · Radar de ventas", page_icon="🍔", layout="wide")

ICONO = {"alta": "🔴", "media": "🟠", "baja": "🟢"}
ESTADO_ICONO = {"pendiente": "⏳ Revisar", "aprobada": "✅ Confirmada", "descartada": "✖️ Falsa alarma"}


@st.cache_data(show_spinner=False)
def cargar_alertas() -> pd.DataFrame:
    a = db.leer_df("SELECT * FROM alertas")
    for c in ["fecha", "fecha_fin"]:
        a[c] = pd.to_datetime(a[c])
    return a


@st.cache_data(show_spinner=False)
def cargar_metricas() -> dict:
    m = db.leer_df("SELECT * FROM metricas")
    return {r.clave: json.loads(r.valor) for r in m.itertuples()}


@st.cache_data(show_spinner=False)
def cargar_serie(rid: str, canal: str) -> pd.DataFrame:
    s = db.leer_df("SELECT * FROM serie_esperada WHERE restaurante_id = :r AND canal = :c",
                   {"r": rid, "c": canal})
    s["fecha"] = pd.to_datetime(s["fecha"])
    return s.sort_values("fecha")


if not db.existe_tabla("alertas"):
    st.error("No hay alertas todavía. En la terminal, dentro de la carpeta rbe/, ejecuta:")
    st.code("python datos_sinteticos/generar.py\npython -m src.pipeline")
    st.stop()

alertas = cargar_alertas()
metricas = cargar_metricas()
dec = db.ultimas_decisiones()
estado = dict(zip(dec.alerta_id, dec.decision)) if not dec.empty else {}
alertas["estado"] = alertas["alerta_id"].map(lambda i: estado.get(i, "pendiente"))

# --------------------------------------------------------------------------- filtros
st.sidebar.header("Filtros")
def multiselect(etiqueta, col):
    opciones = sorted(alertas[col].dropna().unique())
    return st.sidebar.multiselect(etiqueta, opciones, default=opciones)

f_marca = multiselect("Marca", "marca")
f_zona = multiselect("Zona", "zona")
f_canal = multiselect("Canal", "canal")
f_tipo = multiselect("Tipo", "tipo")
f_sem = st.sidebar.multiselect("Prioridad", ["alta", "media", "baja"], default=["alta", "media", "baja"])
f_estado = st.sidebar.multiselect("Estado", list(ESTADO_ICONO), default=["pendiente"])
solo_caidas = st.sidebar.checkbox("Solo caídas de ventas", value=False)

vista = alertas[alertas.marca.isin(f_marca) & alertas.zona.isin(f_zona) & alertas.canal.isin(f_canal)
                & alertas.tipo.isin(f_tipo) & alertas.semaforo.isin(f_sem) & alertas.estado.isin(f_estado)]
if solo_caidas:
    vista = vista[vista.desviacion_pct < 0]
vista = vista.reset_index(drop=True)

# --------------------------------------------------------------------------- cabecera
st.title("🍔 Radar de anomalías de ventas")
st.caption("Detecta, distingue del ruido (estacionalidad, festivos, campañas, eventos de zona), prioriza por € y explica.")

ruido = metricas.get("ruido", {})
evaluacion = pd.DataFrame(metricas.get("evaluacion", []))
k1, k2, k3, k4 = st.columns(4)
k1.metric("Alertas pendientes", int((alertas.estado == "pendiente").sum()), f"de {len(alertas)} totales", delta_color="off")
riesgo = alertas.loc[(alertas.impacto_eur < 0) & (alertas.estado != "descartada"), "impacto_eur"].abs().sum()
k2.metric("€ en riesgo (caídas)", f"{riesgo:,.0f} €".replace(",", "."))
k3.metric("Ruido filtrado", f"{ruido.get('ruido_reducido_pct', 0)} %",
          f"{ruido.get('alertas_sin_filtrar', 0)} → {ruido.get('alertas_tras_filtrar', 0)} días anómalos", delta_color="off")
if not evaluacion.empty:
    f1 = evaluacion.loc[evaluacion.tipo == "global", "f1"].iloc[0]
    k4.metric("F1 (anomalías inyectadas)", f"{f1:.2f}")
else:
    revisadas = alertas[alertas.estado != "pendiente"]
    p = (revisadas.estado == "aprobada").mean() if len(revisadas) else 0
    k4.metric("Precisión revisada por el equipo", f"{p:.0%}", f"{len(revisadas)} revisadas", delta_color="off")

tab_bandeja, tab_calidad = st.tabs(["📥 Bandeja de alertas", "📊 Calidad del modelo"])

# --------------------------------------------------------------------------- bandeja
def mostrar_bandeja():
    if vista.empty:
        st.info("No hay alertas con estos filtros.")
        return
    tabla = pd.DataFrame({
        "": vista.semaforo.map(ICONO),
        "Tipo": vista.tipo.str.capitalize(),
        "Restaurante": vista.restaurante_id + " · " + vista.marca,
        "Zona": vista.zona,
        "Canal": vista.canal,
        "Fecha": vista.fecha.dt.strftime("%d/%m/%Y"),
        "Desviación": vista.desviacion_pct.map(lambda x: f"{x:+.0f} %"),
        "Impacto €": vista.impacto_eur.round(0).astype(int),
        "Estado": vista.estado.map(ESTADO_ICONO),
    })
    col_lista, col_detalle = st.columns([5, 6])
    with col_lista:
        st.caption(f"{len(vista)} alertas · ordenadas por prioridad (impacto € × severidad)")
        sel = st.dataframe(tabla, hide_index=True, width="stretch", height=560,
                           on_select="rerun", selection_mode="single-row")
        st.download_button("⬇️ Exportar tabla de alertas (CSV)", vista.to_csv(index=False).encode("utf-8-sig"),
                           "alertas_rbe.csv", "text/csv")
    fila = sel.selection.rows[0] if sel.selection.rows else 0
    a = vista.iloc[fila]

    with col_detalle:
        st.subheader(f"{ICONO[a.semaforo]} {a.restaurante_id} · {a.marca} · {a.canal}")
        st.caption(f"{a.zona} · {a.tipologia} · alerta {a.alerta_id}")
        c1, c2, c3 = st.columns(3)
        c1.metric("Real" + (" (media semanal)" if a.tipo == "tendencia" else ""), f"{a.real:,.0f} €".replace(",", "."))
        c2.metric("Esperado", f"{a.esperado:,.0f} €".replace(",", "."), f"{a.desviacion_pct:+.0f} %")
        c3.metric("Impacto" + (f" ({a.semanas} sem.)" if a.tipo == "tendencia" else ""),
                  f"{a.impacto_eur:,.0f} €".replace(",", "."))

        # gráfico real vs esperado
        s = cargar_serie(a.restaurante_id, a.canal)
        if a.tipo == "tendencia":
            ini, fin = a.fecha - pd.Timedelta(days=120), a.fecha_fin
        else:
            ini, fin = a.fecha - pd.Timedelta(days=42), a.fecha + pd.Timedelta(days=21)
        s = s[(s.fecha >= ini) & (s.fecha <= fin)]
        fig = go.Figure()
        fig.add_scatter(x=s.fecha, y=s.esperado, name="Esperado", line=dict(color="#9aa5b1", dash="dot"))
        fig.add_scatter(x=s.fecha, y=s.ventas, name="Real", line=dict(color="#d35400"))
        if a.tipo == "tendencia":
            fig.add_scatter(x=s.fecha, y=s.ventas.rolling(14, center=True).mean(), name="Media 14 días",
                            line=dict(color="#7f3c00", width=3))
            fig.add_vrect(x0=a.fecha, x1=a.fecha_fin, fillcolor="#e74c3c", opacity=0.08, line_width=0)
        else:
            punto = s[s.fecha == a.fecha]
            fig.add_scatter(x=punto.fecha, y=punto.ventas, mode="markers", name="Anomalía",
                            marker=dict(size=14, color="#e74c3c", symbol="circle-open", line=dict(width=3)))
        fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.1),
                          yaxis_title="Ventas (€)")
        st.plotly_chart(fig, width="stretch")

        st.markdown("**¿Qué ha pasado?**")
        st.write(a.explicacion)
        st.markdown("**Recomendación**")
        st.write(a.recomendacion)

        if llm.disponible() and st.button("✨ Redactar con IA (solo usa las cifras calculadas)"):
            with st.spinner("Redactando..."):
                exp, estado_llm = llm.redactar(hechos(a))
            if exp:
                st.success(f"**Resumen:** {exp.resumen}\n\n**Causa probable:** {exp.causa_probable}\n\n"
                           f"**Recomendación:** {exp.recomendacion}")
            else:
                st.warning(f"No se usa el texto del LLM ({estado_llm}). Se mantiene la explicación calculada.")

        with st.expander("🔎 Trazabilidad: de dónde sale cada número"):
            st.json({
                "fuente": f"ventas · restaurante_id={a.restaurante_id} · canal={a.canal} · fecha={a.fecha:%Y-%m-%d}",
                "metodo_esperado": "mediana del mismo día de la semana (6 semanas previas) + ajuste por pares "
                                   "(marca, tipología) + filtro de eventos de zona"
                                   if a.tipo == "puntual" else "cambio de nivel semanal relativo a pares (ruptures PELT)",
                "score": a.score, "contexto_calendario": a.contexto or "ninguno",
                "variacion_tickets_pct": None if pd.isna(a.var_tickets_pct) else a.var_tickets_pct,
                "variacion_ticket_medio_pct": None if pd.isna(a.var_ticket_medio_pct) else a.var_ticket_medio_pct,
                "parte_explicada_por_pares_pct": None if pd.isna(a.efecto_pares_pct) else a.efecto_pares_pct,
            })

        st.markdown("**Decisión del analista** (humano en el bucle)")
        comentario = st.text_input("Comentario (opcional)", key=f"com_{a.alerta_id}")
        b1, b2 = st.columns(2)
        if b1.button("✅ Confirmar incidencia", width="stretch"):
            db.registrar_decision(a.alerta_id, "aprobada", comentario)
            st.rerun()
        if b2.button("✖️ Falsa alarma", width="stretch"):
            db.registrar_decision(a.alerta_id, "descartada", comentario)
            st.rerun()


with tab_bandeja:
    mostrar_bandeja()

# --------------------------------------------------------------------------- calidad
with tab_calidad:
    st.subheader("¿Cuánto ruido quitamos?")
    st.write("Días que un detector simple (solo patrón semanal) marcaría como anómalos, frente a los que quedan "
             "tras descontar calendario, campañas y eventos de zona comparando con restaurantes similares.")
    fig = go.Figure(go.Bar(x=["Sin filtrar", "Tras filtrar"],
                           y=[ruido.get("alertas_sin_filtrar", 0), ruido.get("alertas_tras_filtrar", 0)],
                           marker_color=["#9aa5b1", "#d35400"], text=[ruido.get("alertas_sin_filtrar", 0),
                                                                      ruido.get("alertas_tras_filtrar", 0)]))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10))
    st.plotly_chart(fig, width="stretch")

    if not evaluacion.empty:
        st.subheader("Calidad frente a anomalías inyectadas")
        st.dataframe(evaluacion, hide_index=True, width="stretch")
        st.caption("Puntual: acierto si coincide restaurante, canal y día (±1). Tendencia: ±21 días. "
                   "precision@20: de las 20 primeras de la bandeja, cuántas son anomalías reales.")
    st.subheader("Cómo funciona")
    st.markdown("""
1. **Patrón esperado**: para cada restaurante y canal, lo normal ese día es la mediana del mismo día de la semana en las 6 semanas anteriores (un sábado se compara con los sábados).
2. **Quitar el ruido conocido**: lo que ese día les pasa a restaurantes parecidos no es una anomalía del local. Misma marca → campañas; misma tipología → festivos; si la mayoría de la zona se desvía igual → evento externo (temporal, concierto...).
3. **Anomalías puntuales**: tienen que ser a la vez estadísticamente raras (z robusto ≥ 5) y relevantes para el negocio (≥ 25 % sobre lo esperado).
4. **Cambios de tendencia**: cambios de nivel en la serie semanal relativa a los pares.
5. **Prioridad** = impacto en € × severidad. **Las cifras las calcula el código**; la IA solo redacta.
""")
