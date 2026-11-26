"""Esquema de un hallazgo (= una fila de respuestas.csv) y validación del formato oficial (guía §4)."""
import re
from dataclasses import asdict, dataclass

TIPOS = ("No cumple", "Inconsistencia", "Cobertura faltante", "Trazabilidad incorrecta", "No verificable")
COLUMNAS = ["documento", "ubicacion", "tipo", "clausula", "justificacion"]
# columnas extra al final: el puntuador las ignora, ayudan al jurado y a la app
EXTRA = ["confianza", "origen", "evidencia", "pagina"]
PATRON_CLAUSULA_OK = re.compile(r"^IS\.I\.OR\.2\d\d$")


@dataclass
class Hallazgo:
    documento: str
    ubicacion: str
    tipo: str
    clausula: str
    justificacion: str
    evidencia: str = ""        # cita literal del documento que lo demuestra
    origen: str = ""           # regla Rn / llm / vision
    confianza: float = 0.5
    pagina: int | None = None
    fuente: str = ""            # fuente de mayor rango con la que se compara
    calculo: object = None      # fechas y máximo para verificar plazos con código
    descarte: str = ""          # si el verificador lo descarta, por qué (traza / explicabilidad)

    def fila(self) -> dict:
        return {k: v for k, v in asdict(self).items() if k in COLUMNAS + EXTRA}


def errores_formato(h: Hallazgo) -> list[str]:
    e = []
    if not h.documento:
        e.append("documento vacío")
    if not h.ubicacion or len(h.ubicacion) > 80:
        e.append("ubicación vacía o demasiado larga (debe ser un identificador)")
    if h.tipo not in TIPOS:
        e.append(f"tipo no válido: {h.tipo!r}")
    if h.clausula != "—" and not PATRON_CLAUSULA_OK.match(h.clausula):
        e.append(f"cláusula con formato incorrecto: {h.clausula!r}")
    if not h.justificacion:
        e.append("sin justificación")
    return e
