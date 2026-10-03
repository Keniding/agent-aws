"""Create/update (or delete) the AgentCore harness. Idempotent.

Usage: uv run scripts/harness.py up|down
Env:   HARNESS_NAME, HARNESS_ROLE_ARN, MODEL_ID (up only)
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
        "model": {"bedrockModelConfig": {"modelId": os.environ["MODEL_ID"]}},
        "systemPrompt": [{"text": "Eres el asistente de un sistema de incidencias de TI. Clasificas severidad, propones próximos pasos y respondes dudas sobre las incidencias abiertas que se te indiquen. Sé breve y concreto; responde en español."}],
        "maxIterations": 10,
        "timeoutSeconds": 100,
    }
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
