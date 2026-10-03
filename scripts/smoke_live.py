"""Prueba de humo contra el despliegue REAL (no usa dobles): login con Cognito, sesión, agente, cabeceras y salida.

Crea un usuario TEMPORAL en el pool (sin enviar ningún correo), lo usa con un navegador (Playwright) y lo borra al
terminar. No modifica incidencias: solo hace consultas al agente.

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
            pg.locator("#out").click()
            pg.wait_for_url("**/auth/signed-out", timeout=30000)
            comprobar(True, "«Salir» (POST) cierra la sesión y pasa por Cognito")
            comprobar(pg.evaluate("fetch('/api/incidents').then(r => r.status)") == 401, "tras salir, la API da 401")
            nav.close()
    finally:
        aws(a.region, "cognito-idp", "admin-delete-user", "--user-pool-id", pool, "--username", correo)
        print("\nUsuario temporal eliminado.")
    print("\nTODO CORRECTO" if not FALLOS else f"\nFALLARON {len(FALLOS)} comprobaciones:\n  - " + "\n  - ".join(FALLOS))
    return 1 if FALLOS else 0


if __name__ == "__main__":
    sys.exit(main())
