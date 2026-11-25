"""
Asistente conversacional: une intérprete → (repregunta) → inventario → validador → respuesta.

La conversación guarda la ficha entre turnos: si el cliente dice "chapa de 316L" y luego "de 2 mm",
el segundo mensaje completa la ficha del primero.
"""
from src import catalogo, db, inventario, llm
from src.interprete import Ficha, interpretar

PREGUNTAS = {
    "formato": "¿La quiere en **chapa, bobina o fleje**?",
    "espesor_mm": "¿Qué **espesor**? En catálogo: " + ", ".join(f"{e:g}".replace(".", ",") for e in catalogo.ESPESORES_CATALOGO) + " mm.",
    "grado": "¿Qué **grado** (304, 304L, 316L, 430, 441, 2205) o **para qué uso** es (exterior/marino, alta temperatura, alimentario…)?",
    "acabado": "¿Qué **acabado**: 2B (estándar, semibrillante), BA (brillante), 2D (mate), 1D (laminado en caliente), satinado o espejo?",
    "cantidad": "¿Qué **cantidad** (kg/toneladas o nº de hojas)?",
    "medidas": "¿Qué **medidas** (ancho x largo en mm; para fleje, el ancho)?",
}


def _fmt(n) -> str:
    return f"{n:g}".replace(".", ",")


def resumen_ficha(f: Ficha) -> str:
    partes = [f.formato or "¿formato?",
              " o ".join(f.grados) if f.grados else ("cualquier grado" if f.grado_indiferente else "¿grado?"),
              f.acabado or ("cualquier acabado" if f.acabado_indiferente else "¿acabado?"),
              f"{_fmt(f.espesor_mm)} mm" if f.espesor_mm else "¿espesor?"]
    if f.ancho_mm:
        partes.append(f"{f.ancho_mm:.0f}" + (f" x {f.largo_mm:.0f}" if f.largo_mm else "") + " mm")
    if f.piezas:
        partes.append(f"{f.piezas} hojas")
    if f.cantidad_kg:
        partes.append(f"{f.cantidad_kg:,.0f} kg".replace(",", "."))
    return " · ".join(partes)


def _bulto_txt(p: dict) -> str:
    medidas = f"{p['ancho_mm']:.0f}x{p['largo_mm']:.0f}" if p["formato"] == "chapa" else f"{p['ancho_mm']:.0f} mm"
    extra = f"{int(p['n_hojas'])} hojas" if p["formato"] == "chapa" else f"{p['peso_kg']:,.0f} kg".replace(",", ".")
    return f"**{p['id_bulto']}** · {p['formato']} {p['grado']} {p['acabado']} {_fmt(p['espesor_mm'])} mm · {medidas} · {extra} · {p['almacen']}"


class Conversacion:
    def __init__(self):
        self.ficha: Ficha | None = None
        self.pendiente: list[str] = []
        self.ultima_busqueda_completa = False

    def nueva(self):
        self.__init__()

    def responder(self, texto: str) -> dict:
        # Si ya se resolvió una petición y llega otra con un producto DISTINTO → ficha nueva.
        # Si solo añade detalles ("10 chapas de 1250x2500", "brillante") → se afina la misma petición.
        if self.ultima_busqueda_completa and self.ficha:
            prueba, actual = interpretar(texto), self.ficha
            distinto = (prueba.rechazos
                        or (prueba.grados and set(prueba.grados) != set(actual.grados))
                        or (prueba.espesor_mm and prueba.espesor_mm != actual.espesor_mm)
                        or (prueba.formato and prueba.formato != actual.formato))
            if distinto:
                self.ficha = None
        self.ultima_busqueda_completa = False   # se vuelve a activar solo si este turno termina en búsqueda
        f = interpretar(texto, self.ficha, self.pendiente)
        self.ficha = f
        accion = f.accion()
        salida = {"accion": accion, "ficha": f, "busqueda": None, "errores_validacion": [], "preguntas": []}
        lineas = [f"🔎 **He entendido:** {resumen_ficha(f)}"]
        for a in f.avisos:
            lineas.append(f"⚠️ {a}")

        if accion == "rechazar":
            lineas.append("🚫 **No puedo ofrecer eso, no está respaldado por el catálogo:**")
            lineas += [f"- {r}" for r in f.rechazos]
            lineas.append(f"Grados disponibles: {', '.join(catalogo.GRADOS)}. Acabados: {', '.join(catalogo.ACABADOS)}.")
            self.ficha.rechazos = []     # el siguiente mensaje puede corregir la petición
            self.pendiente = ["grado"]
            salida["preguntas"] = [PREGUNTAS["grado"]]
            resultado, bulto = "—", ""
        elif accion == "repreguntar":
            self.pendiente = [c for c in f.faltan_bloqueantes()]
            preguntas = [PREGUNTAS[c] for c in self.pendiente][:2]
            lineas.append("Para buscar en el stock me falta:")
            lineas += [f"- {q}" for q in preguntas]
            salida["preguntas"] = preguntas
            resultado, bulto = "—", ""
        else:
            r = inventario.buscar(f)
            salida["busqueda"] = r
            salida["errores_validacion"] = inventario.validar(r["propuestas"], f)
            if salida["errores_validacion"]:   # nunca se enseña una propuesta que no pase el validador
                malos = {e.split(":")[0] for e in salida["errores_validacion"]}
                r["propuestas"] = [p for p in r["propuestas"] if p["id_bulto"] not in malos]
            if r["propuestas"]:
                mejor = r["propuestas"][0]
                lineas.append(f"✅ Hay {r['n_encajan']} bulto(s) que encajan. **Mejor propuesta:**")
                for i, p in enumerate(r["propuestas"], 1):
                    lineas.append(f"{i}. {_bulto_txt(p)} — **{p['encaje']}** ({p['motivo_ranking']})")
                    for o in p["operaciones"]:
                        lineas.append(f"   - {o['regla']} {o['operacion']}: {o['detalle']}")
                    if p["detalle_cantidad"]:
                        lineas.append(f"   - Cantidad: {p['detalle_cantidad']}")
                resultado, bulto = mejor["encaje"], mejor["id_bulto"]
            else:
                lineas.append("❌ **No hay ningún bulto disponible** que encaje, ni transformándolo con las reglas.")
                if r["no_disponibles"]:
                    lineas.append("Encajarían pero no están disponibles: "
                                  + ", ".join(f"{x['id_bulto']} ({x['estado']})" for x in r["no_disponibles"]))
                motivos = list(dict.fromkeys(d["motivo"] for d in r["descartados"]))[:3]
                if motivos:
                    lineas.append("Motivos de descarte: " + "; ".join(motivos) + ".")
                lineas.append("📝 Queda registrado como **demanda no atendida**.")
                resultado, bulto = "sin_stock", ""
            afinar = f.faltan_para_afinar()
            self.pendiente = afinar
            if afinar and r["propuestas"]:
                salida["preguntas"] = [PREGUNTAS[c] for c in afinar][:2]
                lineas.append("Para afinar la propuesta: " + " ".join(salida["preguntas"]))
            self.ultima_busqueda_completa = True

        respuesta = "\n".join(lineas)
        ids = [p["id_bulto"] for p in (salida["busqueda"] or {}).get("propuestas", [])]
        salida["respuesta"] = respuesta
        salida["respuesta_natural"] = llm.redactar(respuesta, ids) if llm.disponible() else None
        try:
            db.registrar_peticion(texto, f.model_dump(), accion, resultado, bulto)
        except Exception:
            pass
        return salida
