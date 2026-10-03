"""Órdenes de cambio: flujo de estados, API web, herramientas del Gateway y módulo del agente."""

import json
import types

import pytest
from test_app import call

EV = {"riesgo": "media", "impacto": "Reinicio de 1 min", "plan": "Subir memoria a 512 MB", "rollback": "Volver a 256 MB"}
OC = {"titulo": "Subir memoria de la Lambda", "tipo": "modificar_valor", "servicio": "Lambda",
      "recurso": "incidencias-Function", "parametro": "MemorySize", "valor_actual": "256",
      "valor_propuesto": "512", "justificacion": "Timeouts en picos"}


def nueva(app, **kw):
    return call(app, "POST", "/api/oc", {**OC, **kw})


def mover(app, oc_id, a, nota=None):
    return call(app, "POST", f"/api/oc/{oc_id}/mover", {"a": a, "nota": nota})


def test_create_and_list(app):
    status, o = nueva(app)
    assert status == 201 and o["estado"] == "solicitada" and o["solicitante"] == "Modo local"
    assert o["historial"][0]["a"] == "solicitada"
    assert [x["id"] for x in call(app, "GET", "/api/oc")[1]] == [o["id"]]


@pytest.mark.parametrize("cambio", [{"tipo": "otro"}, {"titulo": ""}, {"servicio": ""},
                                    {"parametro": ""}, {"valor_propuesto": ""}])
def test_validation_rejects_incomplete_orders(app, cambio):
    status, out = nueva(app, **cambio)
    assert status == 400 and out["error"]


def test_new_resource_does_not_need_a_value(app):
    status, o = nueva(app, tipo="nuevo_recurso", parametro="", valor_propuesto="", titulo="Cola SQS para avisos")
    assert status == 201 and o["tipo"] == "nuevo_recurso"


def test_full_happy_path_with_history(app):
    oc_id = nueva(app)[1]["id"]
    assert call(app, "POST", f"/api/oc/{oc_id}/evaluar", EV)[1]["estado"] == "evaluada"
    for a in ("aprobada", "programada", "ejecutada", "verificada"):
        status, o = mover(app, oc_id, a)
        assert status == 200 and o["estado"] == a
    assert [h["a"] for h in o["historial"]] == ["solicitada", "evaluada", "aprobada", "programada", "ejecutada",
                                                "verificada"]
    assert o["evaluacion"]["riesgo"] == "media"


def test_cannot_skip_steps_and_closed_orders_stay_closed(app):
    oc_id = nueva(app)[1]["id"]
    status, out = mover(app, oc_id, "aprobada")  # sin evaluar no se aprueba
    assert status == 400 and "evaluada" in out["error"]
    assert mover(app, oc_id, "ejecutada")[0] == 400
    assert mover(app, oc_id, "rechazada", "no procede")[0] == 200
    status, out = mover(app, oc_id, "evaluada")
    assert status == 400 and "cerrada" in out["error"]


def test_evaluation_is_required_and_complete(app):
    oc_id = nueva(app)[1]["id"]
    assert call(app, "POST", f"/api/oc/{oc_id}/evaluar", {**EV, "rollback": ""})[0] == 400
    assert call(app, "POST", f"/api/oc/{oc_id}/evaluar", {**EV, "riesgo": "enorme"})[0] == 400
    assert call(app, "POST", f"/api/oc/{oc_id}/evaluar", EV)[0] == 200
    assert call(app, "POST", f"/api/oc/{oc_id}/evaluar", EV)[0] == 400  # ya evaluada
    assert mover(app, oc_id, "evaluada")[0] == 400  # evaluar es una acción propia, no un simple cambio


def test_reject_cancel_and_revert_need_a_reason(app):
    oc_id = nueva(app)[1]["id"]
    assert mover(app, oc_id, "rechazada")[0] == 400
    assert mover(app, oc_id, "cancelada", "   ")[0] == 400
    assert mover(app, oc_id, "cancelada", "ya no hace falta")[1]["estado"] == "cancelada"


def test_stale_state_does_not_overwrite(app):
    """Dos personas actúan a la vez: la segunda escritura falla en vez de pisar a la primera."""
    oc_id = nueva(app)[1]["id"]
    viejo = app.oc.obtener(oc_id)
    assert mover(app, oc_id, "cancelada", "x")[0] == 200
    with pytest.raises(app.oc.OcError, match="cambió mientras tanto"):
        app.oc._aplicar(viejo, "rechazada", "otro", "tarde")
    assert app.oc.obtener(oc_id)["estado"] == "cancelada"


def test_unknown_or_bad_ids(app):
    assert mover(app, "0" * 32, "cancelada", "x")[0] == 400
    assert call(app, "POST", "/api/oc/123/mover", {"a": "x"})[0] == 404  # ruta que no existe


