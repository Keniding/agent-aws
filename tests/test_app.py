import json
import os
import sys

os.environ["HARNESS_NAME"] = "t"
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import app


def ev(method, body=None):
    return {"requestContext": {"http": {"method": method}}, "body": json.dumps(body) if body else None}


def test_get_serves_page():
    r = app.handler(ev("GET"), None)
    assert r["statusCode"] == 200 and "<form" in r["body"]


def test_post_validates():
    assert app.handler(ev("POST", {"message": ""}), None)["statusCode"] == 400
    assert app.handler(ev("POST", {"message": "x", "session_id": "short"}), None)["statusCode"] == 400


def test_post_ok(monkeypatch):
    monkeypatch.setattr(app, "ask", lambda s, t: "hola " + t)
    r = app.handler(ev("POST", {"message": "yo"}), None)
    body = json.loads(r["body"])
    assert r["statusCode"] == 200 and body["reply"] == "hola yo" and len(body["session_id"]) >= 33
