"""
API externa de solo lectura, versión 1 (GET /api/v1/…). Lógica pura, sin HTTP: servidor.py comprueba la clave y
el ritmo y llama a responder(); se prueba en tests/test_api_v1.py.

Rutas
  /api/v1/metricas/{resumen|cumplimiento|equipo|ia}   las mismas cifras que la pestaña Métricas (src/metricas.py)
  /api/v1/documentos                                  un registro por documento (paginado; JSON o CSV)
  /api/v1/hallazgos                                   un registro por hallazgo (paginado; JSON o CSV)
  /api/v1/openapi.json  ·  /api/v1/docs               descripción estándar y página de ayuda (no piden clave)

Sin nombres de personas: ni quién decidió, ni quién editó, ni a quién se devolvió un documento.
Listas: {"datos": [...], "total", "pagina", "limite", "paginas", "generado", "filtros"}. Errores: {"error": {"codigo", "mensaje"}}.
"""
import csv
import io
from datetime import date

from src import metricas as M

LIMITE_DEF, LIMITE_MAX = 100, 1000
SECCIONES = ("resumen", "cumplimiento", "equipo", "ia")
F_METRICAS = ("periodo", "familia", "prioridad", "tipo", "clausula")
F_DOCS = ("familia", "prioridad", "estado", "vencidos")
F_HALL = ("documento", "familia", "tipo", "clausula", "decision")
DECISION = {"approved": "aceptado", "rejected": "rechazado"}


def alcance_de(ruta: str) -> str | None:
    if ruta.startswith("/api/v1/metricas/"):
        return "metricas"
    return {"/api/v1/documentos": "documentos", "/api/v1/hallazgos": "hallazgos"}.get(ruta)


def error(codigo: int, clave: str, mensaje: str) -> tuple[int, dict]:
    return codigo, {"error": {"codigo": clave, "mensaje": mensaje}}


def _uno(q: dict, k: str) -> str:
    v = q.get(k)
    return str((v[0] if isinstance(v, list) else v) or "")[:120]


