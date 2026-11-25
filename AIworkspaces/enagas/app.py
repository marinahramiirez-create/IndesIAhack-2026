"""
Panel de apoyo a la validación de Unidades de Medida (equipo DLC).

Ejecutar desde la carpeta enagas/:
    streamlit run app.py
(antes: python -m src.pipeline)
"""
import json

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src import db, llm
from src.criterios import CRITERIOS_NUM, NOMBRE

st.set_page_config(page_title="Enagás · Validación de UM", page_icon="🔥", layout="wide")

NIVELES = ["Revisión prioritaria", "Revisión recomendada", "Validación automática candidata"]
ICONO = {NIVELES[0]: "🟠", NIVELES[1]: "🔵", NIVELES[2]: "🟢"}
COLOR = {NIVELES[0]: "#F5A623", NIVELES[1]: "#00A9E0", NIVELES[2]: "#8DB31A"}
DECISION_TXT = {"validada": "✅ Validada", "regularizar": "🛠️ A regularizar", "escalada": "⬆️ Escalada"}


@st.cache_data(show_spinner="Cargando datos...")
def cargar() -> pd.DataFrame:
    df = db.leer_df("SELECT * FROM um_dia")
    df["fecha"] = pd.to_datetime(df["fecha"])
    return df


@st.cache_data(show_spinner=False)
def cargar_metricas() -> dict:
    m = db.leer_df("SELECT * FROM metricas")
    return {r.clave: json.loads(r.valor) for r in m.itertuples()}


if not db.existe_tabla("um_dia"):
    st.error("No hay resultados todavía. En la terminal, dentro de la carpeta enagas/, ejecuta:")
    st.code("python datos_sinteticos/generar.py\npython -m src.pipeline")
    st.stop()

datos = cargar()
metricas = cargar_metricas()
prueba = datos[datos["particion"] == "prueba"]

# --------------------------------------------------------------------------- barra lateral
st.sidebar.header("Día a validar")
fechas = sorted(prueba["fecha"].dt.date.unique())
fecha = pd.Timestamp(st.sidebar.selectbox("Fecha", fechas, index=len(fechas) - 1,
                                          format_func=lambda f: f.strftime("%d/%m/%Y")))
f_ramal = st.sidebar.multiselect("Ramal", sorted(datos["ramal"].unique()))
f_tipo = st.sidebar.multiselect("Tipo de consumo", sorted(datos["tipo_consumo"].unique()))
f_nivel = st.sidebar.multiselect("Nivel", NIVELES, default=NIVELES[:2])
st.sidebar.caption("Por defecto se ocultan las candidatas a validación automática.")

dia = datos[datos["fecha"] == fecha].copy()
dec = db.decisiones_del_dia(fecha)
decision_por_um = dict(zip(dec.um_id, dec.decision)) if not dec.empty else {}
dia["decision"] = dia["um_id"].map(lambda u: decision_por_um.get(u, ""))

# --------------------------------------------------------------------------- cabecera
st.title("🔥 Validación inteligente de Unidades de Medida")
st.caption(f"Panel de apoyo al equipo DLC · {fecha:%d/%m/%Y} · criterios adaptados al histórico de cada UM")

c1, c2, c3, c4, c5 = st.columns(5)
n = len(dia)
cuenta = dia["nivel"].value_counts()
c1.metric("UM del día", n)
c2.metric("🟠 Revisión prioritaria", int(cuenta.get(NIVELES[0], 0)))
c3.metric("🔵 Revisión recomendada", int(cuenta.get(NIVELES[1], 0)))
c4.metric("🟢 Validación automática", int(cuenta.get(NIVELES[2], 0)), f"{cuenta.get(NIVELES[2], 0) / max(n, 1):.0%} de las UM",
          delta_color="off")
c5.metric("Alertas con la regla estándar", int(dia["alerta_std"].sum()),
          f"{int((dia['nivel'] != NIVELES[2]).sum()) - int(dia['alerta_std'].sum()):+d} con IA", delta_color="inverse")

