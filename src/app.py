"""Lambda (Function URL): web + API de incidencias; el asistente es un harness de AgentCore."""

import json
import os
import re
import time
import uuid

import boto3

MAX_CHARS = int(os.environ.get("MAX_MESSAGE_CHARS", "2000"))
HARNESS_NAME = os.environ["HARNESS_NAME"]
TABLE = os.environ["TABLE_NAME"]
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{33,128}$")  # el harness exige >= 33 caracteres
STATUSES = {"abierta", "en_curso", "resuelta"}

_runtime = boto3.client("bedrock-agentcore")
_control = boto3.client("bedrock-agentcore-control")
_table = boto3.resource("dynamodb").Table(TABLE)
_arn = None

with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
    PAGE = f.read()

SEVERITIES = ["baja", "media", "alta", "critica"]
MAX_STEPS = 6  # vueltas máximas del bucle agente <-> herramientas por petición
ID_RE = re.compile(r"^[0-9a-f]{32}$")

NEW_INCIDENT_PROMPT = (
    "Ha entrado una incidencia nueva (id {id}).\nTítulo: {title}\nDescripción: {description}\n\n"
    "Gestiónala tú: llama a clasificar_incidencia con su severidad, categoría, resumen y hasta 3 "
    "próximos pasos. Si es crítica, llama además a cambiar_estado para ponerla en_curso. "
    "Cuando termines, responde con una frase."
)


def _tool(name, description, props, required):
    return {"type": "inline_function", "name": name, "config": {"inlineFunction": {
        "description": description,
        "inputSchema": {"json": {"type": "object", "properties": props, "required": required}}}}}


TOOLS = [
    _tool("listar_incidencias", "Lista las incidencias (id, título, severidad, estado, resumen). "
          "Sin filtro devuelve solo las no resueltas.",
          {"estado": {"type": "string", "enum": sorted(STATUSES)}}, []),
    _tool("clasificar_incidencia", "Guarda la clasificación de una incidencia.",
          {"id": {"type": "string"}, "severidad": {"type": "string", "enum": SEVERITIES},
           "categoria": {"type": "string"}, "resumen": {"type": "string"},
           "proximos_pasos": {"type": "array", "items": {"type": "string"}}},
          ["id", "severidad", "categoria", "resumen"]),
    _tool("cambiar_estado", "Cambia el estado de una incidencia.",
          {"id": {"type": "string"}, "estado": {"type": "string", "enum": sorted(STATUSES)}},
          ["id", "estado"]),
]

def harness_arn() -> str:
    global _arn
    if _arn is None:
        for page in _control.get_paginator("list_harnesses").paginate():
            for h in page["harnesses"]:
                if h["harnessName"] == HARNESS_NAME:
                    _arn = h["arn"]
                    return _arn
        raise RuntimeError(f"harness {HARNESS_NAME!r} no existe; ejecuta scripts/harness.py up")
    return _arn


def _short(i: dict) -> dict:
    return {"id": i["id"], "titulo": i["title"], "severidad": i.get("severity", "sin_clasificar"),
            "estado": i["status"], "resumen": i.get("summary", "")}


def run_tool(name: str, args: dict) -> dict:
    """Ejecuta una herramienta pedida por el agente. Valida todo: la entrada viene de un modelo."""
    if name == "listar_incidencias":
        est = args.get("estado")
        items = list_incidents()
        items = [i for i in items if (i["status"] == est if est in STATUSES else i["status"] != "resuelta")]
        return {"incidencias": [_short(i) for i in items[:30]]}
    iid = str(args.get("id", ""))
    if not ID_RE.match(iid):
        raise ValueError("id inválido")
    if name == "clasificar_incidencia":
        sev = args.get("severidad")
        if sev not in SEVERITIES:
            raise ValueError(f"severidad debe ser una de {SEVERITIES}")
        steps = args.get("proximos_pasos")
        steps = [str(s)[:200] for s in steps][:3] if isinstance(steps, list) else []
        r = _update(iid, "SET severity = :v, category = :c, summary = :m, next_steps = :n",
                    {":v": sev, ":c": _text(args.get("categoria"), 60),
                     ":m": _text(args.get("resumen"), 300), ":n": steps})
        return _short(r)
    if name == "cambiar_estado":
        if args.get("estado") not in STATUSES:
            raise ValueError(f"estado debe ser uno de {sorted(STATUSES)}")
        return _short(_update(iid, "SET #s = :s", {":s": args["estado"]}, {"#s": "status"}))
    raise ValueError(f"herramienta desconocida: {name}")


def _update(iid, expr, values, names=None):
    kw = {"ExpressionAttributeNames": names} if names else {}
    try:
        return _table.update_item(
            Key={"id": iid}, UpdateExpression=expr, ConditionExpression="attribute_exists(id)",
            ExpressionAttributeValues=values, ReturnValues="ALL_NEW", **kw)["Attributes"]
    except _table.meta.client.exceptions.ConditionalCheckFailedException:
        raise ValueError("la incidencia no existe") from None


