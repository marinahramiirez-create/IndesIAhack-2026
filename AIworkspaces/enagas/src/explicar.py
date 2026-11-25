"""
Explicaciones para el equipo DLC (deterministas: cada número sale de la tabla, no de un LLM).

Para cada UM-día:
  - causa_probable: reglas sobre las señales (comunicación, conversor bloqueado, PCS, deriva...)
  - explicacion: las 3 variables que más empujan el score, traducidas a frases con sus valores
  - si es "validación automática candidata": qué criterios estándar habrían saltado y por qué
    para ESTA UM son normales (esto es justo lo que aporta el criterio adaptativo)
"""
import math

import pandas as pd

from src.criterios import CRITERIOS_NUM, NOMBRE


def _ok(*v) -> bool:
    return all(x is not None and not (isinstance(x, float) and math.isnan(x)) for x in v)


def _num(x, dec=0) -> str:
    return f"{x:,.{dec}f}".replace(",", "X").replace(".", ",").replace("X", ".")


def frase(var: str, r) -> str | None:
    u = r.unidad
    f = {
        "exceso_dif_orion": lambda: _ok(r.dif_orion, r.umbral_ad_dif_orion) and
            f"Diferencia Neptuno–ORION del {r.dif_orion:.1%}; lo habitual en esta UM es hasta {r.umbral_ad_dif_orion:.1%}.",
        "dif_orion_signo": lambda: _ok(r.dif_orion_signo) and
            f"Neptuno está un {r.dif_orion_signo:+.1%} respecto al dato validado de ORION.",
        "exceso_dif_orion_abs": lambda: _ok(r.dif_orion_abs, r.umbral_ad_dif_orion_abs) and
            f"Diferencia absoluta con ORION de {_num(r.dif_orion_abs)} {u} (habitual hasta {_num(r.umbral_ad_dif_orion_abs)} {u}).",
        "exceso_dif_pcs": lambda: _ok(r.dif_pcs, r.umbral_ad_dif_pcs) and
            f"El PCS calculado difiere un {r.dif_pcs:.2%} del cromatógrafo {r.cromatografo_id} (habitual hasta {r.umbral_ad_dif_pcs:.2%}).",
        "exceso_dif_his": lambda: _ok(r.dif_his_signo, r.umbral_ad_dif_his) and
            f"El volumen varía un {r.dif_his_signo:+.0%} frente al mismo día de la semana anterior (habitual hasta ±{r.umbral_ad_dif_his:.0%}).",
        "dif_his_signo": lambda: _ok(r.dif_his_signo) and
            f"El volumen varía un {r.dif_his_signo:+.0%} frente al mismo día de la semana anterior.",
        "dif_his_vs_ramal": lambda: _ok(r.ramal_dif_his, r.dif_his_vs_ramal) and
            f"El ramal {r.ramal} varía un {r.ramal_dif_his:+.0%}, pero esta UM se separa {r.dif_his_vs_ramal:+.0%} de su ramal.",
        "ramal_dif_his": lambda: _ok(r.ramal_dif_his) and
            f"Todo el ramal {r.ramal} varía un {r.ramal_dif_his:+.0%} frente a la semana anterior (efecto de red/demanda).",
        "deriva_orion": lambda: _ok(r.deriva_orion) and
            f"La diferencia con ORION de la última semana se ha desplazado {r.deriva_orion:+.1%} respecto a su nivel habitual (posible deriva del conversor).",
        "nc": lambda: bool(r.nc) and "No llegó un resultado correcto de campo (NC): el valor del día es estimado/modulado.",
        "error": lambda: bool(r.error) and "La lectura llegó marcada con error (energía o volumen normalizado bajo error).",
        "ad_modula": lambda: bool(r.ad_modula) and "El dato está modulado, algo poco habitual en esta UM.",
        "serie": lambda: bool(r.serie) and "Tiene un ajuste tipificado como 'Prueba en Serie'.",
        "frec_modula": lambda: _ok(r.frec_modula) and f"Esta UM llega modulada el {r.frec_modula:.0%} de los días.",
        "igual_que_ayer": lambda: bool(r.igual_que_ayer) and "El volumen es idéntico al del día anterior (posible conversor bloqueado).",
        "cero_con_orion": lambda: bool(r.cero_con_orion) and "Neptuno marca 0 mientras ORION registra consumo.",
        "ajustes_previos_90d": lambda: _ok(r.ajustes_previos_90d) and
            f"Ha tenido {int(r.ajustes_previos_90d)} días con ajustes en los últimos 90 días.",
        "dias_desde_contraste": lambda: frase_contraste(r),
        "error_contraste_abs": lambda: frase_contraste(r),
        "contraste_con_obs": lambda: frase_contraste(r),
        "tipo_consumo_cod": lambda: f"Tipo de consumo: {r.tipo_consumo}.",
        "es_energia": lambda: f"UM de {r.tipo_um}.",
        "rareza_iforest": lambda: "La combinación de señales es inusual frente a su histórico (Isolation Forest).",
    }.get(var)
    if f is None:
        return None
    try:
        return f() or None
    except (AttributeError, TypeError, ValueError):
        return None


def frase_contraste(r) -> str | None:
    if not _ok(r.dias_desde_contraste, r.error_pct):
        return "No hay contrastación de contadores registrada para esta UM."
    obs = f" Observaciones: «{r.observaciones}»." if isinstance(r.observaciones, str) and r.observaciones else ""
    if abs(r.error_pct) < 0.5 and not obs:
        return None  # contrastación normal: no aporta a la explicación
    return f"Última contrastación hace {int(r.dias_desde_contraste)} días con error {r.error_pct:+.2f} %.{obs}"