tab_bandeja, tab_comp, tab_mes, tab_como = st.tabs(
    ["📥 Bandeja del día", "📊 Estándar vs adaptativa", "🗓️ Vista mensual", "ℹ️ Cómo funciona"])


def criterios_que_saltan(r, prefijo: str) -> str:
    return ", ".join(NOMBRE[c] for c in NOMBRE if r[f"{prefijo}_{c}"]) or "—"


def tabla_criterios(r) -> pd.DataFrame:
    filas = []
    for c in ["nc", "error", "modula", "serie"]:
        extra = f" (habitual: {r[f'frec_{c}']:.0%} de los días)" if c in ("modula", "serie") else ""
        filas.append({"Criterio": NOMBRE[c], "Valor": "Sí" if r[c] else "No", "Umbral estándar": "marca",
                      "Umbral propio UM": "marca" + extra,
                      "Estándar": "⚠️" if r[f"std_{c}"] else "✓", "Adaptativa": "⚠️" if r[f"ad_{c}"] else "✓"})
    for c in CRITERIOS_NUM:
        if c == "dif_orion_abs":
            fmt = lambda x: "—" if pd.isna(x) else f"{x:,.0f} {r['unidad']}".replace(",", ".")
        else:
            fmt = lambda x: "—" if pd.isna(x) else f"{x:.2%}"
        filas.append({"Criterio": NOMBRE[c], "Valor": fmt(r[c]), "Umbral estándar": fmt(r[f"umbral_std_{c}"]),
                      "Umbral propio UM": fmt(r[f"umbral_ad_{c}"]),
                      "Estándar": "⚠️" if r[f"std_{c}"] else "✓", "Adaptativa": "⚠️" if r[f"ad_{c}"] else "✓"})
    return pd.DataFrame(filas)


def grafico_serie(r):
    h = datos[(datos["um_id"] == r["um_id"]) & (datos["fecha"] > fecha - pd.Timedelta(days=60))
              & (datos["fecha"] <= fecha)].sort_values("fecha")
    fig = go.Figure()
    fig.add_scatter(x=h["fecha"], y=h["valor_orion"], name="ORION (validado GTS)", line=dict(color="#9aa5b1", dash="dot"))
    fig.add_scatter(x=h["fecha"], y=h["valor_neptuno"], name="Neptuno (campo)", line=dict(color="#00A9E0"))
    aj = h[(h["etiqueta"] == 1) & (h["fecha"] < fecha)]
    fig.add_scatter(x=aj["fecha"], y=aj["valor_neptuno"], mode="markers", name="Días con ajuste previo",
                    marker=dict(color="#7a4b00", size=8, symbol="x"))
    hoy = h[h["fecha"] == fecha]
    fig.add_scatter(x=hoy["fecha"], y=hoy["valor_neptuno"], mode="markers", name="Día a validar",
                    marker=dict(size=15, color=COLOR[r["nivel"]], symbol="circle-open", line=dict(width=3)))
    fig.update_layout(height=280, margin=dict(l=10, r=10, t=10, b=10), legend=dict(orientation="h", y=1.15),
                      yaxis_title=r["unidad"])
    return fig, h


def grafico_banda(h, r):
    fig = go.Figure()
    fig.add_scatter(x=h["fecha"], y=h["umbral_ad_dif_orion"], line=dict(width=0), showlegend=False, hoverinfo="skip")
    fig.add_scatter(x=h["fecha"], y=-h["umbral_ad_dif_orion"], fill="tonexty", fillcolor="rgba(141,179,26,0.18)",
                    line=dict(width=0), name="Rango normal de esta UM")
    std = r["umbral_std_dif_orion"]
    fig.add_hline(y=std, line=dict(color="#c0392b", dash="dash", width=1))
    fig.add_hline(y=-std, line=dict(color="#c0392b", dash="dash", width=1), annotation_text="umbral estándar",
                  annotation_position="bottom right")
    fig.add_scatter(x=h["fecha"], y=h["dif_orion_signo"], name="Neptuno vs ORION", line=dict(color="#00A9E0"))
    fig.update_layout(height=220, margin=dict(l=10, r=10, t=10, b=10), yaxis_tickformat=".1%",
                      legend=dict(orientation="h", y=1.2))
    return fig


