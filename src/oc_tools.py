"""Herramientas del agente para órdenes de cambio: Lambda detrás de AgentCore Gateway (destino MCP de tipo Lambda).

Gateway entrega en `event` los argumentos de la herramienta y en el contexto su nombre con prefijo
(`<destino>___<herramienta>`, doc «gateway-add-target-lambda»). El agente puede registrar, consultar, evaluar y anotar,
pero NO aprobar, programar ni cerrar: eso lo decide siempre una persona desde la web (OWASP LLM06: agencia excesiva).
"""

import oc

POR = "agente"
SEP = "___"


def _resumen(o: dict) -> dict:
    return {k: o.get(k) for k in ("id", "titulo", "tipo", "servicio", "recurso", "parametro", "valor_actual",
                                  "valor_propuesto", "estado", "justificacion")} | {
        "riesgo": o.get("evaluacion", {}).get("riesgo")}


def _listar(a):
    return {"ordenes": [_resumen(o) for o in oc.listar(a.get("estado") or None)[:30]]}


def _consultar(a):
    o = oc.obtener(a.get("id"))
    return {**_resumen(o), "evaluacion": o.get("evaluacion", {}), "solicitante": o.get("solicitante"),
            "historial": [{"a": h["a"], "por": h["por"], "nota": h["nota"]} for h in o.get("historial", [])]}


TOOLS = {
    "listar_oc": _listar,
    "consultar_oc": _consultar,
    "registrar_oc": lambda a: _resumen(oc.crear(a, POR)),
    "evaluar_oc": lambda a: _resumen(oc.evaluar(a.get("id"), a, POR)),
    "agregar_nota_oc": lambda a: _resumen(oc.nota(a.get("id"), a.get("nota"), POR)),
}


def handler(event, context):
    name = context.client_context.custom["bedrockAgentCoreToolName"].split(SEP, 1)[-1]
    fn = TOOLS.get(name)
    if fn is None:
        return {"error": f"herramienta desconocida: {name}"}
    try:
        return fn(event if isinstance(event, dict) else {})
    except oc.OcError as exc:  # error de negocio: vuelve al agente para que se corrija
        return {"error": str(exc)}
    except Exception as exc:  # noqa: BLE001 - no se filtran detalles internos al modelo
        print("oc_tools failed:", name, repr(exc))
        return {"error": "error interno al procesar la orden"}
