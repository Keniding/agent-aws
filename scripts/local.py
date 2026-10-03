"""Servidor local: la Lambda real sobre DynamoDB simulado (moto) y un agente falso.

Uso: uv run scripts/local.py [puerto]   (también lo usan las pruebas e2e)
"""

import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = os.path.join(os.path.dirname(__file__), "..", "src")


class FakeStream:
    """Imita la respuesta de InvokeHarness: {'stream': [eventos…]}."""

    def __init__(self, text):
        self.text = text

    def __iter__(self):
        mid = len(self.text) // 2
        for part in (self.text[:mid], self.text[mid:]):
            yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"text": part}}}
        yield {"messageStop": {"stopReason": "end_turn"}}


class FakeToolStream:
    """El agente pide una herramienta: contentBlockStart/Delta con toolUse y parada tool_use."""

    def __init__(self, name, args, call_id="call1"):
        self.name, self.args, self.call_id = name, args, call_id

    def __iter__(self):
        yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {
            "toolUse": {"toolUseId": self.call_id, "name": self.name, "type": "tool_use"}}}}
        raw = json.dumps(self.args)
        yield {"contentBlockDelta": {"contentBlockIndex": 0, "delta": {"toolUse": {"input": raw}}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"messageStop": {"stopReason": "tool_use"}}


class FakeGatewayStream:
    """Herramienta que ejecuta el propio harness (Gateway): aparece en el flujo, pero no se devuelve a la app."""

    def __init__(self, name, text):
        self.name, self.text = name, text

    def __iter__(self):
        yield {"contentBlockStart": {"contentBlockIndex": 0, "start": {
            "toolUse": {"toolUseId": "gw1", "name": self.name, "type": "tool_use"}}}}
        yield {"contentBlockStop": {"contentBlockIndex": 0}}
        yield {"contentBlockDelta": {"contentBlockIndex": 1, "delta": {"text": self.text}}}
        yield {"messageStop": {"stopReason": "end_turn"}}


class FakeRuntime:
    """Agente falso con el mismo protocolo que el harness: pide herramientas y luego responde."""

    RANK = {"critica": 0, "alta": 1, "media": 2, "baja": 3}  # noqa: RUF012 - constante de solo lectura

    def __init__(self):
        self.queue = {}  # sesión -> pasos pendientes: (herramienta, args) | función(resultado) | texto final

    @staticmethod
    def _start_most_urgent(result):
        items = json.loads(result).get("incidencias", [])
        if not items:
            return "No hay incidencias pendientes."
        best = min(items, key=lambda i: FakeRuntime.RANK.get(i["severidad"], 4))
        return ("cambiar_estado", {"id": best["id"], "estado": "en_curso"})

    def _next(self, pend, result):
        while pend:
            step = pend.pop(0)
            if callable(step):
                step = step(result)
            if isinstance(step, str):
                return {"stream": FakeStream(step)}
            if step:
                return {"stream": FakeToolStream(*step)}
        return {"stream": FakeStream("Incidencia gestionada.")}

    def invoke_harness(self, harnessArn, runtimeSessionId, messages, tools=None, allowedTools=None, **_):
        self.last_allowed = allowedTools
        first = messages[0]["content"][0]
        sid = runtimeSessionId
        if "toolResult" in first:
            return self._next(self.queue.get(sid, []), first["toolResult"]["content"][0]["text"])
        text = first["text"]
        if "ÓRDENES DE CAMBIO" in text:  # el Gateway lo ejecuta el propio harness: la app solo ve el aviso y el texto
            return {"stream": FakeGatewayStream("oc___listar_oc", "Revisé las órdenes abiertas.")}
        if text.startswith("Ha entrado una incidencia nueva"):
            iid = text.split("id ")[1].split(")")[0]
            crit = any(w in text.lower() for w in ("caída", "caida", "caído", "caido"))
            self.queue[sid] = [("cambiar_estado", {"id": iid, "estado": "en_curso"})] if crit else []
            return {"stream": FakeToolStream("clasificar_incidencia", {
                "id": iid, "severidad": "critica" if crit else "media", "categoria": "Infraestructura",
                "resumen": "Resumen automático.", "proximos_pasos": ["Revisar logs", "Avisar al equipo"]})}
        if text.lower().startswith("registra una incidencia"):
            title = text.split("\n")[0].split(":", 1)[-1].strip()
            self.queue[sid] = ["Registrada. La clasifiqué y ya está en tu lista."]
            return {"stream": FakeToolStream("crear_incidencia", {"titulo": title, "severidad": "media"})}
        if text.lower().startswith("¿qué atiendo"):
            self.queue[sid] = ["Prioriza lo crítico: atiende primero la de mayor severidad."]
            return {"stream": FakeToolStream("listar_incidencias", {})}
        if text.startswith("Toma la incidencia pendiente"):
            self.queue[sid] = [self._start_most_urgent,
                               "Hecho: la puse en curso. Primeros pasos: revisar logs y avisar al equipo."]
            return {"stream": FakeToolStream("listar_incidencias", {})}
        return {"stream": FakeStream("Prioriza lo crítico. " + text[:60])}


def build_app():
    """Devuelve el módulo app ya conectado a moto + agente falso."""
    import boto3
    from moto import mock_aws

    os.environ.update(AWS_DEFAULT_REGION="us-east-1", AWS_ACCESS_KEY_ID="x",
                      AWS_SECRET_ACCESS_KEY="x", HARNESS_NAME="local", TABLE_NAME="incidencias",
                      OC_TABLE_NAME="ordenes", OC_ALLOWED_TOOLS="@oc,@builtin/skills", AUTH_DISABLED="1")
    mock = mock_aws()
    mock.start()
    for name in ("incidencias", "ordenes"):
        boto3.client("dynamodb").create_table(
            TableName=name, BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "id", "KeyType": "HASH"}])
    sys.path.insert(0, ROOT)
    import app

    app._runtime = FakeRuntime()
    app._arn = "arn:aws:bedrock-agentcore:us-east-1:000000000000:harness/local"
    return app, mock


def serve(port=0):
    app, mock = build_app()

    class H(BaseHTTPRequestHandler):
        def _go(self):
            n = int(self.headers.get("content-length") or 0)
            ev = {"requestContext": {"http": {"method": self.command}},
                  "rawPath": self.path.split("?")[0],
                  "body": self.rfile.read(n).decode() if n else None}
            r = app.handler(ev, None)
            self.send_response(r["statusCode"])
            for k, v in r["headers"].items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(r["body"].encode())

        do_GET = do_POST = do_PATCH = _go

        def log_message(self, *_):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, mock


if __name__ == "__main__":
    srv, _ = serve(int(sys.argv[1]) if len(sys.argv) > 1 else 8000)
    print(f"http://127.0.0.1:{srv.server_port}  (Ctrl+C para salir)")
    threading.Event().wait()