# --------------------------------------------------------------------------- bandeja
def mostrar_bandeja():
    vista = dia.copy()
    if f_ramal:
        vista = vista[vista["ramal"].isin(f_ramal)]
    if f_tipo:
        vista = vista[vista["tipo_consumo"].isin(f_tipo)]
    if f_nivel:
        vista = vista[vista["nivel"].isin(f_nivel)]
    vista = vista.sort_values("score", ascending=False).reset_index(drop=True)
    if vista.empty:
        st.info("No hay UM con estos filtros para este día.")
        return
    tabla = pd.DataFrame({
        "": vista["nivel"].map(ICONO),
        "UM": vista["um_id"],
        "Ramal": vista["ramal"],
        "Tipo": vista["tipo_consumo"] + " · " + vista["tipo_um"],
        "Riesgo": vista["score"],
        "Causa probable": vista["causa_probable"],
        "Regla estándar": [criterios_que_saltan(r, "std") for _, r in vista.iterrows()],
        "Decisión": vista["decision"].map(DECISION_TXT).fillna(""),
    })
    izq, der = st.columns([5, 6])
    with izq:
        st.caption(f"{len(vista)} UM · ordenadas por riesgo")
        sel = st.dataframe(tabla, hide_index=True, width="stretch", height=600, on_select="rerun",
                           selection_mode="single-row",
                           column_config={"Riesgo": st.column_config.ProgressColumn(
                               "Riesgo", min_value=0.0, max_value=1.0, format="%.2f")})
        st.download_button("⬇️ Exportar (CSV)", vista.to_csv(index=False).encode("utf-8-sig"),
                           f"validacion_{fecha:%Y%m%d}.csv", "text/csv")
    r = vista.iloc[sel.selection.rows[0] if sel.selection.rows else 0]

    with der:
        st.subheader(f"{ICONO[r['nivel']]} {r['um_id']} · {r['nivel']}")
        st.caption(f"{r['ramal']} ({r['zona']}) · {r['tipo_consumo']} · UM de {r['tipo_um']} · "
                   f"cromatógrafo {r['cromatografo_id']} · riesgo {r['score']:.2f}")
        st.markdown(f"**Causa probable:** {r['causa_probable']}")
        st.markdown(f"**Por qué:** {r['explicacion']}")
        st.markdown(f"**Recomendación:** {r['recomendacion']}")

        fig, h = grafico_serie(r)
        st.plotly_chart(fig, width="stretch")
        st.caption("Diferencia Neptuno vs ORION: rango normal aprendido para esta UM (verde) frente al umbral estándar (rojo)")
        st.plotly_chart(grafico_banda(h, r), width="stretch")

        st.markdown("**Criterios de validación: estándar vs propios de la UM**")
        st.dataframe(tabla_criterios(r), hide_index=True, width="stretch")

        if llm.disponible() and st.button("✨ Redactar resumen con IA (solo usa los datos calculados)"):
            with st.spinner("Redactando..."):
                exp, estado = llm.redactar(llm.hechos(r))
            if exp:
                st.success(f"**Resumen:** {exp.resumen}\n\n**Causa probable:** {exp.causa_probable}\n\n"
                           f"**Recomendación:** {exp.recomendacion}")
            else:
                st.warning(f"No se usa el texto del LLM ({estado}). Se mantiene la explicación calculada.")

        with st.expander("🔎 Trazabilidad: datos de cada fuente para este día"):
            st.json({
                "Neptuno (campo)": {"volumen_normalizado": r["vol_neptuno"], "pcs_calculado": r["pcs_calculado"],
                                    "energia": r["ene_neptuno"], "estado": r["estado_neptuno"]},
                "SLM (calculado)": {"volumen_normalizado": r["vol_slm"], "energia": r["ene_slm"],
                                    "modulado": bool(r["modulado"])},
                "ORION (validado GTS)": {"volumen_normalizado": r["vol_orion"], "energia": r["ene_orion"]},
                "Calidad de gas": {"cromatografo": r["cromatografo_id"], "pcs": r["pcs_cromatografo"]},
                "Contrastación": {"dias_desde_ultima": None if pd.isna(r["dias_desde_contraste"]) else int(r["dias_desde_contraste"]),
                                  "error_pct": None if pd.isna(r["error_pct"]) else r["error_pct"],
                                  "observaciones": r["observaciones"] if isinstance(r["observaciones"], str) else ""},
                "Modelo": {"score": round(float(r["score"]), 4),
                           "variables_principales": [r["var_1"], r["var_2"], r["var_3"]]},
            })

        st.markdown("**Decisión del equipo DLC** (queda registrada y realimenta el modelo)")
        comentario = st.text_input("Comentario (opcional)", key=f"c_{r['um_id']}_{fecha:%Y%m%d}")
        b1, b2, b3 = st.columns(3)
        for col, (clave, texto) in zip([b1, b2, b3], DECISION_TXT.items()):
            if col.button(texto, width="stretch", key=f"{clave}_{r['um_id']}"):
                db.registrar_decision(r["um_id"], fecha, clave, r["nivel"], comentario)
                st.rerun()