def test_notes_go_to_the_history(app):
    oc_id = nueva(app)[1]["id"]
    status, o = call(app, "POST", f"/api/oc/{oc_id}/nota", {"nota": "Consultado con el equipo de datos"})
    assert status == 200 and o["historial"][-1]["nota"].startswith("Consultado") and o["estado"] == "solicitada"
    assert call(app, "POST", f"/api/oc/{oc_id}/nota", {"nota": " "})[0] == 400


# --- herramientas del agente (Lambda detrás de Gateway) ---
def tool(name, args):
    import oc_tools

    ctx = types.SimpleNamespace(client_context=types.SimpleNamespace(
        custom={"bedrockAgentCoreToolName": "oc___" + name}))
    return oc_tools.handler(args, ctx)


def test_agent_tools_register_evaluate_and_annotate(app):
    o = tool("registrar_oc", OC)
    assert o["estado"] == "solicitada" and "error" not in o
    assert app.oc.obtener(o["id"])["solicitante"] == "agente"
    assert tool("evaluar_oc", {"id": o["id"], **EV})["estado"] == "evaluada"
    assert tool("agregar_nota_oc", {"id": o["id"], "nota": "listo para aprobar"})["estado"] == "evaluada"
    det = tool("consultar_oc", {"id": o["id"]})
    assert det["evaluacion"]["riesgo"] == "media" and [h["por"] for h in det["historial"]] == ["agente"] * 3
    assert [x["id"] for x in tool("listar_oc", {"estado": "evaluada"})["ordenes"]] == [o["id"]]


def test_agent_cannot_approve_or_close(app):
    o = tool("registrar_oc", OC)
    tool("evaluar_oc", {"id": o["id"], **EV})
    for name in ("aprobar_oc", "mover_oc", "cerrar_oc", "programar_oc"):
        assert "desconocida" in tool(name, {"id": o["id"], "a": "aprobada"})["error"]
    assert app.oc.obtener(o["id"])["estado"] == "evaluada"


def test_agent_tool_errors_return_to_the_model(app):
    assert "tipo" in tool("registrar_oc", {**OC, "tipo": "x"})["error"]
    assert "inválido" in tool("consultar_oc", {"id": "abc"})["error"]
    assert "no existe" in tool("consultar_oc", {"id": "0" * 32})["error"]


def test_tool_prefix_is_stripped_whatever_the_target_name(app):
    import oc_tools

    ctx = types.SimpleNamespace(client_context=types.SimpleNamespace(
        custom={"bedrockAgentCoreToolName": "mi-destino___listar_oc"}))
    assert oc_tools.handler({}, ctx) == {"ordenes": []}


# --- módulo del agente en la web ---
def test_oc_chat_only_allows_gateway_tools_and_reports_them(app):
    status, out = call(app, "POST", "/api/chat", {"message": "¿qué órdenes hay?", "track": "oc"})
    assert status == 200 and out["actions"] == [{"tool": "listar_oc", "ok": True}]
    assert app._runtime.last_allowed == ["@oc", "@builtin/skills"]  # gateway y habilidad: ni funciones de incidencias ni shell
    call(app, "POST", "/api/chat", {"message": "hola"})
    assert "@oc" not in app._runtime.last_allowed  # en incidencias el Gateway de OC no está permitido


def test_oc_chat_prompt_names_the_skill_and_lists_open_orders(app):
    seen = {}

    class Spy:
        def invoke_harness(self, harnessArn, runtimeSessionId, messages, **kw):
            seen["text"], seen["kw"] = messages[0]["content"][0]["text"], kw
            return {"stream": [{"contentBlockDelta": {"delta": {"text": "ok"}}},
                               {"messageStop": {"stopReason": "end_turn"}}]}

    oc_id = nueva(app)[1]["id"]
    mover(app, oc_id, "cancelada", "x")
    abierta = nueva(app, titulo="Otra abierta")[1]["id"]
    app._runtime = Spy()
    call(app, "POST", "/api/chat", {"message": "hola", "track": "oc"})
    assert "gestion-oc" in seen["text"] and abierta in seen["text"] and oc_id not in seen["text"]
    assert "tools" not in seen["kw"]


def test_oc_track_is_ignored_when_the_gateway_is_not_configured(app, monkeypatch):
    monkeypatch.setattr(app, "OC_ALLOWED", [])
    call(app, "POST", "/api/chat", {"message": "hola", "track": "oc"})
    assert app._runtime.last_allowed[0] == "@crear_incidencia"


def test_incidents_are_untouched(app):
    nueva(app)
    assert call(app, "GET", "/api/incidents")[1] == []
    assert json.dumps(call(app, "GET", "/api/oc")[1])
