import json

import local  # scripts/local.py (FakeRuntime/FakeStream)


def ev(method, path, body=None):
    return {"requestContext": {"http": {"method": method}}, "rawPath": path,
            "body": json.dumps(body) if body is not None else None}


def call(app, method, path, body=None):
    r = app.handler(ev(method, path, body), None)
    return r["statusCode"], json.loads(r["body"]) if r["headers"]["content-type"].startswith(
        "application/json") else r["body"]


def test_page_served(app):
    status, html = call(app, "GET", "/")
    assert status == 200 and "<title>Incidencias</title>" in html


def test_create_triages_and_persists(app):
    status, inc = call(app, "POST", "/api/incidents",
                       {"title": "Caída de la BD", "description": "no responde"})
    assert status == 201
    assert inc["severity"] == "critica" and inc["status"] == "abierta"
    assert inc["next_steps"] == ["Revisar logs", "Avisar al equipo"]
    _, items = call(app, "GET", "/api/incidents")
    assert [i["id"] for i in items] == [inc["id"]]


def test_list_is_newest_first(app, monkeypatch):
    ids = []
    for n, t in enumerate(["a", "b", "c"]):
        monkeypatch.setattr(app.time, "time", lambda n=n: 1000 + n)  # reloj controlado
        ids.append(call(app, "POST", "/api/incidents", {"title": t})[1]["id"])
    _, items = call(app, "GET", "/api/incidents")
    assert [i["id"] for i in items] == ids[::-1]


def test_status_update_and_404(app):
    _, inc = call(app, "POST", "/api/incidents", {"title": "x"})
    status, upd = call(app, "PATCH", f"/api/incidents/{inc['id']}", {"status": "resuelta"})
    assert status == 200 and upd["status"] == "resuelta" and upd["title"] == "x"
    assert call(app, "PATCH", "/api/incidents/" + "0" * 32, {"status": "resuelta"})[0] == 404
    assert call(app, "PATCH", f"/api/incidents/{inc['id']}", {"status": "nope"})[0] == 400


def test_triage_failure_still_saves(app):
    class Boom:
        def invoke_harness(self, **_):
            raise RuntimeError("sin modelo")

    app._runtime = Boom()
    status, inc = call(app, "POST", "/api/incidents", {"title": "x"})
    assert status == 201 and inc["severity"] == "sin_clasificar"
    assert len(call(app, "GET", "/api/incidents")[1]) == 1


def test_triage_garbage_reply(app):
    class Junk:
        def invoke_harness(self, **_):
            return {"stream": local.FakeStream("no es json")}

    app._runtime = Junk()
    _, inc = call(app, "POST", "/api/incidents", {"title": "x"})
    assert inc["severity"] == "sin_clasificar" and inc["next_steps"] == []


def test_validation(app):
    assert call(app, "POST", "/api/incidents", {"title": "  "})[0] == 400
    assert call(app, "POST", "/api/chat", {"message": ""})[0] == 400
    assert call(app, "POST", "/api/chat", {"message": "x" * 2001})[0] == 400
    assert call(app, "POST", "/api/chat", {"message": "hi", "session_id": "corto"})[0] == 400
    r = app.handler({"requestContext": {"http": {"method": "POST"}}, "rawPath": "/api/chat",
                     "body": "{no"}, None)
    assert r["statusCode"] == 400
    assert call(app, "GET", "/nada")[0] == 404


def test_chat_includes_only_open_incidents(app):
    seen = {}

    class Spy:
        def invoke_harness(self, harnessArn, runtimeSessionId, messages):
            seen["text"] = messages[0]["content"][0]["text"]
            seen["sid"] = runtimeSessionId
            return {"stream": local.FakeStream("ok")}

    call(app, "POST", "/api/incidents", {"title": "ABIERTA-UNO"})
    _, b = call(app, "POST", "/api/incidents", {"title": "CERRADA-DOS"})
    call(app, "PATCH", f"/api/incidents/{b['id']}", {"status": "resuelta"})
    app._runtime = Spy()
    status, out = call(app, "POST", "/api/chat", {"message": "¿qué atiendo?"})
    assert status == 200 and out["reply"] == "ok" and len(out["session_id"]) >= 33
    assert "ABIERTA-UNO" in seen["text"] and "CERRADA-DOS" not in seen["text"]
    assert seen["sid"] == out["session_id"]


def test_chat_error_exposes_only_class(app):
    class Boom:
        def invoke_harness(self, **_):
            raise PermissionError("secreto interno")

    app._runtime = Boom()
    status, out = call(app, "POST", "/api/chat", {"message": "hola"})
    assert status == 502 and out == {"error": "PermissionError"}


def test_harness_arn_lookup_by_name(app):
    class Ctl:
        def get_paginator(self, _):
            return self

        def paginate(self):
            return [{"harnesses": [{"harnessName": "otro", "arn": "A"},
                                   {"harnessName": "local", "arn": "B"}]}]

    app._arn, app._control = None, Ctl()
    assert app.harness_arn() == "B" and app.harness_arn() == "B"  # cacheado
    app._arn, app.HARNESS_NAME = None, "falta"
    try:
        app.harness_arn()
        raise AssertionError("debía fallar")
    except RuntimeError as e:
        assert "falta" in str(e)