def causa_probable(r) -> str:
    if r.nc:
        return "Fallo de comunicación / dato no recibido"
    if r.error:
        return "Lectura con error en origen"
    if r.cero_con_orion or (r.igual_que_ayer and _ok(r.dif_orion) and r.dif_orion > r.umbral_ad_dif_orion):
        return "Posible contador o conversor bloqueado"
    if _ok(r.exceso_dif_pcs) and r.exceso_dif_pcs > 1:
        return "Calidad de gas: PCS calculado ≠ cromatógrafo asignado"
    if _ok(r.deriva_orion, r.exceso_dif_orion) and abs(r.deriva_orion) > 0.01 and r.exceso_dif_orion > 1:
        return "Posible deriva del conversor (diferencia con ORION creciente)"
    if _ok(r.exceso_dif_his, r.dif_his_vs_ramal) and r.exceso_dif_his > 1 and abs(r.dif_his_vs_ramal) > 0.3:
        return "Salto de consumo no explicado por el ramal: posible lectura errónea"
    if _ok(r.exceso_dif_orion) and r.exceso_dif_orion > 1:
        return "Diferencia con ORION superior a lo habitual en esta UM"
    if _ok(r.deriva_orion) and abs(r.deriva_orion) > 0.005:
        return "Deriva incipiente frente a ORION (vigilar)"
    if _ok(r.ramal_dif_his) and abs(r.ramal_dif_his) > 0.2:
        return "Variación compartida por todo el ramal (demanda real)"
    if _ok(r.ajustes_previos_90d) and r.ajustes_previos_90d >= 3:
        return "UM con incidencias recientes: revisión preventiva"
    if _ok(r.dif_his, r.exceso_dif_his) and r.dif_his > 0.25 and r.exceso_dif_his <= 1:
        return "Cambio de consumo dentro del patrón habitual de la UM"
    return "Señales débiles: revisión preventiva"


def falsas_alarmas_evitadas(r) -> str | None:
    """Criterios estándar que saltan pero que, para esta UM, están dentro de lo normal."""
    trozos = []
    for c in CRITERIOS_NUM:
        if getattr(r, f"std_{c}") and not getattr(r, f"ad_{c}"):
            v, ts, ta = getattr(r, c), getattr(r, f"umbral_std_{c}"), getattr(r, f"umbral_ad_{c}")
            fmt = (lambda x: f"{_num(x)} {r.unidad}") if c == "dif_orion_abs" else (lambda x: f"{x:.1%}")
            trozos.append(f"{NOMBRE[c]} = {fmt(v)} supera el umbral estándar ({fmt(ts)}), "
                          f"pero en esta UM lo normal llega a {fmt(ta)}")
    for c in ["modula", "serie"]:
        if getattr(r, f"std_{c}") and not getattr(r, f"ad_{c}"):
            trozos.append(f"{NOMBRE[c]} salta, pero esta UM lo tiene el {getattr(r, f'frec_{c}'):.0%} de los días")
    if not trozos:
        return None
    return "La regla estándar alertaría: " + "; ".join(trozos) + "."


def explicar_fila(r) -> str:
    frases = []
    if r.nivel == "Validación automática candidata":
        frases.append("Comportamiento coherente con el patrón propio de la UM.")
        fa = falsas_alarmas_evitadas(r)
        if fa:
            frases.append(fa)
    else:
        for k in (1, 2, 3):
            if getattr(r, f"aporte_{k}") > 0:
                f = frase(getattr(r, f"var_{k}"), r)
                if f and f not in frases:
                    frases.append(f)
        if _ok(r.ramal_dif_his) and abs(r.ramal_dif_his) > 0.2 and not any("ramal" in x for x in frases):
            frases.append(frase("ramal_dif_his", r))
        if not frases:  # ninguna señal fuerte: decir qué la hace sospechosa
            for v in ("ajustes_previos_90d", "deriva_orion", "dif_orion_signo"):
                f = frase(v, r)
                if f:
                    frases.append(f)
                    break
    return " ".join(frases) if frases else "Sin señales destacables."


def recomendacion(r) -> str:
    c = r.causa_probable
    if r.nivel == "Validación automática candidata":
        return "Candidata a validar sin revisión manual (muestreo aleatorio recomendado)."
    return {
        "Fallo de comunicación / dato no recibido": "Solicitar lectura al conversor o estimar con ORION; registrar ajuste.",
        "Lectura con error en origen": "Revisar el conversor y sustituir el dato erróneo.",
        "Posible contador o conversor bloqueado": "Comprobar en campo el conversor; regularizar con ORION mientras tanto.",
        "Calidad de gas: PCS calculado ≠ cromatógrafo asignado": "Revisar la asignación de cromatógrafo y recalcular energía.",
        "Posible deriva del conversor (diferencia con ORION creciente)": "Programar contrastación del contador y corregir desde el inicio de la deriva.",
        "Salto de consumo no explicado por el ramal: posible lectura errónea": "Confirmar con el cliente/operador si hubo cambio real de consumo.",
    }.get(c, "Revisar la serie de la UM frente a ORION y su ramal.")


def aplicar(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    filas = list(df.itertuples(index=False))
    df["causa_probable"] = [causa_probable(r) for r in filas]
    filas = list(df.itertuples(index=False))
    df["explicacion"] = [explicar_fila(r) for r in filas]
    df["recomendacion"] = [recomendacion(r) for r in filas]
    return df
