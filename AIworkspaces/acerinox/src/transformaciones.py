"""
Reglas de transformación (reglas_transformacion.txt) escritas como código.

Cada operación lleva el código de la regla (R1...R6) para poder citarla. Lo que no está aquí NO se puede proponer:
no se cambia el grado ni el espesor, no se fabrican acabados de fábrica (BA, 2B, 2D, 1D) y no se aumentan medidas.

El día del reto: leer el TXT real y ajustar las constantes y funciones de este archivo (es corto a propósito).
"""
import math

REFILADO_MM = 10
ANCHO_MIN_TIRA = 20
ANCHO_MAX_FLEJE = 600
LARGO_MIN, LARGO_MAX = 500, 6000
MERMA_CORTE_TRANSVERSAL = 0.01
SATINADO_DESDE = {"2B", "BA"}
SATINADO_ESPESOR_MIN = 0.5
ESPEJO_DESDE = {"BA"}
ESPEJO_ESPESOR_MAX = 3.0

REGLAS = {
    "R1": "Corte longitudinal",
    "R2": "Corte transversal (bobina → chapa)",
    "R3": "Cizalla (chapa a medida menor)",
    "R4": "Satinado",
    "R5": "Pulido espejo",
    "R6": "Film protector",
}


def op(regla: str, detalle: str) -> dict:
    return {"regla": regla, "operacion": REGLAS[regla], "detalle": detalle}


def acabado(b: dict, objetivo: str | None) -> tuple[list[dict] | None, str]:
    """Operaciones para pasar del acabado del bulto al pedido. None = imposible (con motivo)."""
    if objetivo is None or b["acabado"] == objetivo:
        return [], ""
    if objetivo == "satinado":
        if b["acabado"] in SATINADO_DESDE and b["espesor_mm"] >= SATINADO_ESPESOR_MIN:
            return [op("R4", f"satinar desde {b['acabado']}")], ""
        return None, f"satinado solo desde {'/'.join(sorted(SATINADO_DESDE))} (R4)"
    if objetivo == "espejo":
        if b["acabado"] in ESPEJO_DESDE and b["espesor_mm"] <= ESPEJO_ESPESOR_MAX:
            return [op("R5", "pulido espejo desde BA")], ""
        return None, "espejo solo desde BA y ≤ 3 mm (R5)"
    return None, f"el acabado {objetivo} es de fábrica: no se obtiene en almacén desde {b['acabado']}"


def formato_y_medidas(b: dict, formato: str, ancho: float | None, largo: float | None) -> tuple[list[dict] | None, float, int, str]:
    """
    Operaciones de corte para pasar del bulto al formato/medidas pedidos.
    Devuelve (operaciones | None si imposible, merma 0-1, piezas por hoja o tiras, motivo si imposible).
    """
    bf, ba, bl = b["formato"], b["ancho_mm"], b.get("largo_mm")

    if formato == "chapa":
        if bf == "chapa":
            if ancho is None and largo is None:
                return [], 0.0, 1, ""
            a, l = ancho or ba, largo or bl
            if a > ba or l > bl:
                return None, 0, 0, f"medidas {a:.0f}x{l:.0f} mayores que la chapa {ba:.0f}x{bl:.0f} (no se puede aumentar)"
            if a == ba and l == bl:
                return [], 0.0, 1, ""
            k = max(math.floor(ba / a) * math.floor(bl / l), math.floor(ba / l) * math.floor(bl / a))
            merma = 1 - k * a * l / (ba * bl)
            return [op("R3", f"cizallar {ba:.0f}x{bl:.0f} → {k} piezas de {a:.0f}x{l:.0f} por hoja")], merma, k, ""
        if bf == "bobina":
            if largo is None:
                return None, 0, 0, "para cortar chapa de una bobina hace falta el largo"
            if not LARGO_MIN <= largo <= LARGO_MAX:
                return None, 0, 0, f"largo fuera de {LARGO_MIN}-{LARGO_MAX} mm (R2)"
            a = ancho or ba
            if a > ba:
                return None, 0, 0, f"ancho {a:.0f} mayor que la bobina {ba:.0f}"
            ops, merma = [], MERMA_CORTE_TRANSVERSAL
            if a < ba:
                n = math.floor((ba - REFILADO_MM) / a)
                if n < 1:
                    return None, 0, 0, f"no cabe una tira de {a:.0f} mm tras el refilado (R1)"
                merma = 1 - n * a / ba + MERMA_CORTE_TRANSVERSAL
                ops.append(op("R1", f"cortar a {n} tiras de {a:.0f} mm"))
            ops.append(op("R2", f"cortar a chapas de {largo:.0f} mm de largo"))
            return ops, merma, 1, ""
        return None, 0, 0, "de un fleje no se obtiene chapa del ancho pedido"

    if formato in ("bobina", "fleje"):
        if bf == "chapa":
            return None, 0, 0, "una chapa no se puede convertir en bobina o fleje"
        if formato == "bobina" and bf == "fleje":
            return None, 0, 0, "un fleje es más estrecho que una bobina"
        if formato == "fleje" and ancho is None:
            return None, 0, 0, "para un fleje hace falta el ancho"
        if formato == "fleje" and bf == "bobina" and ancho >= ANCHO_MAX_FLEJE:
            return None, 0, 0, f"un fleje tiene menos de {ANCHO_MAX_FLEJE} mm de ancho"
        if ancho is None or ancho == ba:
            return [], 0.0, 1, ""
        if ancho > ba:
            return None, 0, 0, f"ancho {ancho:.0f} mayor que el bulto {ba:.0f} (no se puede aumentar)"
        if ancho < ANCHO_MIN_TIRA:
            return None, 0, 0, f"ancho mínimo de tira {ANCHO_MIN_TIRA} mm (R1)"
        n = math.floor((ba - REFILADO_MM) / ancho)
        if n < 1:
            return None, 0, 0, f"no cabe una tira de {ancho:.0f} mm tras el refilado (R1)"
        merma = 1 - n * ancho / ba
        return [op("R1", f"cortar {ba:.0f} mm → {n} tiras de {ancho:.0f} mm (refilado {REFILADO_MM} mm)")], merma, n, ""

    return None, 0, 0, f"formato desconocido: {formato}"