def invoke(session_id: str, messages: list):
    """Una vuelta al harness: devuelve (texto, llamadas a herramientas, motivo de parada)."""
    resp = _runtime.invoke_harness(harnessArn=harness_arn(), runtimeSessionId=session_id,
                                   messages=messages, tools=TOOLS)
    text, calls, cur, stop = [], [], None, None
    for event in resp["stream"]:
        tu = event.get("contentBlockStart", {}).get("start", {}).get("toolUse")
        if tu:
            cur = {"id": tu["toolUseId"], "name": tu["name"], "input": ""}
            calls.append(cur)
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            text.append(delta["text"])
        if "toolUse" in delta and cur is not None:
            cur["input"] += delta["toolUse"].get("input", "")
        if "messageStop" in event:
            stop = event["messageStop"].get("stopReason")
    # Nemotron emite su razonamiento antes de </think>: solo interesa la respuesta final.
    return "".join(text).rsplit("</think>", 1)[-1].strip(), calls, stop


def ask(session_id: str, text: str):
    """Bucle del agente: el harness decide, aquí se ejecutan sus herramientas. -> (respuesta, acciones)."""
    messages, actions, reply = [{"role": "user", "content": [{"text": text}]}], [], ""
    for _ in range(MAX_STEPS):
        reply, calls, stop = invoke(session_id, messages)
        if stop != "tool_use" or not calls:
            break
        results = []
        for c in calls:
            try:
                args = json.loads(c["input"] or "{}")
                out, status = run_tool(c["name"], args if isinstance(args, dict) else {}), "success"
            except Exception as exc:  # noqa: BLE001 - el error vuelve al agente para que se corrija
                args, out, status = {}, {"error": str(exc)}, "error"
            actions.append({"tool": c["name"], "ok": status == "success"})
            results.append({"toolResult": {"toolUseId": c["id"], "status": status,
                                           # solo texto: el eco con 'json' rompe el parser de boto3
                                           "content": [{"text": json.dumps(out, default=int)}]}})
        messages = [{"role": "user", "content": results}]
    return reply, actions


def list_incidents() -> list:
    items = _table.scan()["Items"]
    return sorted(items, key=lambda i: i["created_at"], reverse=True)


def create_incident(title: str, description: str) -> dict:
    item = {"id": uuid.uuid4().hex, "title": title, "description": description,
            "status": "abierta", "created_at": int(time.time()),
            "severity": "sin_clasificar", "category": "", "summary": "", "next_steps": []}
    _table.put_item(Item=item)  # primero se guarda: si el agente falla, la incidencia no se pierde
    try:
        _, actions = ask(str(uuid.uuid4()), NEW_INCIDENT_PROMPT.format(
            id=item["id"], title=title, description=description))
        item = _table.get_item(Key={"id": item["id"]})["Item"]
        item["actions"] = actions
    except Exception as exc:  # noqa: BLE001
        print("triage failed:", repr(exc))
    return item


def chat(session_id: str, message: str):
    return ask(session_id, message)


def _json(status: int, body) -> dict:
    return {"statusCode": status, "headers": {"content-type": "application/json"},
            "body": json.dumps(body, default=int)}


def _text(value, limit) -> str:
    return str(value or "").strip()[:limit]


def handler(event, _context):
    http = event["requestContext"]["http"]
    method, path = http["method"], event.get("rawPath", "/")
    if method == "GET" and path == "/":
        return {"statusCode": 200, "headers": {"content-type": "text/html; charset=utf-8"},
                "body": PAGE}
    try:
        body = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _json(400, {"error": "JSON inválido"})

    if method == "GET" and path == "/api/incidents":
        return _json(200, list_incidents())

    if method == "POST" and path == "/api/incidents":
        title, desc = _text(body.get("title"), 200), _text(body.get("description"), MAX_CHARS)
        if not title:
            return _json(400, {"error": "falta el título"})
        return _json(201, create_incident(title, desc))

    m = re.fullmatch(r"/api/incidents/([0-9a-f]{32})", path)
    if method == "PATCH" and m:
        if body.get("status") not in STATUSES:
            return _json(400, {"error": f"status debe ser uno de {sorted(STATUSES)}"})
        try:
            r = _table.update_item(
                Key={"id": m.group(1)}, UpdateExpression="SET #s = :s",
                ConditionExpression="attribute_exists(id)",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": body["status"]}, ReturnValues="ALL_NEW")
        except _table.meta.client.exceptions.ConditionalCheckFailedException:
            return _json(404, {"error": "no existe"})
        return _json(200, r["Attributes"])

    if method == "POST" and path == "/api/chat":
        message = _text(body.get("message"), MAX_CHARS + 1)
        if not message or len(message) > MAX_CHARS:
            return _json(400, {"error": f"el mensaje debe tener 1..{MAX_CHARS} caracteres"})
        sid = body.get("session_id") or str(uuid.uuid4())
        if not SESSION_RE.match(sid):
            return _json(400, {"error": "session_id inválido"})
        try:
            reply, actions = chat(sid, message)
            return _json(200, {"session_id": sid, "reply": reply, "actions": actions})
        except Exception as exc:  # noqa: BLE001 - solo exponemos la clase del error
            print("chat failed:", repr(exc))
            return _json(502, {"error": type(exc).__name__})

    return _json(404, {"error": "no encontrado"})
