"""
Explicaciones para personas no técnicas.

Por defecto se generan con PLANTILLAS (deterministas, sin LLM): cada número sale de la tabla de alertas.
Opcionalmente, src/llm.py puede reescribirlas en lenguaje más natural, pero sin poder añadir cifras.
"""
import pandas as pd


def _eur(x) -> str:
    return f"{x:,.0f} €".replace(",", ".")


def _pct(x) -> str:
    return f"{x:+.0f} %"


def origen_desviacion(a) -> str:
    vt, vm = a.get("var_tickets_pct"), a.get("var_ticket_medio_pct")
    if pd.isna(vt) or pd.isna(vm):
        return ""
    if abs(vt) >= 2 * abs(vm):
        return f"Viene sobre todo del número de tickets ({_pct(vt)}); el ticket medio apenas cambia ({_pct(vm)})."
    if abs(vm) >= 2 * abs(vt):
        return f"Viene sobre todo del ticket medio ({_pct(vm)}); el número de tickets es normal ({_pct(vt)})."
    return f"Cambian a la vez los tickets ({_pct(vt)}) y el ticket medio ({_pct(vm)})."


def recomendacion(a) -> str:
    sube = a["desviacion_pct"] > 0
    if a["tipo"] == "tendencia":
        if sube:
            return "Identificar qué ha cambiado (nueva apertura cercana cerrada, obra terminada, mejora operativa) para replicarlo."
        return ("Revisar con el gerente de zona: competencia nueva, obras, cambios de personal u horario. "
                "Si es en delivery, revisar posicionamiento y tiempos en las plataformas.")
    vt, vm = a.get("var_tickets_pct", 0), a.get("var_ticket_medio_pct", 0)
    if not sube and a["canal"] == "delivery":
        return "Comprobar si el restaurante estuvo desconectado de las plataformas de delivery (tablet, cierre temporal)."
    if not sube and abs(vm) > abs(vt):
        return "Revisar precios y promociones en caja ese día: posible precio mal configurado o descuento aplicado por error."
    if not sube:
        return "Confirmar con el restaurante si hubo cierre parcial, avería (TPV, freidora, datáfono) o falta de personal."
    if abs(vm) > abs(vt):
        return "Revisar tickets de importe anormalmente alto: posible error de cobro o pedido de grupo grande."
    return "Verificar si hubo un evento local no registrado en el calendario o tickets duplicados."


def explicacion_plantilla(a) -> str:
    fecha = pd.Timestamp(a["fecha"]).strftime("%d/%m/%Y")
    nombre = f"{a['restaurante_id']} ({a['marca']}, {a['zona']})"
    if a["tipo"] == "tendencia":
        texto = (f"Desde la semana del {fecha}, las ventas de {a['canal']} en {nombre} están en un nivel "
                 f"{_pct(a['desviacion_pct'])} distinto al anterior, mientras que restaurantes similares no cambian. "
                 f"Dura ya {a['semanas']} semanas, con un impacto acumulado de {_eur(a['impacto_eur'])}.")
    else:
        texto = (f"El {fecha}, las ventas de {a['canal']} en {nombre} fueron {_eur(a['real'])} frente a "
                 f"{_eur(a['esperado'])} esperados ({_pct(a['desviacion_pct'])}). {origen_desviacion(a)}")
        if isinstance(a.get("contexto"), str) and a["contexto"]:
            texto += (f" Ese día había {a['contexto']}, pero eso ya está descontado: los restaurantes "
                      f"comparables no se comportaron así.")
        else:
            texto += " Los restaurantes comparables (misma marca, tipología y zona) no muestran lo mismo, así que es algo propio de este local."
    return texto


def hechos(a) -> dict:
    """Los datos (ya calculados) que se le pasan al LLM. No puede usar ningún otro número."""
    claves = ["tipo", "restaurante_id", "marca", "zona", "canal", "real", "esperado", "desviacion_pct",
              "impacto_eur", "semanas", "var_tickets_pct", "var_ticket_medio_pct", "contexto"]
    d = {k: (None if pd.isna(a.get(k)) else a.get(k)) for k in claves if k in a}
    d["fecha"] = pd.Timestamp(a["fecha"]).strftime("%d/%m/%Y")
    d["recomendacion_base"] = recomendacion(a)
    return d
