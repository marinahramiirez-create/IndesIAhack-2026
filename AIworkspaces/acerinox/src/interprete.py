"""
Intérprete: petición coloquial → ficha técnica (grado, acabado, espesor, formato, medidas, cantidad).

  1. Reglas (siempre): diccionario del catálogo + expresiones regulares para números en español.
     Cada valor guarda la EVIDENCIA: qué palabras del cliente lo justifican y qué sección del catálogo lo respalda.
  2. LLM (si hay): rellena solo los huecos que las reglas no entendieron. Su salida se valida contra los valores
     del catálogo: si propone un grado o acabado que no existe, se descarta (prohibido inventar).

Decide la acción:
  rechazar     pide algo que el catálogo no respalda (grado inexistente, "acero mágico"...)
  repreguntar  faltan datos imprescindibles (formato, espesor) para buscar
  buscar       se puede buscar; si faltan grado/acabado/cantidad se busca igual y se pregunta para afinar
"""
import re

from pydantic import BaseModel, Field

from src import catalogo

NUM_PALABRA = {"medio": 0.5, "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
               "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "doce": 12, "quince": 15, "veinte": 20, "treinta": 30,
               "cincuenta": 50, "cien": 100}
NUM = r"(\d+(?:[.,]\d+)?|" + "|".join(sorted(NUM_PALABRA, key=len, reverse=True)) + r")"
INDIFERENTE = re.compile(r"me da igual|cualquiera|indiferente|lo que (?:sea|tengas)|sin preferencia", re.I)


class Ficha(BaseModel):
    grados: list[str] = Field(default_factory=list, description="grados admitidos; vacío = cualquiera")
    grado_indiferente: bool = False
    acabado: str | None = None
    acabado_indiferente: bool = False
    espesor_mm: float | None = None
    formato: str | None = None
    ancho_mm: float | None = None
    largo_mm: float | None = None
    cantidad_kg: float | None = None
    piezas: int | None = None
    propiedades: list[str] = Field(default_factory=list)
    evidencias: list[dict] = Field(default_factory=list)   # {campo, valor, texto, cita}
    rechazos: list[str] = Field(default_factory=list)
    avisos: list[str] = Field(default_factory=list)

    def faltan_bloqueantes(self) -> list[str]:
        return [c for c in ["formato", "espesor_mm"] if getattr(self, c) is None]

    def faltan_para_afinar(self) -> list[str]:
        f = []
        if not self.grados and not self.grado_indiferente:
            f.append("grado")
        if self.acabado is None and not self.acabado_indiferente:
            f.append("acabado")
        if self.cantidad_kg is None and self.piezas is None:
            f.append("cantidad")
        if self.formato in ("chapa", "fleje") and self.ancho_mm is None:
            f.append("medidas")
        return f

    def accion(self) -> str:
        if self.rechazos:
            return "rechazar"
        if self.faltan_bloqueantes():
            return "repreguntar"
        return "buscar"


def _num(t: str) -> float:
    t = t.lower()
    return float(NUM_PALABRA[t]) if t in NUM_PALABRA else float(t.replace(",", "."))


def _ev(f: Ficha, campo: str, valor, texto: str, cita: str = ""):
    f.evidencias = [e for e in f.evidencias if e["campo"] != campo] + [{"campo": campo, "valor": valor, "texto": texto, "cita": cita}]


