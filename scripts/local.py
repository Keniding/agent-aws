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


class FakeRuntime:
    def invoke_harness(self, harnessArn, runtimeSessionId, messages):
        text = messages[0]["content"][0]["text"]
        if text.startswith("Clasifica esta incidencia"):
            crit = "caída" in text.lower() or "caida" in text.lower()
            return {"stream": FakeStream(json.dumps({
                "severity": "critica" if crit else "media", "category": "Infraestructura",
                "summary": "Resumen automático.", "next_steps": ["Revisar logs", "Avisar al equipo"]}))}
        return {"stream": FakeStream("Prioriza lo crítico. Contexto: " + text.split("\n")[1][:60])}


def build_app():
    """Devuelve el módulo app ya conectado a moto + agente falso."""
    import boto3
    from moto import mock_aws

    os.environ.update(AWS_DEFAULT_REGION="us-east-1", AWS_ACCESS_KEY_ID="x",
                      AWS_SECRET_ACCESS_KEY="x", HARNESS_NAME="local", TABLE_NAME="incidencias")
    mock = mock_aws()
    mock.start()
    boto3.client("dynamodb").create_table(
        TableName="incidencias", BillingMode="PAY_PER_REQUEST",
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
