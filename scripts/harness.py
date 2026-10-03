"""Create/update (or delete) the AgentCore harness. Idempotent.

Usage: uv run scripts/harness.py up|down
Env:   HARNESS_NAME, HARNESS_ROLE_ARN (up only); MODEL_ID, API_FORMAT optional
       (default: nvidia.nemotron-nano-9b-v2 via Bedrock Mantle, chat_completions)
       OC_GATEWAY_ARN, SKILLS_URI optional: módulo de órdenes de cambio (gateway «oc» + habilidad gestion-oc)
"""

import os
import sys
import time

import boto3

name = os.environ["HARNESS_NAME"]
c = boto3.client("bedrock-agentcore-control")


def find():
    for page in c.get_paginator("list_harnesses").paginate():
        for h in page["harnesses"]:
            if h["harnessName"] == name:
                return h
    return None


def wait(harness_id, done):
    while True:
        h = c.get_harness(harnessId=harness_id)["harness"]
        print("status:", h["status"])
        if h["status"] in done:
            return h
        if h["status"].endswith("FAILED"):
            sys.exit(h.get("failureReason", "failed"))
        time.sleep(5)


def up():
    spec = {
        "executionRoleArn": os.environ["HARNESS_ROLE_ARN"],
        "model": {"bedrockModelConfig": {
            "modelId": os.environ.get("MODEL_ID") or "nvidia.nemotron-nano-9b-v2",
            "apiFormat": os.environ.get("API_FORMAT") or "chat_completions",
        }},
        "systemPrompt": [{"text": "Eres un agente que gestiona un sistema de incidencias de TI. No te limites a opinar: actúa con tus herramientas. Si el usuario describe un problema o pide registrar algo, llama de inmediato a crear_incidencia: el id lo genera el sistema, deduce tú título, severidad, categoría, resumen y pasos, y NUNCA pidas al usuario un id ni más datos. Usa listar_incidencias para ver el estado real antes de responder sobre incidencias, clasificar_incidencia para guardar la clasificación de una incidencia nueva y cambiar_estado cuando el usuario o el flujo lo pida. Nunca inventes ids ni incidencias: usa solo las que figuren en «Estado actual» o que devuelva listar_incidencias, y no uses lo que recuerdes de conversaciones anteriores. Si te preguntan por cantidades o estados, cuéntalos desde esa lista. Responde en español, breve y concreto, sin repetir tu razonamiento."}],
        "maxIterations": 10,
        "timeoutSeconds": 100,
    }
    # Órdenes de cambio: herramientas serverless detrás de AgentCore Gateway y habilidad (SKILL.md) en S3.
    # Si no hay gateway (despliegue sin el módulo), el harness queda solo con las funciones en línea de la app.
    if os.environ.get("OC_GATEWAY_ARN"):
        spec["tools"] = [{"type": "agentcore_gateway", "name": "oc", "config": {"agentCoreGateway": {
            "gatewayArn": os.environ["OC_GATEWAY_ARN"], "outboundAuth": {"awsIam": {}}}}}]
        spec["systemPrompt"][0]["text"] += (
            " Además hay un módulo de ÓRDENES DE CAMBIO (OC) de servicios de AWS: cuando te hablen de él, usa la "
            "habilidad gestion-oc y las herramientas del gateway «oc»; nunca apruebes ni cierres una orden.")
    if os.environ.get("SKILLS_URI"):
        spec["skills"] = [{"s3": {"uri": os.environ["SKILLS_URI"].rstrip("/") + "/gestion-oc/"}}]
    cur = find()
    if cur:
        c.update_harness(harnessId=cur["harnessId"], **spec)
        h = wait(cur["harnessId"], {"READY"})
    else:
        h = c.create_harness(harnessName=name, **spec)["harness"]
        h = wait(h["harnessId"], {"READY"})
    print("harness arn:", h["arn"])


def down():
    cur = find()
    if cur:
        c.delete_harness(harnessId=cur["harnessId"])
        print("deleting", cur["harnessId"])


{"up": up, "down": down}[sys.argv[1]]()
