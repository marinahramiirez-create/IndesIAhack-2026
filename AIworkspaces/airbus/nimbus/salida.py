"""
Salida: validación del formato oficial y escritura del CSV.

Reglas (guía del reto, §4): columnas documento,ubicacion,tipo,clausula,justificacion en ese orden, UTF-8;
tipo ∈ los cinco tipos; cláusula «IS.I.OR.2xx» o «—»; un hallazgo por fila y sin duplicados (el segundo cuenta como error).
Se añaden columnas extra al final (confianza, detector, evidencia, pagina): el puntuador las ignora.
"""
import csv
import re
from pathlib import Path

from nimbus.modelos import TIPOS, Hallazgo

COLUMNAS = ["documento", "ubicacion", "tipo", "clausula", "justificacion", "confianza", "detector", "evidencia", "pagina"]
RE_CLAU = re.compile(r"^IS\.I\.OR\.\d{3}$|^—$")
# mismos patrones de identificador que usa el puntuador oficial (para deduplicar como él empareja)
RE_ID = re.compile(r"[A-Z0-9]{2,4}-SEC-\d{3}|SEC-REQ-\d{3}|DIR-\d{2}|RSK-[A-Z0-9]+-\d{2}|RSK-\d{2}|IF-[A-Z0-9]+-\d{2}|"
                   r"RFC-\d{4}-\d{3}|VUL-\d{4}-\d{3}|KEY-\d{3}|EXC-\d{3}|NOT-\d{4}|INC-\d{2}[AB]-\d{3}|H-\d{2}-\d{2}|"
                   r"MSG-\d{2}|\bR-\d{2}\b|\bP-\d{2}\b|E-\d{4}|(?:u|adm)[\w-]*\d+|ARD-\d{4}-\d{2}|INC-\d{4}-\d{3}|MC-\d{2}")


def validar(h: Hallazgo) -> list[str]:
    errores = []
    if not h.documento.strip():
        errores.append("documento vacío")
    if not h.ubicacion.strip():
        errores.append("ubicación vacía")
    if h.tipo not in TIPOS:
        errores.append(f"tipo no válido: {h.tipo}")
    if not RE_CLAU.match(h.clausula):
        errores.append(f"cláusula con formato no válido: {h.clausula}")
    return errores


def deduplicar(hallazgos: list[Hallazgo]) -> list[Hallazgo]:
    """Un defecto, una fila: si dos hallazgos apuntan al mismo identificador del mismo documento, gana el más seguro."""
    mejor: dict = {}
    for h in sorted(hallazgos, key=lambda h: -h.confianza):
        ids = frozenset(RE_ID.findall(h.ubicacion)) or frozenset([h.ubicacion])
        clave = (h.documento, ids)
        if clave not in mejor and not any(c[0] == h.documento and c[1] & ids for c in mejor):
            mejor[clave] = h
    return sorted(mejor.values(), key=lambda h: (h.documento, h.ubicacion))


class Escritor:
    """Escribe el CSV de forma progresiva: si se agota el tiempo, lo ya escrito vale."""

    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self.f = open(self.ruta, "w", encoding="utf-8", newline="")
        self.w = csv.writer(self.f)
        self.w.writerow(COLUMNAS)
        self.n = 0

    def escribir(self, hallazgos: list[Hallazgo]):
        for h in hallazgos:
            if validar(h):
                continue
            self.w.writerow([h.documento, h.ubicacion, h.tipo, h.clausula, h.justificacion,
                             f"{h.confianza:.2f}", h.detector, h.evidencia, h.pagina])
            self.n += 1
        self.f.flush()

    def cerrar(self):
        self.f.close()


def comprobar_csv(ruta: Path) -> list[str]:
    """Comprobador de formato independiente (lista de comprobación de la guía, §12.3)."""
    errores = []
    with open(ruta, encoding="utf-8-sig") as f:
        filas = list(csv.reader(f))
    if not filas or filas[0][:5] != COLUMNAS[:5]:
        return ["cabecera incorrecta: deben ser documento,ubicacion,tipo,clausula,justificacion"]
    vistos = set()
    for n, fila in enumerate(filas[1:], 2):
        h = Hallazgo(*fila[:5])
        errores += [f"fila {n}: {e}" for e in validar(h)]
        if (h.documento, h.ubicacion) in vistos:
            errores.append(f"fila {n}: duplicada ({h.documento}, {h.ubicacion})")
        vistos.add((h.documento, h.ubicacion))
    return errores