def interpretar_reglas(texto: str, f: Ficha | None = None, campo_pendiente: list[str] | None = None) -> Ficha:
    """Interpreta 'texto' y lo añade a la ficha f (conversación de varios turnos)."""
    f = f.model_copy(deep=True) if f else Ficha()
    t = " " + texto.lower() + " "

    # ---- respuesta "me da igual" a la última pregunta
    if INDIFERENTE.search(t) and campo_pendiente:
        if "grado" in campo_pendiente:
            f.grado_indiferente = True
            _ev(f, "grado", "cualquiera", INDIFERENTE.search(t).group(0))
        if "acabado" in campo_pendiente:
            f.acabado_indiferente = True
            _ev(f, "acabado", "cualquiera", INDIFERENTE.search(t).group(0))

    # ---- cosas que el catálogo no respalda
    for patron, motivo in catalogo.NO_RESPALDADO:
        m = re.search(patron, t)
        if m:
            f.rechazos.append(f"«{m.group(0).strip()}»: {motivo}.")
    for m in re.finditer(r"\b(?:aisi|acero|inox|grado|calidad|de)?\s*\b(\d{3}(?!mm|kg|cm)[a-z]{1,2})\b", t):
        g = m.group(1).upper()
        if not any(re.search(p, g.lower()) for pats, _ in catalogo.GRADOS.values() for p in pats):
            f.rechazos.append(f"«{g}»: ese grado no está en el catálogo (grados disponibles: {', '.join(catalogo.GRADOS)}).")

    # ---- grado explícito
    explicitos = [g for g, (pats, _) in catalogo.GRADOS.items() if any(re.search(p, t) for p in pats)]
    if explicitos:
        f.grados = explicitos
        f.grado_indiferente = False
        for g in explicitos:
            m = next(re.search(p, t) for p in catalogo.GRADOS[g][0] if re.search(p, t))
            _ev(f, "grado", g, m.group(0).strip(), catalogo.cita(catalogo.GRADOS[g][1]))

    # ---- propiedades de uso → grados candidatos
    for patron, grados, nombre, sec in catalogo.PROPIEDADES:
        m = re.search(patron, t)
        if not m:
            continue
        f.propiedades.append(nombre)
        if explicitos:
            fuera = [g for g in explicitos if g not in grados]
            if fuera:
                f.avisos.append(f"Ha pedido {', '.join(fuera)} pero para «{nombre}» el catálogo recomienda "
                                f"{', '.join(grados)} ({catalogo.cita(sec)}).")
        else:
            f.grados = [g for g in grados if g in f.grados] or grados if f.grados else grados
            _ev(f, "grado", " o ".join(f.grados), m.group(0), f"{catalogo.cita(sec)} ({nombre})")

    # ---- acabado y formato
    for campo, tabla in [("acabado", catalogo.ACABADOS), ("formato", catalogo.FORMATOS)]:
        for valor, (pats, sec) in tabla.items():
            m = next((re.search(p, t) for p in pats if re.search(p, t)), None)
            if m:
                setattr(f, campo, valor)
                _ev(f, campo, valor, m.group(0).strip(), catalogo.cita(sec))
                break

    # ---- medidas: 1250x2500 / 1250 por 2500
    m = re.search(r"(\d{3,4})\s*(?:x|×|\*|por)\s*(\d{3,5})", t)
    if m:
        f.ancho_mm, f.largo_mm = float(m.group(1)), float(m.group(2))
        _ev(f, "medidas", f"{m.group(1)} x {m.group(2)} mm", m.group(0))
    m = re.search(r"(\d{2,4})\s*(?:mm|mil[ií]metros)?\s*de ancho|ancho (?:de )?(\d{2,4})", t)
    if m:
        f.ancho_mm = float(m.group(1) or m.group(2))
        _ev(f, "ancho", f"{f.ancho_mm:.0f} mm", m.group(0))
    m = re.search(r"(\d{3,5})\s*(?:mm)?\s*de largo|largo (?:de )?(\d{3,5})", t)
    if m:
        f.largo_mm = float(m.group(1) or m.group(2))
        _ev(f, "largo", f"{f.largo_mm:.0f} mm", m.group(0))

    # ---- espesor: "2 mm", "dos milímetros", "de 0,8"
    for m in re.finditer(NUM + r"\s*(?:mm|mil[ií]metros?)\b(?!\s*de (?:ancho|largo))", t):
        v = _num(m.group(1))
        if v <= 20:
            f.espesor_mm = v
            _ev(f, "espesor", f"{v} mm", m.group(0).strip(), catalogo.cita("4"))
            break
    if f.espesor_mm is None:
        m = re.search(r"\b(?:de|en|a)\s+(\d+[.,]\d+|\d)\b(?!\s*(?:x|por|mm de|tonel|kg|kilo|chapa|hoja|pieza|unidad))", t)
        if m and _num(m.group(1)) <= 10:
            f.espesor_mm = _num(m.group(1))
            _ev(f, "espesor", f"{f.espesor_mm} mm", m.group(0).strip(), catalogo.cita("4"))
    if f.espesor_mm is not None and f.espesor_mm not in catalogo.ESPESORES_CATALOGO:
        f.avisos.append(f"El espesor {f.espesor_mm} mm no está en la gama del catálogo "
                        f"({', '.join(str(e) for e in catalogo.ESPESORES_CATALOGO)} mm).")

    # ---- cantidad: toneladas, kg, piezas ("una chapa" no es cantidad: es el producto)
    m = re.search(NUM + r"\s*(?:toneladas?|tn|t)\b", t)
    if m and m.group(1) not in ("un", "una"):
        f.cantidad_kg = _num(m.group(1)) * 1000
        _ev(f, "cantidad", f"{f.cantidad_kg:.0f} kg", m.group(0).strip())
    m = re.search(NUM + r"\s*(?:kg|kilos?|kilogramos?)\b", t)
    if m:
        f.cantidad_kg = _num(m.group(1))
        _ev(f, "cantidad", f"{f.cantidad_kg:.0f} kg", m.group(0).strip())
    m = re.search(NUM + r"\s*(?:chapas|hojas|piezas|unidades|planchas|placas)\b", t)
    if m and m.group(1) not in ("un", "una", "uno"):
        f.piezas = int(_num(m.group(1)))
        _ev(f, "cantidad", f"{f.piezas} hojas", m.group(0).strip())

    f.rechazos = list(dict.fromkeys(f.rechazos))
    f.avisos = list(dict.fromkeys(f.avisos))
    return f


def interpretar(texto: str, f: Ficha | None = None, campo_pendiente: list[str] | None = None) -> Ficha:
    """Reglas + (opcional) LLM para los huecos."""
    ficha = interpretar_reglas(texto, f, campo_pendiente)
    from src import llm
    if llm.disponible() and (ficha.faltan_bloqueantes() or ficha.faltan_para_afinar()):
        ficha = llm.completar_ficha(texto, ficha)
    return ficha
