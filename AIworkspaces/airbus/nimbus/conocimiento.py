"""
Conocimiento de referencia, construido A PARTIR DEL PROPIO CORPUS (vale igual para el corpus oculto):

  - Vigencias (LISTA-DOC): qué versión de cada documento está en vigor y cuáles están sustituidas.
  - Estándar STD-SEC-001 VIGENTE: sus parámetros (nombre, valor, sentido de la regla) normalizados.
  - Fórmula de nivel de riesgo (P × I y umbrales), leída del estándar.
  - Part-IS: plazos del reglamento que NO están en el estándar (nimbus/partis.py los toma del texto oficial).

Nada de esto lleva valores escritos a mano: si el corpus oculto cambia un plazo, se lee el nuevo.
"""
import re
import unicodedata
from dataclasses import dataclass, field

from nimbus.modelos import Documento

# ---------------------------------------------------------------- normalización de texto y valores
PARADAS = set("de del la las el los en y o a por para con sin tras su sus un una al".split())


def norm(t: str) -> str:
    t = unicodedata.normalize("NFD", t.lower())
    return "".join(c for c in t if unicodedata.category(c) != "Mn")


def fichas(t: str) -> set[str]:
    """Palabras de contenido, sin tildes ni plurales: 'Corrección de vulnerabilidades críticas' → {correccion, vulnerabilidad, critica}"""
    salida = set()
    for w in re.findall(r"[a-z0-9]+", norm(t)):
        if w in PARADAS or len(w) < 3:
            continue
        for suf in ("es", "s"):
            if w.endswith(suf) and len(w) > 5:
                w = w[: -len(suf)]
                break
        salida.add(w)
    return salida


UNIDADES_H = {"minuto": 1 / 60, "min": 1 / 60, "hora": 1, "h": 1, "dia": 24, "semana": 168, "mes": 730, "ano": 8760}
RE_DUR = re.compile(r"(\d+(?:[.,]\d+)?)\s*(minutos?|min|horas?|h|d[ií]as?(?:\s+laborables?)?|semanas?|meses|mes|a[ñn]os?)\b", re.I)


def duraciones_h(texto: str) -> list[tuple[float, str]]:
    """'5 días laborables' → [(168.0, '5 días laborables')]  (laborables ≈ naturales × 7/5)"""
    salida = []
    for m in RE_DUR.finditer(texto):
        n = float(m.group(1).replace(",", "."))
        u = norm(m.group(2)).split()[0].rstrip("s")
        u = {"ano": "ano", "mese": "mes", "dia": "dia"}.get(u, u)
        h = n * UNIDADES_H.get(u, UNIDADES_H.get(u.rstrip("e"), 1))
        if "laborable" in norm(m.group(2)):
            h *= 7 / 5
        salida.append((h, m.group(0)))
    return salida


def multiples(nombre: str, valor: str) -> list[tuple[str, str]]:
    """'Corrección de vulnerabilidades (crítica / alta / media)' + '30 / 90 / 180 días' → 3 parámetros."""
    m = re.search(r"\(([^)]*/[^)]*)\)", nombre)
    if not m:
        return [(nombre, valor)]
    partes = [p.strip() for p in m.group(1).split("/")]
    base = nombre[: m.start()].strip()
    nums = re.findall(r"\d+(?:[.,]\d+)?\s*(?:h\b)?", valor)
    unidad = RE_DUR.search(valor)
    if len(nums) != len(partes):
        return [(nombre, valor)]
    u = unidad.group(2) if unidad else ""
    return [(f"{base} {p}", f"{n.strip()} {u}".strip() if not n.strip().endswith("h") else n.strip()) for p, n in zip(partes, nums)]


@dataclass
class Parametro:
    nombre: str
    valor: str
    origen: str
    tabla: str
    seccion: str
    sentido: str          # max (no superar) | min (como mínimo) | periodo (al menos cada: intervalo máximo) | texto
    horas: float | None   # valor normalizado si es una duración
    numero: float | None  # otros números (caracteres, intentos, %, versión TLS)
    claves: set = field(default_factory=set)


def _sentido(nombre: str, valor: str) -> str:
    v, n = norm(valor), norm(nombre)
    if "cada" in v:
        return "periodo"
    if v.startswith("maximo") or "maxima" in v or "maximo" in v:
        return "max"
    if v.startswith("al menos") or "minim" in v or "o superior" in v:
        return "min"
    if any(k in n for k in ("conservacion", "longitud", "puntuacion", "retencion")):
        return "min"
    return "max"


def _parametro(nombre, valor, origen, tabla, seccion) -> Parametro:
    durs = duraciones_h(valor)
    num = None
    m = re.search(r"TLS\s*(\d\.\d)", valor) or re.search(r"(\d+(?:[.,]\d+)?)\s*(?:caracteres|intentos|%)", valor)
    if m:
        num = float(m.group(1).replace(",", "."))
    return Parametro(nombre, valor, origen, tabla, seccion, _sentido(nombre, valor) if (durs or num is not None) else "texto",
                     durs[0][0] if durs else None, num, fichas(nombre))