with tab_bandeja:
    mostrar_bandeja()

# --------------------------------------------------------------------------- comparativa
with tab_comp:
    res = metricas.get("resumen", {})
    comp = pd.DataFrame(metricas.get("comparativa", []))
    st.subheader(f"Periodo de prueba: {res.get('dias_prueba', 0)} días × {res.get('um', 0)} UM (datos no vistos por el modelo)")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Reducción de revisiones manuales", f"{res.get('reduccion_revisiones_vs_estandar_pct', 0)} %")
    k2.metric("Candidatas a validación automática", f"{res.get('pct_validacion_automatica', 0)} %")
    k3.metric("Incidencias que se escaparían", f"{res.get('incidencias_escapadas_en_auto_pct', 0)} %")
    k4.metric("AUC-PR del score", res.get("auc_pr_modelo", 0))

    if not comp.empty:
        verdad = "incidencia_real" if res.get("incidencias_reales_disponibles") else "etiqueta_proxy"
        fig = go.Figure(go.Bar(x=comp["enfoque"], y=comp["revisiones_dia"], text=comp["revisiones_dia"],
                               marker_color=["#c0392b", "#9aa5b1", "#00A9E0", "#F5A623"]))
        fig.update_layout(height=300, yaxis_title="UM a revisar por día", margin=dict(l=10, r=10, t=10, b=10))
        st.plotly_chart(fig, width="stretch")
        st.dataframe(comp[["enfoque", "revisiones_dia", "pct_um_dia_revisadas", f"precision_{verdad}",
                           f"recall_{verdad}", f"f1_{verdad}"]].rename(columns=lambda c: c.replace(f"_{verdad}", "")),
                     hide_index=True, width="stretch")
        st.caption("Evaluado contra " + ("las incidencias reales inyectadas (datos sintéticos)." if verdad == "incidencia_real"
                                         else "los días que el usuario acabó ajustando o modificando (etiqueta proxy)."))
    if metricas.get("recall_por_tipo"):
        st.markdown("**Incidencias detectadas por tipo** (no enviadas a validación automática)")
        st.dataframe(pd.Series(metricas["recall_por_tipo"], name="detectadas").map("{:.0%}".format),
                     width="stretch")
        st.caption("Las derivas que se escapan están en UM muy ruidosas (ciclos combinados, UM pequeñas): una "
                   "deriva del 2-6 % queda dentro de su variación normal. Ahí la herramienta es la contrastación periódica.")
    imp = metricas.get("modelo", {}).get("importancia", {})
    if imp:
        s = pd.Series(imp).head(12)[::-1]
        fig = go.Figure(go.Bar(x=s.values, y=s.index, orientation="h", marker_color="#00A9E0"))
        fig.update_layout(height=360, title="Variables que más pesan en el score", margin=dict(l=10, r=10, t=40, b=10))
        st.plotly_chart(fig, width="stretch")

