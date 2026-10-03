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

TRIAGE_PROMPT = (
    "Clasifica esta incidencia. Responde SOLO un objeto JSON con las claves: "
    '"severity" (baja|media|alta|critica), "category" (texto corto), '
    '"summary" (una frase), "next_steps" (lista de hasta 3 acciones).\n\n'
    "Título: {title}\nDescripción: {description}"
)


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


def ask(session_id: str, text: str) -> str:
    resp = _runtime.invoke_harness(
        harnessArn=harness_arn(),
        runtimeSessionId=session_id,
        messages=[{"role": "user", "content": [{"text": text}]}],
    )
    out = []
    for event in resp["stream"]:
        delta = event.get("contentBlockDelta", {}).get("delta", {})
        if "text" in delta:
            out.append(delta["text"])
    return "".join(out)


def parse_triage(text: str) -> dict:
    m = re.search(r"\{.*\}", text, re.DOTALL)
    try:
        data = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        data = {}
    steps = data.get("next_steps")
    return {
        "severity": str(data.get("severity", "sin_clasificar")),
        "category": str(data.get("category", "")),
        "summary": str(data.get("summary", "")),
        "next_steps": [str(s) for s in steps][:3] if isinstance(steps, list) else [],
    }


def list_incidents() -> list:
    items = _table.scan()["Items"]
    return sorted(items, key=lambda i: i["created_at"], reverse=True)


def create_incident(title: str, description: str) -> dict:
    item = {"id": uuid.uuid4().hex, "title": title, "description": description,
            "status": "abierta", "created_at": int(time.time())}
    try:
        item.update(parse_triage(ask(str(uuid.uuid4()),
                                     TRIAGE_PROMPT.format(title=title, description=description))))
    except Exception as exc:  # noqa: BLE001 - la incidencia se guarda aunque falle el asistente
        print("triage failed:", repr(exc))
        item["severity"] = "sin_clasificar"
    _table.put_item(Item=item)
    return item


def chat(session_id: str, message: str) -> str:
    open_ = [i for i in list_incidents() if i["status"] != "resuelta"][:20]
    ctx = "\n".join(f"- [{i['id'][:8]}] {i['severity']} · {i['status']} · {i['title']}"
                    for i in open_) or "(ninguna)"
    return ask(session_id, f"Incidencias abiertas:\n{ctx}\n\nPregunta: {message}")


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
            return _json(200, {"session_id": sid, "reply": chat(sid, message)})
        except Exception as exc:  # noqa: BLE001 - solo exponemos la clase del error
            print("chat failed:", repr(exc))
            return _json(502, {"error": type(exc).__name__})

    return _json(404, {"error": "no encontrado"})
