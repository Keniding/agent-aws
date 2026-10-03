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
    assert inc["severity"] == "critica" and inc["status"] == "en_curso"  # el agente la pasó a en_curso
    assert [a["tool"] for a in inc["actions"]] == ["clasificar_incidencia", "cambiar_estado"]
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


def test_chat_agent_lists_only_open_incidents(app):
    """El agente pide listar_incidencias y recibe solo las abiertas; la app le devuelve el resultado."""
    seen = {}

    class Spy:
        def __init__(self):
            self.n = 0

        def invoke_harness(self, harnessArn, runtimeSessionId, messages, tools=None):
            self.n += 1
            seen["tools"] = [t["name"] for t in tools]
            if self.n == 1:
                return {"stream": local.FakeToolStream("listar_incidencias", {})}
            seen["result"] = messages[0]["content"][0]["toolResult"]
            return {"stream": local.FakeStream("ok")}

    call(app, "POST", "/api/incidents", {"title": "ABIERTA-UNO"})
    _, b = call(app, "POST", "/api/incidents", {"title": "CERRADA-DOS"})
    call(app, "PATCH", f"/api/incidents/{b['id']}", {"status": "resuelta"})
    app._runtime = Spy()
    status, out = call(app, "POST", "/api/chat", {"message": "¿qué atiendo?"})
    assert status == 200 and out["reply"] == "ok" and len(out["session_id"]) >= 33
    assert out["actions"] == [{"tool": "listar_incidencias", "ok": True}]
    res = seen["result"]
    assert res["status"] == "success" and "content" in res and "json" not in res["content"][0]
    assert "ABIERTA-UNO" in res["content"][0]["text"] and "CERRADA-DOS" not in res["content"][0]["text"]
    assert seen["tools"] == ["listar_incidencias", "clasificar_incidencia", "cambiar_estado"]


def test_agent_tool_errors_go_back_to_the_agent(app):
    """Entrada inválida del modelo no rompe nada: el error vuelve como toolResult de error."""
    seen = []

    class Bad:
        def __init__(self):
            self.n = 0

        def invoke_harness(self, harnessArn, runtimeSessionId, messages, tools=None):
            self.n += 1
            if self.n == 1:
                return {"stream": local.FakeToolStream("clasificar_incidencia", {
                    "id": "0" * 32, "severidad": "apocaliptica", "categoria": "x", "resumen": "y"})}
            if self.n == 2:
                seen.append(messages[0]["content"][0]["toolResult"])
                return {"stream": local.FakeToolStream("cambiar_estado", {"id": "no", "estado": "x"})}
            seen.append(messages[0]["content"][0]["toolResult"])
            return {"stream": local.FakeStream("fin")}

    app._runtime = Bad()
    status, out = call(app, "POST", "/api/chat", {"message": "haz algo raro"})
    assert status == 200 and out["reply"] == "fin"
    assert [s["status"] for s in seen] == ["error", "error"]
    assert out["actions"] == [{"tool": "clasificar_incidencia", "ok": False},
                              {"tool": "cambiar_estado", "ok": False}]


def test_agent_loop_is_bounded(app):
    class Loop:
        n = 0

        def invoke_harness(self, **_):
            Loop.n += 1
            return {"stream": local.FakeToolStream("listar_incidencias", {})}

    app._runtime = Loop()
    status, _ = call(app, "POST", "/api/chat", {"message": "bucle"})
    assert status == 200 and Loop.n == app.MAX_STEPS


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
