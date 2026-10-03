import json
import os
import sys

os.environ.update(HARNESS_NAME="t", TABLE_NAME="t", AWS_DEFAULT_REGION="us-east-1")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import app


class FakeTable:
    def __init__(self):
        self.items = {}

    def scan(self):
        return {"Items": list(self.items.values())}

    def put_item(self, Item):
        self.items[Item["id"]] = Item


def ev(method, path, body=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path,
            "body": json.dumps(body) if body is not None else None}


def test_page():
    assert "<form" in app.handler(ev("GET", "/"), None)["body"]


def test_create_and_list(monkeypatch):
    monkeypatch.setattr(app, "_table", FakeTable())
    monkeypatch.setattr(app, "ask", lambda s, t: 'ok {"severity":"alta","next_steps":["a"]}')
    r = app.handler(ev("POST", "/api/incidents", {"title": "BD caída"}), None)
    assert r["statusCode"] == 201 and json.loads(r["body"])["severity"] == "alta"
    assert len(json.loads(app.handler(ev("GET", "/api/incidents"), None)["body"])) == 1


def test_triage_failure_still_saves(monkeypatch):
    monkeypatch.setattr(app, "_table", FakeTable())

    def boom(*_):
        raise RuntimeError

    monkeypatch.setattr(app, "ask", boom)
    r = app.handler(ev("POST", "/api/incidents", {"title": "x"}), None)
    assert json.loads(r["body"])["severity"] == "sin_clasificar"


def test_validation():
    assert app.handler(ev("POST", "/api/incidents", {"title": ""}), None)["statusCode"] == 400
    assert app.handler(ev("PATCH", "/api/incidents/" + "a" * 32, {"status": "x"}),
                       None)["statusCode"] == 400
    assert app.handler(ev("POST", "/api/chat", {"message": "hi", "session_id": "short"}),
                       None)["statusCode"] == 400


def test_chat(monkeypatch):
    monkeypatch.setattr(app, "_table", FakeTable())
    monkeypatch.setattr(app, "ask", lambda s, t: "resp")
    r = app.handler(ev("POST", "/api/chat", {"message": "hola"}), None)
    assert json.loads(r["body"])["reply"] == "resp"
