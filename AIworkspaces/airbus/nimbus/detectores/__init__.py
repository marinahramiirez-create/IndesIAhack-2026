"""
Detectores: reglas GENÉRICAS que proponen hallazgos. Ninguna está escrita para un documento concreto:
se activan por la forma del contenido (una tabla con columnas Parámetro/Valor, un requisito con «debería»,
un registro de riesgos con P, I y Nivel…), así que funcionan igual en el corpus oculto.

Cada detector recibe (documento, conocimiento) y devuelve una lista de Hallazgo con su evidencia literal.
"""
import traceback

from nimbus.detectores import parametros, prosa, riesgos, trazabilidad, verificacion

TODOS = [
    prosa.recomendacion,
    prosa.no_verificable,
    trazabilidad.referencias_rotas,
    trazabilidad.ids_duplicados,
    trazabilidad.clausula_incoherente,
    trazabilidad.version_sustituida,
    parametros.tablas_de_parametros,
    parametros.requisitos_frente_al_estandar,
    riesgos.registros_de_riesgos,
    verificacion.sin_verificacion,
    verificacion.cobertura_de_verificacion,
]


def ejecutar(doc, k) -> tuple[list, list[str]]:
    """Ejecuta todos los detectores; si uno falla, se registra y se sigue con los demás."""
    hallazgos, errores = [], []
    for det in TODOS:
        try:
            hallazgos += det(doc, k)
        except Exception as e:
            errores.append(f"{doc.codigo} · {det.__module__.split('.')[-1]}.{det.__name__}: {e}\n{traceback.format_exc(limit=2)}")
    return hallazgos, errores
