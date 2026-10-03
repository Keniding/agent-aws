"""Órdenes de cambio (OC): modelo, flujo de estados y persistencia. Lo usan la web (app.py) y las herramientas del
agente (oc_tools.py, detrás de AgentCore Gateway).

El sistema SOLO hace seguimiento: no modifica ningún recurso de AWS. Una OC describe el cambio que alguien pide
(p. ej. subir la memoria de una Lambda) y recorre un flujo con control humano hasta que se ejecuta y se verifica.
"""

import os
import time
import uuid

import boto3

_table = boto3.resource("dynamodb").Table(os.environ["OC_TABLE_NAME"])

TIPOS = {"modificar_valor": "Modificar un valor", "nuevo_recurso": "Solicitar un recurso nuevo"}
RIESGOS = ["baja", "media", "alta"]
ESTADOS = ["solicitada", "evaluada", "aprobada", "programada", "ejecutada", "verificada",
           "rechazada", "cancelada", "revertida"]
TERMINALES = {"verificada", "rechazada", "cancelada", "revertida"}
# Flujo: quién pide -> se evalúa (riesgo, impacto, plan y vuelta atrás) -> una persona aprueba -> se programa ->
# se ejecuta fuera de este sistema -> se verifica. Cualquier paso previo a ejecutar puede cancelarse.
FLUJO = {
    "solicitada": ["evaluada", "rechazada", "cancelada"],
    "evaluada": ["aprobada", "rechazada", "cancelada"],
    "aprobada": ["programada", "cancelada"],
    "programada": ["ejecutada", "cancelada"],
    "ejecutada": ["verificada", "revertida"],
}
ID_LEN = 32
CAMPOS = {"titulo": 200, "servicio": 60, "recurso": 200, "parametro": 100, "valor_actual": 200,
          "valor_propuesto": 200, "justificacion": 1000}


class OcError(ValueError):
    """Error de negocio con un mensaje claro para el usuario."""


def _txt(value, limit) -> str:
    return str(value or "").strip()[:limit]


def crear(datos: dict, por: str) -> dict:
    t = {k: _txt(datos.get(k), n) for k, n in CAMPOS.items()}
    tipo = datos.get("tipo")
    if tipo not in TIPOS:
        raise OcError(f"el tipo debe ser uno de {sorted(TIPOS)}")
    if not t["titulo"] or not t["servicio"]:
        raise OcError("la orden necesita al menos un título y el servicio afectado")
    if tipo == "modificar_valor" and not (t["parametro"] and t["valor_propuesto"]):
        raise OcError("para modificar un valor indica qué parámetro cambia y el valor propuesto")
    ahora = int(time.time())
    item = {"id": uuid.uuid4().hex, "tipo": tipo, **t, "estado": "solicitada", "solicitante": _txt(por, 120),
            "created_at": ahora, "updated_at": ahora, "evaluacion": {},
            "historial": [{"ts": ahora, "de": "", "a": "solicitada", "por": _txt(por, 120), "nota": ""}]}
    _table.put_item(Item=item)
    return item


def obtener(oc_id: str) -> dict:
    if len(str(oc_id)) != ID_LEN:
        raise OcError("id de orden inválido: usa el id de 32 caracteres que devuelve listar_oc")
    item = _table.get_item(Key={"id": str(oc_id)}, ConsistentRead=True).get("Item")
    if not item:
        raise OcError("la orden de cambio no existe")
    return item


def listar(estado: str | None = None) -> list:
    """Todas las órdenes (Scan paginado y consistente: son pocas), de la más reciente a la más antigua."""
    items, kw = [], {"ConsistentRead": True}
    while True:
        page = _table.scan(**kw)
        items += page["Items"]
        if "LastEvaluatedKey" not in page:
            break
        kw["ExclusiveStartKey"] = page["LastEvaluatedKey"]
    if estado:
        items = [i for i in items if i["estado"] == estado]
    return sorted(items, key=lambda i: i["created_at"], reverse=True)


def _aplicar(item: dict, a: str, por: str, nota: str, extra: dict | None = None) -> dict:
    """Cambia de estado con escritura condicional: si alguien movió la orden mientras tanto, falla sin pisarla."""
    ahora = int(time.time())
    sets, vals = ["estado = :a", "updated_at = :t", "historial = list_append(historial, :h)"], {
        ":a": a, ":t": ahora, ":de": item["estado"],
        ":h": [{"ts": ahora, "de": item["estado"], "a": a, "por": _txt(por, 120), "nota": _txt(nota, 500)}]}
    for k, v in (extra or {}).items():
        sets.append(f"{k} = :{k}")
        vals[f":{k}"] = v
    try:
        return _table.update_item(
            Key={"id": item["id"]}, UpdateExpression="SET " + ", ".join(sets),
            ConditionExpression="estado = :de", ExpressionAttributeValues=vals, ReturnValues="ALL_NEW")["Attributes"]
    except _table.meta.client.exceptions.ConditionalCheckFailedException:
        raise OcError("la orden cambió mientras tanto: recarga y vuelve a intentarlo") from None


def evaluar(oc_id: str, ev: dict, por: str) -> dict:
    """solicitada -> evaluada. Exige riesgo, impacto, plan y vuelta atrás: sin ellos nadie puede aprobar."""
    item = obtener(oc_id)
    if item["estado"] != "solicitada":
        raise OcError(f"solo se evalúa una orden «solicitada»; esta está «{item['estado']}»")
    riesgo = ev.get("riesgo")
    if riesgo not in RIESGOS:
        raise OcError(f"el riesgo debe ser uno de {RIESGOS}")
    e = {"riesgo": riesgo, **{k: _txt(ev.get(k), 600) for k in ("impacto", "plan", "rollback")}}
    if not (e["impacto"] and e["plan"] and e["rollback"]):
        raise OcError("la evaluación necesita impacto, plan de ejecución y plan de vuelta atrás")
    return _aplicar(item, "evaluada", por, "", {"evaluacion": e})


def nota(oc_id: str, texto: str, por: str) -> dict:
    item = obtener(oc_id)
    texto = _txt(texto, 500)
    if not texto:
        raise OcError("la nota está vacía")
    ahora = int(time.time())
    return _table.update_item(
        Key={"id": item["id"]}, UpdateExpression="SET historial = list_append(historial, :h), updated_at = :t",
        ExpressionAttributeValues={":h": [{"ts": ahora, "de": item["estado"], "a": item["estado"],
                                           "por": _txt(por, 120), "nota": texto}], ":t": ahora},
        ReturnValues="ALL_NEW")["Attributes"]


def mover(oc_id: str, a: str, por: str, nota_: str = "") -> dict:
    """Transición decidida por una persona (aprobar, rechazar, programar, ejecutar, verificar…)."""
    item = obtener(oc_id)
    if a not in FLUJO.get(item["estado"], []):
        permitido = FLUJO.get(item["estado"], [])
        raise OcError(f"no se puede pasar de «{item['estado']}» a «{a}»"
                      + (f"; desde aquí: {', '.join(permitido)}" if permitido else "; la orden ya está cerrada"))
    if a == "evaluada":
        raise OcError("para evaluar usa la evaluación (riesgo, impacto, plan y vuelta atrás)")
    if a in ("rechazada", "cancelada", "revertida") and not _txt(nota_, 500):
        raise OcError("indica el motivo")
    return _aplicar(item, a, por, nota_)