def _paginar(filas: list[dict], q: dict, filtros: dict, hoy: date) -> tuple[int, dict]:
    try:
        limite = int(_uno(q, "limite") or LIMITE_DEF)
        pagina = int(_uno(q, "pagina") or 1)
    except ValueError:
        return error(400, "parametro_no_valido", "«limite» y «pagina» tienen que ser números.")
    if not 1 <= limite <= LIMITE_MAX or pagina < 1:
        return error(400, "parametro_no_valido", f"«limite» va de 1 a {LIMITE_MAX} y «pagina» empieza en 1.")
    paginas = max(1, -(-len(filas) // limite))
    return 200, {"datos": filas[(pagina - 1) * limite: pagina * limite], "total": len(filas), "pagina": pagina,
                 "limite": limite, "paginas": paginas, "generado": hoy.isoformat(), "filtros": filtros}


def documentos(res, docs, estado, cargados, q, hoy) -> list[dict]:
    f = {k: _uno(q, k) for k in F_DOCS}
    dec = estado.get("dec", {})
    filas = []
    for d in M.documentos(res, docs, estado, cargados, hoy):
        dd = d["dias"]
        vencido = dd["tipo"] == "dias" and dd["n"] < 0
        if (f["familia"] and d["familia"] != f["familia"]) or (f["prioridad"] and d["prioridad"] != f["prioridad"]) \
                or (f["estado"] and d["estado"] != f["estado"]) or (f["vencidos"] in ("si", "sí", "1", "true") and not vencido):
            continue
        ds = [dec.get(f"{r['documento']}|{r['ubicacion']}") for r in d["hallazgos"]]
        filas.append({"documento": d["doc"], "titulo": d["titulo"], "familia": d["familia"], "estado": d["estado"],
                      "prioridad": d["prioridad"], "dias_para_responder": dd.get("n") if dd["tipo"] == "dias" else None,
                      "respondido": dd["tipo"] == "hecho", "vencido": vencido, "inicio": d["inicio"],
                      "hallazgos": len(ds), "decididos": sum(1 for x in ds if x),
                      "aceptados": sum(1 for x in ds if x and x.get("dec") == "approved"),
                      "rechazados": sum(1 for x in ds if x and x.get("dec") == "rejected"),
                      "devuelto": d["escalado"], "cargado": d["cargado"]})
    return filas


def hallazgos(res, docs, estado, cargados, q, hoy) -> list[dict]:
    f = {k: _uno(q, k) for k in F_HALL}
    dec, ed = estado.get("dec", {}), estado.get("ediciones", {})
    fam = {d["doc"]: d["familia"] for d in M.documentos(res, docs, estado, cargados, hoy)}
    filas = []
    for r in res:
        k = f"{r['documento']}|{r['ubicacion']}"
        x = dec.get(k)
        decision = DECISION.get((x or {}).get("dec"), "pendiente")
        if (f["documento"] and r["documento"] != f["documento"]) or (f["familia"] and fam.get(r["documento"]) != f["familia"]) \
                or (f["tipo"] and r["tipo"] != f["tipo"]) or (f["clausula"] and r["clausula"] != f["clausula"]) \
                or (f["decision"] and decision != f["decision"]):
            continue
        filas.append({"documento": r["documento"], "ubicacion": r["ubicacion"], "familia": fam.get(r["documento"], ""),
                      "tipo": r["tipo"], "clausula": r["clausula"], "confianza": r.get("conf"),
                      "origen": (r.get("origen") or "").split(" ")[0], "pagina": r.get("pagina"),
                      "justificacion": r.get("justificacion", ""), "decision": decision,
                      "fecha_decision": str(x.get("fecha", ""))[:10] if x else None, "editado": bool(ed.get(k))})
    return filas


def a_csv(filas: list[dict], separador: str = ";") -> str:
    """CSV para Excel: UTF-8 con BOM y «;» (configuración regional española); separador=coma para «,»."""
    if not filas:
        return "﻿"
    b = io.StringIO()
    w = csv.DictWriter(b, fieldnames=list(filas[0]), delimiter=separador, lineterminator="\r\n")
    w.writeheader()
    for f in filas:
        w.writerow({k: ("sí" if v is True else "no" if v is False else "" if v is None else v) for k, v in f.items()})
    return "﻿" + b.getvalue()


def responder(ruta: str, q: dict, res, docs, estado, cargados, hoy: date, metricas_ia=None):
    """→ (código, cuerpo, tipo): cuerpo es un dict (JSON) o un str (CSV)."""
    formato = _uno(q, "formato") or "json"
    if formato not in ("json", "csv"):
        return (*error(400, "parametro_no_valido", "«formato» es json o csv."), "json")
    if ruta.startswith("/api/v1/metricas/"):
        sec = ruta.rsplit("/", 1)[1]
        if sec not in SECCIONES:
            return (*error(404, "no_encontrado", f"Métricas disponibles: {', '.join(SECCIONES)}."), "json")
        if formato == "csv":
            return (*error(400, "parametro_no_valido", "Las métricas solo se sirven en JSON; documentos y hallazgos también en CSV."), "json")
        filtros = {k: _uno(q, k) for k in F_METRICAS}
        datos = M.calcular(res, docs, estado, cargados, filtros, hoy, metricas_ia)
        return 200, {"datos": datos[sec], "meta": datos["meta"]}, "json"
    fn = {"/api/v1/documentos": (documentos, F_DOCS), "/api/v1/hallazgos": (hallazgos, F_HALL)}.get(ruta)
    if not fn:
        return (*error(404, "no_encontrado", "Ruta desconocida. Mira /api/v1/docs."), "json")
    filas = fn[0](res, docs, estado, cargados, q, hoy)
    code, cuerpo = _paginar(filas, q, {k: _uno(q, k) for k in fn[1] if _uno(q, k)}, hoy)
    if code != 200 or formato == "json":
        return code, cuerpo, "json"
    return 200, a_csv(cuerpo["datos"], "," if _uno(q, "separador") == "coma" else ";"), "csv"


# ------------------------------------------------------------------ descripción estándar (OpenAPI 3.1)
def _p(nombre, desc, enum=None):
    s = {"type": "string"} | ({"enum": enum} if enum else {})
    return {"name": nombre, "in": "query", "required": False, "description": desc, "schema": s}


_PAG = [{"name": "limite", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": LIMITE_MAX, "default": LIMITE_DEF}},
        {"name": "pagina", "in": "query", "schema": {"type": "integer", "minimum": 1, "default": 1}},
        _p("formato", "json (por defecto) o csv", ["json", "csv"]), _p("separador", "CSV con «;» (por defecto) o «,»", ["coma"])]
_ERR = {"401": {"description": "Falta la clave, no es válida, está caducada o revocada"},
        "403": {"description": "La clave no tiene ese alcance, o el rol de su dueño ya no lo permite"},
        "429": {"description": "Demasiadas peticiones: espera los segundos de la cabecera Retry-After"}}
OPENAPI = {
    "openapi": "3.1.0",
    "info": {"title": "Nimbus Audit Studio · API de solo lectura", "version": "1.0.0",
             "description": "Métricas, documentos y hallazgos de la revisión Part-IS. Sin nombres de personas. "
                            "Autenticación: cabecera «Authorization: Bearer nas_…» con una clave creada en Mi cuenta."},
    "components": {"securitySchemes": {"clave": {"type": "http", "scheme": "bearer", "description": "Clave de API (nas_…)"}}},
    "security": [{"clave": []}],
    "paths": {
        "/api/v1/metricas/{seccion}": {"get": {
            "summary": "Métricas (las mismas que la pestaña Métricas)", "parameters": [
                {"name": "seccion", "in": "path", "required": True, "schema": {"type": "string", "enum": list(SECCIONES)}},
                _p("periodo", "Actividad de los últimos días", ["todo", "7", "30", "90"]), _p("familia", "Familia del documento"),
                _p("prioridad", "Prioridad", ["Alta", "Media", "Baja"]), _p("tipo", "Tipo de hallazgo"), _p("clausula", "Cláusula Part-IS")],
            "responses": {"200": {"description": "{datos, meta}"}, **_ERR}}},
        "/api/v1/documentos": {"get": {
            "summary": "Documentos: estado, prioridad, días para responder y avance", "parameters": [
                _p("familia", "Familia"), _p("prioridad", "Prioridad", ["Alta", "Media", "Baja"]),
                _p("estado", "Estado", ["Pendiente", "En revisión", "Completado", "Sin hallazgos"]), _p("vencidos", "Solo los vencidos", ["si"]), *_PAG],
            "responses": {"200": {"description": "{datos, total, pagina, limite, paginas, generado, filtros}"}, **_ERR}}},
        "/api/v1/hallazgos": {"get": {
            "summary": "Hallazgos: tipo, cláusula, confianza, origen y decisión del equipo", "parameters": [
                _p("documento", "Código del documento"), _p("familia", "Familia"), _p("tipo", "Tipo de hallazgo"),
                _p("clausula", "Cláusula Part-IS"), _p("decision", "Decisión", ["aceptado", "rechazado", "pendiente"]), *_PAG],
            "responses": {"200": {"description": "{datos, total, pagina, limite, paginas, generado, filtros}"}, **_ERR}}},
    },
}


def pagina_docs(base: str) -> str:
    """Ayuda con ejemplos listos para copiar (curl, Python, Excel, Power BI). `base` = http://host:puerto"""
    e = lambda s: s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    ej = {
        "curl": f'curl -H "Authorization: Bearer nas_TU_CLAVE" "{base}/api/v1/documentos?vencidos=si"',
        "Python": f'''import requests
r = requests.get("{base}/api/v1/hallazgos", params={{"tipo": "No cumple", "limite": 500}},
                 headers={{"Authorization": "Bearer nas_TU_CLAVE"}}, timeout=30)
r.raise_for_status()
for h in r.json()["datos"]:
    print(h["documento"], h["clausula"], h["decision"])''',
        "Excel o Power BI (Power Query, «Desde web» → Avanzado, o el editor avanzado)": f'''let
    Origen = Json.Document(Web.Contents("{base}",
        [RelativePath = "api/v1/documentos", Query = [limite = "1000"],
         Headers = [Authorization = "Bearer nas_TU_CLAVE"]])),
    Tabla = Table.FromRecords(Origen[datos])
in
    Tabla''',
    }
    filas = "".join(f"<h3>{e(k)}</h3><pre>{e(v)}</pre>" for k, v in ej.items())
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>API · Nimbus Audit Studio</title><style>
body{{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;max-width:860px;margin:32px auto;padding:0 16px;color:#1c1c1e;background:#fff;line-height:1.5}}
h1{{font-size:26px}}h2{{font-size:19px;margin-top:28px}}h3{{font-size:15px;margin:18px 0 6px}}
pre{{background:#f5f5f7;border:1px solid #e1e0d9;border-radius:8px;padding:12px;overflow:auto;font-size:13px}}
code{{background:#f5f5f7;padding:1px 5px;border-radius:4px}}table{{border-collapse:collapse;width:100%;font-size:14px}}
td,th{{border:1px solid #e1e0d9;padding:6px 8px;text-align:left;vertical-align:top}}.aviso{{background:#fff4e0;border:1px solid #f3c98b;border-radius:8px;padding:10px 12px}}
</style></head><body>
<h1>API de solo lectura · Nimbus Audit Studio</h1>
<p>Métricas, documentos y hallazgos de la revisión Part-IS para Power BI, Excel o scripts. <b>Sin nombres de personas.</b>
Descripción estándar: <a href="/api/v1/openapi.json">/api/v1/openapi.json</a>.</p>
<p class="aviso"><b>Seguridad.</b> La clave se crea en <b>Mi cuenta → Claves de API</b> y se ve una sola vez: guárdala como una contraseña.
Este servidor usa <code>http</code> sin cifrar: úsala en el mismo ordenador o en una red de confianza, nunca desde internet.</p>
<h2>Autenticación</h2><p>Cabecera <code>Authorization: Bearer nas_…</code> (nunca en la dirección: las direcciones quedan en historiales).
Límite: 60 peticiones por minuto y clave (si se pasa, <code>429</code> con <code>Retry-After</code>).</p>
<h2>Rutas</h2><table><tr><th>Ruta</th><th>Alcance</th><th>Filtros</th></tr>
<tr><td><code>/api/v1/metricas/resumen</code> · <code>/cumplimiento</code> · <code>/equipo</code> · <code>/ia</code></td><td>métricas</td><td>periodo (todo, 7, 30, 90), familia, prioridad, tipo, clausula</td></tr>
<tr><td><code>/api/v1/documentos</code></td><td>documentos</td><td>familia, prioridad, estado, vencidos=si · limite, pagina · formato=csv</td></tr>
<tr><td><code>/api/v1/hallazgos</code></td><td>hallazgos</td><td>documento, familia, tipo, clausula, decision (aceptado, rechazado, pendiente) · limite, pagina · formato=csv</td></tr></table>
<p>Listas: <code>{{"datos": [...], "total", "pagina", "limite", "paginas", "generado", "filtros"}}</code> (hasta {LIMITE_MAX} por página).
Errores: <code>{{"error": {{"codigo", "mensaje"}}}}</code> — 401 clave, 403 alcance o permiso, 404 ruta, 429 ritmo.</p>
<h2>Ejemplos</h2>{filas}
<p>Para abrir una lista directamente en Excel: añade <code>?formato=csv</code> (UTF-8, separada por «;»; <code>&amp;separador=coma</code> para «,»).</p>
</body></html>"""
