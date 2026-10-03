"""Prueba de humo contra el despliegue REAL (no usa dobles): login con Cognito, sesión, agente, cabeceras y salida.

Crea un usuario TEMPORAL en el pool (sin enviar ningún correo), lo usa con un navegador (Playwright) y lo borra al
terminar. No modifica incidencias: solo hace consultas al agente. En órdenes de cambio crea UNA orden de prueba, la
cancela y la borra al final (con las credenciales del administrador, porque la app no puede borrar).

Uso:   uv run --with "botocore[crt]" scripts/smoke_live.py [--stack incidencias] [--region us-east-2] [--ask "..."]
Requiere: credenciales de AWS con permisos de Cognito (admin-create-user/delete-user) y CloudFormation de solo lectura,
          y `uv run playwright install chromium`.
Sale con código 1 si alguna comprobación falla.
"""

import argparse
import json
import secrets
import string
import subprocess
import sys
import urllib.error
import urllib.request

from playwright.sync_api import sync_playwright

FALLOS: list[str] = []


def comprobar(ok: bool, texto: str) -> None:
    print(("  ✓ " if ok else "  ✗ ") + texto)
    if not ok:
        FALLOS.append(texto)


def aws(region: str, *args: str) -> str:
    out = subprocess.run(["aws", *args, "--region", region], capture_output=True, text=True, check=True)
    return out.stdout


def salida_pila(region: str, stack: str, clave: str) -> str:
    q = f"Stacks[0].Outputs[?OutputKey=='{clave}'].OutputValue"
    return aws(region, "cloudformation", "describe-stacks", "--stack-name", stack, "--query", q, "--output", "text").strip()


