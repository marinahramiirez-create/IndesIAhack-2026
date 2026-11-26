"""
Agente auditor (LLM): lee UN documento + las referencias + los documentos que cita, y propone hallazgos
con evidencia literal. No decide solo: cada propuesta pasa después por src/verificar.py (código).
Prompts en este módulo, con nombre y propósito (guía §10.2).
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from src import llm
from src.ingesta import Documento
from src.modelo import Hallazgo

TipoDefecto = Literal["No cumple", "Inconsistencia", "Cobertura faltante", "Trazabilidad incorrecta", "No verificable"]


class Calculo(BaseModel):
    """Para defectos de plazo: el CÓDIGO calcula los días; el modelo solo copia las fechas y el máximo."""
    desde: str = Field(description="fecha inicial tal como aparece, AAAA-MM-DD (opcional HH:MM)")
    hasta: str = Field(description="fecha final o fecha de corte, AAAA-MM-DD (opcional HH:MM)")
    maximo_dias: float = Field(description="plazo máximo permitido en días (24 horas = 1)")

    @model_validator(mode="before")
    @classmethod
    def _sinonimos(cls, v):
        """El modelo a veces usa otros nombres de campo: se aceptan los equivalentes."""
        if isinstance(v, dict):
            alias = {"desde": ("fecha_inicio", "inicio", "fecha_desde", "fecha1"),
                     "hasta": ("fecha_fin", "fin", "fecha_corte", "fecha_hasta", "fecha2"),
                     "maximo_dias": ("max_dias", "maximo", "limite_dias", "plazo_max_dias")}
            for k, otros in alias.items():
                if k not in v:
                    v[k] = next((v[o] for o in otros if o in v), None)
        return v


class Propuesta(BaseModel):
    ubicacion: str
    tipo: TipoDefecto
    clausula: str
    justificacion: str
    evidencia: str = Field(description="cita LITERAL copiada del documento auditado que demuestra el defecto")
    fuente: str = Field(description="fuente de mayor rango contra la que se compara (p. ej. 'STD-SEC-001 Tabla 1')")
    confianza: float = Field(ge=0, le=1)
    calculo: Optional[Calculo] = None

    @field_validator("calculo", mode="before")
    @classmethod
    def _calculo_tolerante(cls, v):
        try:
            return Calculo.model_validate(v) if v else None
        except ValidationError:
            return None     # sin cálculo válido: el hallazgo sigue, pero sin la comprobación de plazo


class Respuesta(BaseModel):
    """Cada propuesta se valida por separado: una mal formada se descarta sin perder las demás."""
    hallazgos: list[dict]

    def propuestas(self) -> tuple[list[Propuesta], int]:
        ok, malas = [], 0
        for h in self.hallazgos:
            try:
                ok.append(Propuesta.model_validate(h))
            except ValidationError:
                malas += 1
        return ok, malas


SISTEMA = """Eres un auditor experto en Part-IS (EASA) que revisa la documentación del ISMS de NIMBUS Aerospace,
un operador ficticio de drones. Tu trabajo: encontrar los DEFECTOS REALES de un documento, con evidencia.

JERARQUÍA (cuando dos fuentes discrepan, manda la de mayor rango):
1. Part-IS (texto del reglamento, abajo). Sus plazos legales (p. ej. notificación a la autoridad, conservación
   de registros) no se repiten en los documentos internos: tómalos del reglamento.
2. STD-SEC-001 vigente (abajo): valores numéricos corporativos y criterios de control operativo. No tiene defectos.
3. LISTA-DOC: qué documentos y versiones están en vigor. Un documento sustituido NO es referencia.
4. Políticas, manual, procedimientos, especificaciones: deben respetar lo anterior.
5. Registros, informes, declaraciones, actas: demuestran si lo anterior se cumple en la práctica.

TIPOS DE DEFECTO (usa exactamente uno):
- "No cumple": un valor u obligación incumple el estándar o la norma (plazo de 45 días donde el estándar exige 7;
  control obligatorio redactado como recomendación; fila de registro que viola un criterio de control operativo;
  respuesta de un proveedor que incumple un requisito obligatorio).
- "Inconsistencia": dos partes dicen cosas incompatibles (texto vs tabla, vs diagrama, vs otro documento,
  requisito vs requisito, resumen vs detalle, nivel de riesgo mal calculado).
- "Cobertura faltante": la norma o el estándar exigen algo que el documento no cubre (p. ej. se cubre detección y
  respuesta pero no recuperación; falta revisión periódica; un requisito obligatorio no se verifica).
- "Trazabilidad incorrecta": referencia a un ID que no existe, cláusula de Part-IS mal asignada a un requisito,
  identificador duplicado, elemento que remite a algo que no figura.
- "No verificable": requisito tan vago que no se puede comprobar, o resultado «conforme» sin evidencia.

CUIDADO, NO SON DEFECTOS:
- Un documento MÁS exigente que el estándar es conforme (24 h donde se exige ≤ 72 h está bien).
- Lo descriptivo o informativo (contexto, alcance, definiciones) no es un requisito.
- Cada hallazgo de más penaliza: reporta solo lo que puedas demostrar con una cita literal y una fuente.
- Si el documento no tiene defectos, devuelve una lista vacía.

