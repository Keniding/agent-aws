"""Disparador «pre sign-up» de Cognito: solo deja registrarse a los correos o dominios autorizados.

ALLOWED_SIGNUPS = lista separada por comas de correos exactos («ana@empresa.com») o dominios («@empresa.com»).
Vacía = nadie puede registrarse por su cuenta (los usuarios dados de alta por un administrador siguen valiendo).
El correo debe verificarse con un código antes de poder entrar (no se autoconfirma).
"""

import os


def allowed(email: str, rules: str) -> bool:
    email = email.strip().lower()
    for rule in (r.strip().lower() for r in rules.split(",")):
        if rule and (email == rule or (rule.startswith("@") and email.endswith(rule) and email.count("@") == 1)):
            return True
    return False


def handler(event, _context):
    source = event.get("triggerSource", "")
    if source == "PreSignUp_AdminCreateUser":
        return event  # lo creó un administrador: ya está autorizado
    email = (event.get("request", {}).get("userAttributes", {}).get("email") or "")
    if source != "PreSignUp_SignUp" or not allowed(email, os.environ.get("ALLOWED_SIGNUPS", "")):
        raise Exception("Tu correo no está autorizado para registrarse.")  # noqa: TRY002 - Cognito muestra este texto
    event["response"]["autoConfirmUser"] = False
    event["response"]["autoVerifyEmail"] = False  # se verifica con el código que envía Cognito
    return event
