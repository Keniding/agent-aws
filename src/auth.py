"""Inicio de sesión con Amazon Cognito (login alojado, código de autorización + PKCE), sin dependencias.

El id_token llega directamente del endpoint de tokens de Cognito por TLS y el código está ligado al
verificador PKCE, por lo que no hace falta verificar su firma: sí se validan emisor, audiencia, tipo,
nonce y caducidad. La sesión es una cookie firmada con HMAC (__Host-, HttpOnly, Secure, SameSite=Lax).
"""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
import urllib.parse
import urllib.request

DISABLED = os.environ.get("AUTH_DISABLED") == "1"  # solo para desarrollo local y pruebas
POOL_ID = os.environ.get("COGNITO_POOL_ID", "")
DOMAIN = os.environ.get("COGNITO_DOMAIN", "")  # prefijo del dominio del login alojado
CLIENT_NAME = os.environ.get("COGNITO_CLIENT_NAME", "incidencias-web")
SECRET_ARN = os.environ.get("SESSION_SECRET_ARN", "")
REGION = os.environ.get("AWS_REGION", "")
SESSION_TTL = int(os.environ.get("SESSION_HOURS", "8")) * 3600
LOGIN_TTL = 600
SESSION_COOKIE, LOGIN_COOKIE = "__Host-session", "__Host-oidc"
_secret_cache = None
_client_id_cache = None


def configured() -> bool:
    return bool(POOL_ID and DOMAIN and SECRET_ARN and REGION)


def _base() -> str:
    return f"https://{DOMAIN}.auth.{REGION}.amazoncognito.com"


def _session_key() -> str:
    global _secret_cache
    if _secret_cache is None:
        import boto3

        value = boto3.client("secretsmanager").get_secret_value(SecretId=SECRET_ARN)["SecretString"]
        _secret_cache = json.loads(value)["session_key"]
    return _secret_cache


def client_id() -> str:
    """El id del cliente se descubre en ejecución: así la Lambda no depende del cliente en la plantilla."""
    global _client_id_cache
    if _client_id_cache is None:
        import boto3

        clients = boto3.client("cognito-idp").list_user_pool_clients(UserPoolId=POOL_ID, MaxResults=60)
        _client_id_cache = next(c["ClientId"] for c in clients["UserPoolClients"]
                                if c["ClientName"] == CLIENT_NAME)
    return _client_id_cache


def _same(a, b) -> bool:
    """Comparación en tiempo constante (evita ataques de temporización). `hmac.compare_digest` con `str` solo
    admite ASCII y lanza TypeError con otros caracteres (docs de Python): como `state` viene de la URL, se compara
    sobre bytes para que cualquier entrada sea un simple «no coincide»."""
    return hmac.compare_digest(str(a).encode("utf-8"), str(b).encode("utf-8"))


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _mac(body: str) -> str:
    return _b64(hmac.new(_session_key().encode(), body.encode(), hashlib.sha256).digest())


def sign(data: dict) -> str:
    body = _b64(json.dumps(data, separators=(",", ":")).encode())
    return f"{body}.{_mac(body)}"


def verify(token: str):
    """Devuelve el contenido si la firma es válida y no ha caducado; si no, None."""
    try:
        body, mac = token.split(".")
        if not _same(mac, _mac(body)):
            return None
        data = json.loads(_unb64(body))
        return data if data["exp"] > time.time() else None
    except Exception:  # noqa: BLE001 - cualquier cookie manipulada o ilegible equivale a "sin sesión"
        return None


def _cookies(event) -> dict:
    jar = {}
    for c in event.get("cookies") or []:
        name, _, value = c.partition("=")
        jar[name.strip()] = value.strip()
    return jar


def _set_cookie(name, value, max_age) -> str:
    return f"{name}={value}; Max-Age={max_age}; Path=/; HttpOnly; Secure; SameSite=Lax"


def session(event):
    """Usuario de la sesión actual (dict) o None."""
    token = _cookies(event).get(SESSION_COOKIE)
    return verify(token) if token else None


def same_origin(event) -> bool:
    """Defensa en profundidad contra CSRF en peticiones que modifican datos (además de SameSite=Lax).

    OWASP (CSRF Prevention Cheat Sheet): Fetch Metadata es la comprobación moderna más útil (el navegador pone
    `Sec-Fetch-Site` y la página no puede falsearlo); `Origin` cubre navegadores sin Fetch Metadata. Solo se
    admiten `same-origin` (nuestra web) y `none` (acción directa del usuario); `same-site` también se rechaza
    porque en un dominio compartido como *.on.aws un «mismo sitio» puede ser otro inquilino.
    """
    headers = event.get("headers") or {}
    site = headers.get("sec-fetch-site")
    if site is not None and site not in ("same-origin", "none"):
        return False
    origin = headers.get("origin")
    return not origin or urllib.parse.urlparse(origin).netloc == event["requestContext"]["domainName"]