def http(url: str, method: str = "GET", headers: dict | None = None):
    """(estado, cabeceras en minúsculas) sin seguir redirecciones."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *_a, **_k):
            return None

    req = urllib.request.Request(url, method=method, headers=headers or {}, data=b"" if method == "POST" else None)
    try:
        r = urllib.request.build_opener(NoRedirect).open(req, timeout=30)
        return r.status, {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stack", default="incidencias")
    ap.add_argument("--region", default="us-east-2")
    ap.add_argument("--ask", default="Dame un resumen breve del estado actual de las incidencias.")
    a = ap.parse_args()

    url = salida_pila(a.region, a.stack, "WebUrl").rstrip("/")
    pool = salida_pila(a.region, a.stack, "UserPoolId")
    print(f"Despliegue: {url}\nPool: {pool}\n")

    print("Sin sesión (no debe servirse nada):")
    estado, cab = http(url + "/")
    comprobar(estado == 302 and cab.get("location", "").endswith("/auth/login"), "/ redirige al login")
    for ruta in ("/api/incidents", "/api/me"):
        comprobar(http(url + ruta)[0] == 401, f"GET {ruta} -> 401")
    comprobar(http(url + "/api/incidents", "POST")[0] == 401, "POST /api/incidents -> 401")
    comprobar(http(url + "/auth/logout")[0] == 405, "GET /auth/logout -> 405 (el cierre es POST)")
    comprobar(http(url + "/auth/logout", "POST", {"sec-fetch-site": "cross-site"})[0] == 403, "POST /auth/logout cross-site -> 403")
    for nombre, valor in (("x-content-type-options", "nosniff"), ("x-frame-options", "DENY")):
        comprobar(cab.get(nombre) == valor, f"cabecera {nombre}: {valor}")
    comprobar("frame-ancestors 'none'" in cab.get("content-security-policy", ""), "cabecera CSP con frame-ancestors")
    comprobar(cab.get("strict-transport-security", "").startswith("max-age="), "cabecera HSTS")

    comprobar(http(url + "/api/oc")[0] == 401, "GET /api/oc -> 401")
    ordenes: list[str] = []
    correo = f"humo-{secrets.token_hex(4)}@example.com"
    clave = "Aa1-" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))
    aws(a.region, "cognito-idp", "admin-create-user", "--user-pool-id", pool, "--username", correo,
        "--message-action", "SUPPRESS", "--user-attributes", f"Name=email,Value={correo}", "Name=email_verified,Value=true")
    aws(a.region, "cognito-idp", "admin-set-user-password", "--user-pool-id", pool, "--username", correo,
        "--password", clave, "--permanent")
    try:
        print("\nCon sesión (usuario temporal):")
        with sync_playwright() as p:
            nav = p.chromium.launch()
            pg = nav.new_context(viewport={"width": 1280, "height": 900}).new_page()
            pg.goto(url + "/")
            pg.wait_for_url("**amazoncognito.com/**", timeout=30000)
            comprobar(True, "sin sesión, la web lleva al login de Cognito")
            f = pg.locator("form[name=cognitoSignInForm]:visible").first
            f.locator("input[name=username]").fill(correo)
            f.locator("input[name=password]").fill(clave)
            f.locator("input[name=signInSubmitButton]").click()
            pg.wait_for_url(url + "/", timeout=30000)
            pg.locator("#agentcard").wait_for(timeout=30000)
            comprobar(True, "tras el login se entra a la app")
            me = pg.evaluate("fetch('/api/me').then(r => r.json())")
            comprobar(me.get("email") == correo and me.get("local") is False, "/api/me devuelve la persona autenticada")
            ck = {c["name"]: c for c in pg.context.cookies()}.get("__Host-session", {})
            comprobar(bool(ck.get("httpOnly") and ck.get("secure") and ck.get("sameSite") == "Lax"),
                      "cookie de sesión HttpOnly + Secure + SameSite=Lax")
            comprobar("__Host-session" not in pg.evaluate("document.cookie"), "el JavaScript no puede leer la cookie")
            comprobar(pg.evaluate("fetch('/api/incidents').then(r => r.status)") == 200, "GET /api/incidents -> 200")
            r = pg.evaluate("fetch('/api/chat',{method:'POST',headers:{'content-type':'application/json'},"
                            "body:JSON.stringify({message:" + json.dumps(a.ask) + "})})"
                            ".then(async r => ({s:r.status, j:await r.json()}))")
            comprobar(r["s"] == 200 and bool(r["j"].get("reply")), "el agente responde")
            print(f"    respuesta del agente: {r['j'].get('reply', '')[:160]!r}  acciones: {r['j'].get('actions')}")
            print("\nÓrdenes de cambio (se crea una orden de prueba y se borra al final):")
            api = ("(async([m,p,b])=>{const r=await fetch(p,{method:m,headers:{'content-type':'application/json'},"
                   "body:b?JSON.stringify(b):undefined});return {s:r.status,j:await r.json()}})")
            comprobar(pg.evaluate(api + "(['GET','/api/oc'])")["s"] == 200, "GET /api/oc -> 200")
            o = pg.evaluate(api + "(['POST','/api/oc',{tipo:'modificar_valor',titulo:'Orden de prueba (humo)',"
                            "servicio:'Lambda',parametro:'MemorySize',valor_actual:'256',valor_propuesto:'512'}])")
            oc_id = o["j"].get("id")
            ordenes.append(oc_id)
            comprobar(o["s"] == 201 and o["j"].get("solicitante") == correo, "una persona registra una orden: queda su correo")
            sin_evaluar = pg.evaluate(api + f"(['POST','/api/oc/{oc_id}/mover',{{a:'aprobada'}}])")
            comprobar(sin_evaluar["s"] == 400, "no se puede aprobar sin evaluar -> 400")
            r = pg.evaluate("fetch('/api/chat',{method:'POST',headers:{'content-type':'application/json'},"
                            "body:JSON.stringify({track:'oc',message:'Consulta con tus herramientas qué órdenes hay "
                            "abiertas y dime el estado de la orden de prueba (humo).'})}).then(async r => ({s:r.status, j:await r.json()}))")
            herramientas = [x["tool"] for x in r["j"].get("actions", [])]
            comprobar(r["s"] == 200 and bool(r["j"].get("reply")), "el agente del módulo responde")
            comprobar(any(t in ("listar_oc", "consultar_oc") for t in herramientas),
                      f"el agente usa las herramientas del gateway: {herramientas}")
            fin = pg.evaluate(api + f"(['POST','/api/oc/{oc_id}/mover',{{a:'cancelada',nota:'prueba de humo'}}])")
            comprobar(fin["s"] == 200 and fin["j"]["estado"] == "cancelada", "la persona cancela la orden con motivo")
            pg.locator("#out").click()
            pg.wait_for_url("**/auth/signed-out", timeout=30000)
            comprobar(True, "«Salir» (POST) cierra la sesión y pasa por Cognito")
            comprobar(pg.evaluate("fetch('/api/incidents').then(r => r.status)") == 401, "tras salir, la API da 401")
            nav.close()
    finally:
        aws(a.region, "cognito-idp", "admin-delete-user", "--user-pool-id", pool, "--username", correo)
        print("\nUsuario temporal eliminado.")
        if ordenes:  # la app no puede borrar órdenes (a propósito): se limpian con credenciales de administrador
            tabla = aws(a.region, "cloudformation", "describe-stack-resource", "--stack-name", a.stack,
                        "--logical-resource-id", "ChangeOrdersTable", "--query",
                        "StackResourceDetail.PhysicalResourceId", "--output", "text").strip()
            for oc_id in ordenes:
                aws(a.region, "dynamodb", "delete-item", "--table-name", tabla, "--key", json.dumps({"id": {"S": oc_id}}))
            print(f"{len(ordenes)} orden(es) de prueba eliminada(s).")
    print("\nTODO CORRECTO" if not FALLOS else f"\nFALLARON {len(FALLOS)} comprobaciones:\n  - " + "\n  - ".join(FALLOS))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