CLÁUSULA: el punto de Part-IS que se vulnera, con tres dígitos y sin apartados: "IS.I.OR.210" (no "210", no
"IS.I.OR.210(a)"). Usa la del tema real del defecto (accesos, cifrado, vulnerabilidades, copias y tratamiento
técnico → IS.I.OR.210; evaluación de riesgos → .205; incidentes detección/respuesta/recuperación → .220;
notificación a la autoridad → .230; proveedores/subcontratación → .235; personal, formación, competencia → .240;
conservación de registros → .245; cambios en el ISMS → .255; auditorías, revisión, acciones correctivas → .260).
Solo si el defecto es una referencia rota a un ID inexistente y no hay punto aplicable, usa "—".

UBICACIÓN: el identificador LITERAL más preciso que exista en el documento: ID de requisito (C2L-SEC-025),
ID de fila de registro (VUL-2026-012, E-1087, cuenta u1087, KEY-014, RFC-2026-089, H-01-07, R-17, P-07, MSG-07),
directriz (DIR-05). Si compara dos sitios: "A ↔ B". Solo si no hay ID: "Tabla N", "Figura N" o "§N".
Nunca una descripción ("el requisito cuatro" no vale). Un defecto = un hallazgo; no repitas el mismo defecto.

PLAZOS Y FECHAS: no hagas tú la cuenta. Si el defecto depende de un plazo entre dos fechas (revocación tras una
baja, corrección de una vulnerabilidad, renovación de formación, rotación de claves, prueba de restauración,
fecha límite vencida en la fecha de corte...), rellena "calculo" con las dos fechas copiadas tal cual y el
máximo permitido en días; el sistema hará la cuenta y descartará el hallazgo si el plazo se cumple.

Responde SOLO con JSON:
{"hallazgos": [{"ubicacion": "...", "tipo": "...", "clausula": "IS.I.OR.2xx", "justificacion": "una frase: qué
dice el documento, qué exige la fuente y cuál es", "evidencia": "cita literal exacta del documento auditado",
"fuente": "...", "confianza": 0.0-1.0, "calculo": null}]}
Si hay plazo, "calculo" es exactamente: {"desde": "AAAA-MM-DD HH:MM", "hasta": "AAAA-MM-DD HH:MM", "maximo_dias": N}

=== REFERENCIAS ===
"""


def auditar(doc: Documento, referencias: str, relacionados: list[Documento]) -> tuple[list[Hallazgo], object]:
    partes = [f"DOCUMENTO A AUDITAR: {doc.codigo} v{doc.version} — {doc.titulo}\n"
              f"(carpeta: {doc.ruta.replace(chr(92), '/').split('/')[-2]})\n\n{doc.texto}"]
    for r in relacionados:
        partes.append(f"\n\n=== DOCUMENTO RELACIONADO (solo para cruzar; NO se audita): {r.codigo} v{r.version} ===\n"
                      + r.texto[:40000])
    partes.append("\n\nAudita SOLO el documento a auditar. Devuelve el JSON con sus defectos.")
    resp, uso = llm.pedir_json(SISTEMA + referencias, "".join(partes), Respuesta)
    return _a_hallazgos(doc, resp, "llm"), uso


def _a_hallazgos(doc: Documento, resp: "Respuesta", origen: str) -> list[Hallazgo]:
    propuestas, _malas = resp.propuestas()
    salida = []
    for p in propuestas:
        h = Hallazgo(doc.codigo, p.ubicacion.strip(), p.tipo, p.clausula.strip(), p.justificacion.strip(),
                     evidencia=p.evidencia.strip(), origen=origen, confianza=p.confianza)
        h.calculo = p.calculo
        h.fuente = p.fuente
        salida.append(h)
    return salida


INSTRUCCION_FIGURAS = """Se adjuntan las páginas del documento que contienen FIGURAS (diagramas).
Tarea: para cada figura, lee qué dibuja (componentes, zonas, conexiones, flechas, protocolos, pasos de un flujo)
y compáralo con el texto que la acompaña y con los requisitos del propio documento y con STD-SEC-001.
Reporta SOLO las discrepancias reales entre figura y texto/requisitos, por ejemplo:
- una conexión que se salta un control (firewall, pasarela, DMZ) que los requisitos exigen;
- un flujo que sale sin cifrar o con un protocolo prohibido cuando el texto exige cifrado;
- un paso que el texto o un requisito describen y el diagrama omite (o al revés).
Ubicación: "Figura N" (el número de su título). En "evidencia" copia LITERAL la frase del TEXTO del documento
(requisito o párrafo) que el diagrama contradice. Si las figuras son coherentes, devuelve una lista vacía."""


def auditar_figuras(doc: Documento, referencias: str) -> list[Hallazgo]:
    """Visión solo donde el texto no llega (guía §7): páginas con figuras + texto del documento."""
    from src.ingesta import figura_png
    if not doc.figuras or doc.escaneado:
        return []
    paginas = sorted({f["pagina"] for f in doc.figuras})[:4]
    contenido = []
    for n in paginas:
        contenido.append({"type": "text", "text": f"[Página {n}]"})
        contenido.append(llm.imagen(figura_png(doc, n, zoom=1.6)))
    titulos = "\n".join(f["titulo"] for f in doc.figuras)
    contenido.append({"type": "text", "text": f"DOCUMENTO: {doc.codigo} v{doc.version}\nFiguras:\n{titulos}\n\n"
                                              f"{INSTRUCCION_FIGURAS}\n\nTEXTO DEL DOCUMENTO:\n{doc.texto}"})
    resp, _ = llm.pedir_json(SISTEMA + referencias, contenido, Respuesta)
    return [h for h in _a_hallazgos(doc, resp, "vision") if "Figura" in h.ubicacion]