# ---------------------------------------------------------------- base de conocimiento
@dataclass
class Conocimiento:
    vigentes: dict = field(default_factory=dict)        # código → versión vigente
    sustituidas: dict = field(default_factory=dict)     # código → [versiones sustituidas]
    std: Documento | None = None
    parametros: list[Parametro] = field(default_factory=list)
    umbrales_riesgo: tuple | None = None                # (alto_desde, medio_desde)
    ids_por_prefijo: dict = field(default_factory=dict) # "C2L-SEC" → {"C2L-SEC-001", ...} (definidos en todo el corpus)
    clausula_req: dict = field(default_factory=dict)    # "C2L-SEC-025" → "IS.I.OR.210"
    avisos: list = field(default_factory=list)

    def parametro(self, nombre: str, umbral: float = 0.6) -> Parametro | None:
        """Parámetro del estándar más parecido por nombre (palabras de contenido)."""
        q = fichas(nombre)
        mejor, sim = None, 0.0
        for p in self.parametros:
            if not q or not p.claves:
                continue
            s = len(q & p.claves) / len(q | p.claves)
            if s > sim:
                mejor, sim = p, s
        if sim >= umbral:
            return mejor
        # respaldo por el VALOR: "Versión mínima de TLS" ↔ "Cifrado en tránsito = TLS 1.2 o superior"
        for marca in ("TLS", "AES"):
            if marca.lower() in norm(nombre):
                return next((p for p in self.parametros if marca in p.valor), None)
        return None

    def nivel(self, p: float, i: float) -> str | None:
        if not self.umbrales_riesgo:
            return None
        alto, medio = self.umbrales_riesgo
        v = p * i
        return "Alto" if v >= alto else "Medio" if v >= medio else "Bajo"


def construir(docs: list[Documento]) -> Conocimiento:
    k = Conocimiento()
    # 1. Vigencias según la lista maestra
    lista = next((d for d in docs if d.codigo.startswith("LISTA-DOC")), None)
    if lista:
        for t in lista.tablas:
            cab = [norm(c) for c in t.cabecera]
            if "codigo" in cab and "version" in cab and "estado" in cab:
                ic, iv, ie = cab.index("codigo"), cab.index("version"), cab.index("estado")
                for f in t.filas:
                    cod = re.sub(r"\s+", "", f[ic]); ver = f[iv].strip(); est = norm(f[ie])
                    if "vigente" in est:
                        k.vigentes[cod] = ver
                    elif "sustitu" in est:
                        k.sustituidas.setdefault(cod, []).append(ver)
    else:
        k.avisos.append("No hay LISTA-DOC: no se pueden comprobar vigencias.")

    # 2. Estándar vigente
    stds = [d for d in docs if d.codigo == "STD-SEC-001" or d.codigo.startswith("STD-SEC-001")]
    vig = k.vigentes.get("STD-SEC-001")
    k.std = next((d for d in stds if d.version == vig), None) or (max(stds, key=lambda d: d.version) if stds else None)
    if k.std:
        for t in k.std.tablas:
            cab = [norm(c) for c in t.cabecera]
            if "parametro" in cab and "valor" in cab:
                ip, iv = cab.index("parametro"), cab.index("valor")
                io = cab.index("origen") if "origen" in cab else None
                for f in t.filas:
                    for nombre, valor in multiples(f[ip], f[iv]):
                        k.parametros.append(_parametro(nombre, valor, f[io] if io is not None else "", t.numero, t.seccion))
                    if "nivel" in norm(f[ip]) and "probabilidad" in norm(f[iv]):
                        m = re.search(r"≥\s*(\d+)\s*Alto.*?(\d+)\s*[–-]\s*\d+\s*Medio", f[iv])
                        if m:
                            k.umbrales_riesgo = (float(m.group(1)), float(m.group(2)))
    else:
        k.avisos.append("No se encontró STD-SEC-001: sin parámetros corporativos.")

    # 2b. Plazos de Part-IS (el estándar dice "el fijado por el Reglamento"): se toman del texto oficial
    from nimbus import partis
    k.parametros = [p for p in k.parametros if "reglamento" not in norm(p.valor)]
    for pl in partis.plazos():
        k.parametros.append(Parametro(pl["nombre"], pl["cita"], f"Part-IS {pl['clausula']}", "Part-IS", "",
                                      pl["sentido"], pl["horas"], None, fichas(pl["nombre"])))

    # 3. Requisitos DEFINIDOS en el corpus (por las especificaciones, no los que otros documentos citan):
    #    sirven para detectar referencias rotas entre documentos y para saber la cláusula de cada requisito.
    from nimbus.detectores.comun import requisitos_de
    for d in docs:
        for r in requisitos_de(d):
            m = re.match(r"^([A-Z0-9]+(?:-[A-Z]+)*)-\d+$", r.id)
            if m:
                k.ids_por_prefijo.setdefault(m.group(1), set()).add(r.id)
            if r.clausula.startswith("IS.I.OR"):
                k.clausula_req.setdefault(r.id, r.clausula)
    return k
