"""
Esquemas de datos entre capas. Cambiar un parser, un modelo o un índice no obliga a tocar el resto
mientras se respeten estos contratos.
"""
from dataclasses import asdict, dataclass, field

TIPOS = ("No cumple", "Inconsistencia", "Cobertura faltante", "Trazabilidad incorrecta", "No verificable")


@dataclass
class Seccion:
    numero: str                     # "5.4"
    titulo: str                     # "Control de accesos"
    clausulas: list[str]            # cláusulas citadas en el título: ["IS.I.OR.210"]
    pagina: int


@dataclass
class Requisito:
    id: str                         # "C2L-SEC-025"
    texto: str                      # enunciado completo
    tipo: str                       # "Tratamiento" (campo Tipo:)
    clausula: str                   # "IS.I.OR.210" (cláusula que declara el propio requisito)
    verificacion: str               # "Prueba técnica" / "—"
    seccion: str                    # "6.4"
    pagina: int


@dataclass
class Tabla:
    numero: str                     # "5"
    titulo: str                     # "Parámetros de seguridad del subsistema."
    seccion: str                    # "4"
    pagina: int
    cabecera: list[str]
    filas: list[list[str]]          # celdas por columna (reconstruidas por coordenadas)


@dataclass
class Figura:
    numero: str
    titulo: str
    seccion: str
    pagina: int
    bbox: tuple                     # recorte en la página (x0, top, x1, bottom) para enviarlo a visión


@dataclass
class Documento:
    archivo: str
    codigo: str                     # "SRS-SEC-C2L" (tal cual en la portada: una errata = 0 aciertos)
    version: str
    familia: str                    # carpeta: "01_especificaciones"
    paginas: int
    escaneado: bool                 # sin texto digital → necesita visión/OCR
    texto: str = ""
    secciones: list[Seccion] = field(default_factory=list)
    requisitos: list[Requisito] = field(default_factory=list)
    tablas: list[Tabla] = field(default_factory=list)
    figuras: list[Figura] = field(default_factory=list)
    ids_definidos: list[str] = field(default_factory=list)   # todos los IDs que aparecen como fila/requisito
    errores: list[str] = field(default_factory=list)

    def dict(self):
        return asdict(self)


@dataclass
class Hallazgo:
    documento: str
    ubicacion: str
    tipo: str
    clausula: str
    justificacion: str
    # columnas extra (el puntuador las ignora; ayudan al jurado y a la app)
    confianza: float = 0.8
    detector: str = ""
    evidencia: str = ""             # cita literal del PDF
    pagina: int = 0

    def clave(self):
        """Para no repetir el mismo defecto en dos filas (el segundo cuenta como error)."""
        return (self.documento, self.ubicacion)