# --------------------------------------------------------------------------- mensual
with tab_mes:
    st.subheader("Validación mensual por UM")
    mes = st.selectbox("Mes", sorted(prueba["fecha"].dt.to_period("M").unique(), reverse=True), format_func=str)
    m = prueba[prueba["fecha"].dt.to_period("M") == mes]
    agg = m.groupby(["um_id", "ramal", "tipo_um"]).agg(
        dias_prioritaria=("nivel", lambda s: (s == NIVELES[0]).sum()),
        dias_recomendada=("nivel", lambda s: (s == NIVELES[1]).sum()),
        riesgo_max=("score", "max"),
        neptuno=("valor_neptuno", "sum"), orion=("valor_orion", "sum"),
        dias_dif_pcs=("ad_dif_pcs", "sum"),
    ).reset_index()
    agg["DIF_ORION mes"] = (agg["neptuno"] / agg["orion"] - 1).map("{:+.2%}".format)
    con = m.groupby("um_id").agg(CONTRAS=("dias_desde_contraste", lambda s: bool((s < 31).any())),
                                 CONTRAS_OBS=("contraste_con_obs", lambda s: bool(s.astype(bool).any())))
    agg = agg.merge(con, on="um_id").sort_values("riesgo_max", ascending=False)
    st.dataframe(agg.drop(columns=["neptuno", "orion"]), hide_index=True, width="stretch",
                 column_config={"riesgo_max": st.column_config.ProgressColumn("riesgo máx.", min_value=0.0, max_value=1.0)})

# --------------------------------------------------------------------------- cómo funciona
with tab_como:
    st.markdown("""
**1. Cruce de fuentes.** Una fila por UM y día con Neptuno (campo), SLM (calculado), ORION (validado GTS),
calidad de gas (cromatógrafo) y contrastación de contadores.

**2. Criterios estándar** (los actuales, iguales para todas las UM): NC, ERROR, MODULA, SERIE, DIF_PCS,
DIF_ORION, DIF_ORION_ABS, DIF_HIS.

**3. Criterios adaptativos.** Para cada UM, su "rango normal" en cada criterio se aprende de su propio
histórico (percentil 99,5 del último año, solo días pasados y sin incidencias). Una central de ciclo
combinado que arranca y para, o una UM pequeña con mucho ruido relativo frente a ORION, dejan de dar
falsas alarmas.

**4. Score de riesgo.** Un modelo (LightGBM + Isolation Forest) combina todas las señales: cuánto se sale cada
criterio de lo normal *para esa UM*, deriva frente a ORION, contador bloqueado, comportamiento del ramal,
contrastación y ajustes previos. Aprende de los días que el equipo tuvo que **ajustar o modificar**.

**5. Tres niveles calibrados.** Validación automática candidata (conserva el 93 % de las incidencias fuera de
este grupo), revisión recomendada y revisión prioritaria (≥ 80 % de acierto en calibración).

**6. Explicación.** Las variables que más empujan el score (SHAP) se traducen a frases con sus valores.
Las cifras las calcula el código; la IA generativa (opcional) solo redacta.

**7. Humano en el bucle.** Cada decisión (validar / regularizar / escalar) se guarda en la base de datos y
sirve para reentrenar: "las decisiones realimentan el modelo y ajustan umbrales".
""")
