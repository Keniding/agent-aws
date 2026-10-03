"""Lambda (Function URL): serves the web page and proxies chat to an AgentCore harness."""

import json
import os
import re
import uuid

import boto3

MAX_CHARS = int(os.environ.get("MAX_MESSAGE_CHARS", "2000"))
HARNESS_NAME = os.environ["HARNESS_NAME"]
SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{33,128}$")  # harness needs >= 33 chars

_runtime = boto3.client("bedrock-agentcore")
_control = boto3.client("bedrock-agentcore-control")
_arn = None

with open(os.path.join(os.path.dirname(__file__), "index.html"), encoding="utf-8") as f:
    PAGE = f.read()


def harness_arn() -> str:
    """Resolve the harness ARN by name once per cold start."""
    global _arn
    if _arn is None:
        for page in _control.get_paginator("list_harnesses").paginate():
            for h in page["harnesses"]:
                if h["harnessName"] == HARNESS_NAME:
                    _arn = h["arn"]
                    return _arn
        raise RuntimeError(f"harness {HARNESS_NAME!r} not found; run scripts/harness.py")
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


def _json(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(body),
    }


def handler(event, _context):
    http = event["requestContext"]["http"]
    if http["method"] == "GET":
        return {"statusCode": 200, "headers": {"content-type": "text/html; charset=utf-8"},
                "body": PAGE}
    if http["method"] != "POST":
        return _json(405, {"error": "method not allowed"})
    try:
        data = json.loads(event.get("body") or "{}")
    except json.JSONDecodeError:
        return _json(400, {"error": "invalid JSON"})
    message = str(data.get("message", "")).strip()
    if not message or len(message) > MAX_CHARS:
        return _json(400, {"error": f"message must be 1..{MAX_CHARS} chars"})
    session_id = data.get("session_id") or str(uuid.uuid4())
    if not SESSION_RE.match(session_id):
        return _json(400, {"error": "invalid session_id"})
    try:
        return _json(200, {"session_id": session_id, "reply": ask(session_id, message)})
    except Exception as exc:  # noqa: BLE001 - demo: expose only the error class
        print("invoke failed:", repr(exc))
        return _json(502, {"error": type(exc).__name__})