def page(status, title, body, cookies=None) -> dict:
    html = ('<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            f'<title>{title}</title><body style="font:18px/28px Georgia,serif;max-width:32rem;margin:15vh auto;'
            f'padding:0 1rem"><h1 style="font-weight:500">{title}</h1><p>{body}</p>')
    resp = {"statusCode": status,
            "headers": {"content-type": "text/html; charset=utf-8", "cache-control": "no-store"}, "body": html}
    if cookies:
        resp["cookies"] = cookies
    return resp


def redirect(url, cookies=None) -> dict:
    resp = {"statusCode": 302, "headers": {"location": url, "cache-control": "no-store"}, "body": ""}
    if cookies:
        resp["cookies"] = cookies
    return resp


def _origin(event) -> str:
    return f"https://{event['requestContext']['domainName']}"  # lo fija AWS, no el cliente


def _login(event) -> dict:
    state, nonce, verifier = secrets.token_urlsafe(16), secrets.token_urlsafe(16), secrets.token_urlsafe(48)
    query = urllib.parse.urlencode({
        "client_id": client_id(), "response_type": "code", "redirect_uri": _origin(event) + "/auth/callback",
        "scope": "openid email profile", "state": state, "nonce": nonce,
        "code_challenge": _b64(hashlib.sha256(verifier.encode()).digest()), "code_challenge_method": "S256"})
    ticket = sign({"s": state, "n": nonce, "v": verifier, "exp": time.time() + LOGIN_TTL})
    return redirect(f"{_base()}/oauth2/authorize?{query}", [_set_cookie(LOGIN_COOKIE, ticket, LOGIN_TTL)])


def _exchange(code, verifier, redirect_uri) -> dict:
    form = urllib.parse.urlencode({
        "grant_type": "authorization_code", "client_id": client_id(), "code": code,
        "redirect_uri": redirect_uri, "code_verifier": verifier}).encode()
    req = urllib.request.Request(f"{_base()}/oauth2/token", data=form,
                                 headers={"content-type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.load(resp)


def _denied(msg="No se pudo iniciar sesión.") -> dict:
    return page(403, "Acceso denegado", f'{msg} <a href="/auth/login">Intentar de nuevo</a>',
                [_set_cookie(LOGIN_COOKIE, "", 0)])


def _callback(event) -> dict:
    q = event.get("queryStringParameters") or {}
    ticket = verify(_cookies(event).get(LOGIN_COOKIE, ""))
    if not ticket or not q.get("state") or not _same(q["state"], ticket["s"]):
        return _denied("La solicitud de inicio de sesión no es válida o caducó.")
    if q.get("error") or not q.get("code"):
        return _denied("El inicio de sesión no se completó.")
    try:
        tokens = _exchange(q["code"], ticket["v"], _origin(event) + "/auth/callback")
        claims = json.loads(_unb64(tokens["id_token"].split(".")[1]))
    except Exception as exc:  # noqa: BLE001 - nunca se vuelcan tokens ni respuestas del proveedor
        print("auth exchange failed:", type(exc).__name__)
        return _denied()
    ok = (claims.get("iss") == f"https://cognito-idp.{REGION}.amazonaws.com/{POOL_ID}"
          and claims.get("aud") == client_id() and claims.get("token_use") == "id"
          and _same(claims.get("nonce", ""), ticket["n"])
          and claims.get("exp", 0) > time.time())
    if not ok:
        return _denied()
    email = str(claims.get("email", "")).lower()
    user = {"sub": claims.get("sub"), "name": claims.get("name") or email or claims.get("cognito:username"),
            "email": email, "exp": time.time() + SESSION_TTL}
    return redirect("/", [_set_cookie(SESSION_COOKIE, sign(user), SESSION_TTL),
                          _set_cookie(LOGIN_COOKIE, "", 0)])


def _logout(event) -> dict:
    """Borra la cookie de sesión y devuelve la URL de cierre de Cognito (si no se cierra también allí, «volver a
    entrar» sería automático). Es un POST: OWASP exige que nada que cambie estado se haga con GET (evita que otra
    web te cierre la sesión con un simple enlace o imagen). La web navega a la URL devuelta."""
    query = urllib.parse.urlencode({"client_id": client_id(),
                                    "logout_uri": _origin(event) + "/auth/signed-out"})
    return {"statusCode": 200, "headers": {"content-type": "application/json", "cache-control": "no-store"},
            "cookies": [_set_cookie(SESSION_COOKIE, "", 0)],
            "body": json.dumps({"url": f"{_base()}/logout?{query}"})}


def route(event, method, path) -> dict:
    """Rutas /auth/*: login, callback y signed-out (GET) y logout (POST)."""
    if not configured():
        return page(503, "Autenticación no configurada", "Falta configurar Amazon Cognito.")
    if path == "/auth/logout":
        if method != "POST":
            return page(405, "Método no permitido", "Para salir usa el botón «Salir» de la aplicación.")
        if not same_origin(event):
            return page(403, "Origen no permitido", "")
        return _logout(event)
    if method != "GET":
        return page(405, "Método no permitido", "")
    if path == "/auth/login":
        return _login(event)
    if path == "/auth/callback":
        return _callback(event)
    if path == "/auth/signed-out":
        return page(200, "Sesión cerrada", '<a href="/auth/login">Volver a entrar</a>')
    return page(404, "No encontrado", "")
