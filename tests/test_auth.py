"""Autenticación con Cognito: flujo OIDC (código + PKCE) con el proveedor simulado y casos de rechazo."""

import json
import time
import urllib.parse

import pytest

import auth

HOST = "abc123.lambda-url.us-east-2.on.aws"
POOL, CLIENT = "us-east-2_AbCdEf", "client123"
ISS = f"https://cognito-idp.us-east-2.amazonaws.com/{POOL}"


def ev(method, path, body=None, cookies=None, query=None, headers=None):
    return {"requestContext": {"http": {"method": method}, "domainName": HOST}, "rawPath": path,
            "body": json.dumps(body) if body is not None else None, "cookies": cookies or [],
            "queryStringParameters": query, "headers": headers or {}}


@pytest.fixture
def secured(app, monkeypatch):
    """La app real con la autenticación activada y Cognito configurado (sin red)."""
    monkeypatch.setattr(auth, "DISABLED", False)
    monkeypatch.setattr(auth, "POOL_ID", POOL)
    monkeypatch.setattr(auth, "DOMAIN", "incidencias-123")
    monkeypatch.setattr(auth, "SECRET_ARN", "arn:secret")
    monkeypatch.setattr(auth, "REGION", "us-east-2")
    monkeypatch.setattr(auth, "_secret_cache", "k" * 40)
    monkeypatch.setattr(auth, "_client_id_cache", CLIENT)
    return app


def claims(**over):
    base = {"iss": ISS, "aud": CLIENT, "token_use": "id", "exp": time.time() + 600, "sub": "u-1",
            "email": "Ana@Example.com", "name": "Ana"}
    return {**base, **over}


def jwt(c):
    return "h." + auth._b64(json.dumps(c).encode()) + ".s"


def cookie_value(resp, name):
    for c in resp.get("cookies", []):
        if c.startswith(name + "="):
            return c.split(";")[0]
    raise AssertionError(f"sin cookie {name}")


def login(app):
    """Hace /auth/login y devuelve (cookie de login, parámetros enviados a Cognito)."""
    r = app.handler(ev("GET", "/auth/login"), None)
    assert r["statusCode"] == 302
    url = urllib.parse.urlparse(r["headers"]["location"])
    return cookie_value(r, auth.LOGIN_COOKIE), {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}, r


def finish(app, monkeypatch, id_claims, state=None, tamper=False):
    """Completa el callback con un id_token dado (nonce/estado correctos salvo que se indique)."""
    cookie, params, _ = login(app)
    id_claims = {**id_claims}
    if id_claims.get("nonce") is None:
        id_claims["nonce"] = params["nonce"]
    monkeypatch.setattr(auth, "_exchange", lambda code, verifier, redirect_uri: {"id_token": jwt(id_claims)})
    return app.handler(ev("GET", "/auth/callback", cookies=[cookie],
                          query={"code": "abc", "state": state or params["state"]}), None)


def test_without_session_everything_is_closed(secured):
    r = secured.handler(ev("GET", "/"), None)
    assert r["statusCode"] == 302 and r["headers"]["location"] == "/auth/login"
    for method, path in [("GET", "/api/incidents"), ("POST", "/api/incidents"), ("POST", "/api/chat"),
                         ("PATCH", "/api/incidents/" + "0" * 32), ("GET", "/api/me")]:
        assert secured.handler(ev(method, path, {}), None)["statusCode"] == 401, (method, path)


def test_not_configured_fails_closed(secured, monkeypatch):
    monkeypatch.setattr(auth, "POOL_ID", "")
    for path in ("/", "/api/incidents", "/auth/login"):
        assert secured.handler(ev("GET", path), None)["statusCode"] == 503


def test_login_redirects_to_cognito_with_pkce(secured):
    _cookie, p, r = login(secured)
    assert r["headers"]["location"].startswith("https://incidencias-123.auth.us-east-2.amazoncognito.com/oauth2/authorize?")
    assert p["client_id"] == CLIENT and p["response_type"] == "code" and p["code_challenge_method"] == "S256"
    assert p["redirect_uri"] == f"https://{HOST}/auth/callback" and len(p["state"]) >= 16 and p["nonce"]
    flags = next(c for c in r["cookies"] if c.startswith(auth.LOGIN_COOKIE))
    assert all(f in flags for f in ("HttpOnly", "Secure", "SameSite=Lax", "Path=/"))
    assert "Domain" not in flags  # prefijo __Host-


def test_full_login_then_access(secured, monkeypatch):
    seen = {}
    cookie, params, _ = login(secured)
    monkeypatch.setattr(auth, "_exchange", lambda code, verifier, redirect_uri: seen.update(
        code=code, verifier=verifier, redirect_uri=redirect_uri) or {"id_token": jwt(claims(nonce=params["nonce"]))})
    r = secured.handler(ev("GET", "/auth/callback", cookies=[cookie],
                           query={"code": "abc", "state": params["state"]}), None)
    assert r["statusCode"] == 302 and r["headers"]["location"] == "/"
    # PKCE: el verificador enviado a Cognito corresponde al desafío del paso 1
    assert auth._b64(__import__("hashlib").sha256(seen["verifier"].encode()).digest()) == params["code_challenge"]
    assert seen["redirect_uri"] == f"https://{HOST}/auth/callback"
    sess = cookie_value(r, auth.SESSION_COOKIE)
    flags = next(c for c in r["cookies"] if c.startswith(auth.SESSION_COOKIE))
    assert all(f in flags for f in ("HttpOnly", "Secure", "SameSite=Lax"))
    assert any(c.startswith(auth.LOGIN_COOKIE + "=;") for c in r["cookies"])  # el ticket de login se borra

    ok = secured.handler(ev("GET", "/api/incidents", cookies=[sess]), None)
    assert ok["statusCode"] == 200
    me = json.loads(secured.handler(ev("GET", "/api/me", cookies=[sess]), None)["body"])
    assert me == {"name": "Ana", "email": "ana@example.com", "local": False}
    assert secured.handler(ev("GET", "/", cookies=[sess]), None)["statusCode"] == 200


@pytest.mark.parametrize("over", [
    {"aud": "otro-cliente"}, {"iss": "https://evil.example.com/x"}, {"token_use": "access"},
    {"nonce": "otro-nonce"}, {"exp": time.time() - 5},
])
def test_invalid_token_claims_are_rejected(secured, monkeypatch, over):
    r = finish(secured, monkeypatch, claims(**over))
    assert r["statusCode"] == 403 and not any(c.startswith(auth.SESSION_COOKIE + "=") and "Max-Age=0" not in c
                                               for c in r.get("cookies", []))


def test_state_mismatch_and_missing_ticket(secured, monkeypatch):
    assert finish(secured, monkeypatch, claims(), state="forjado")["statusCode"] == 403
    r = secured.handler(ev("GET", "/auth/callback", query={"code": "abc", "state": "x"}), None)
    assert r["statusCode"] == 403  # sin cookie de login (callback no iniciado por esta app)


def test_exchange_failure_is_denied_without_leaking(secured, monkeypatch, capsys):
    cookie, params, _ = login(secured)

    def boom(*_):
        raise RuntimeError("tok3n-secreto")

    monkeypatch.setattr(auth, "_exchange", boom)
    r = secured.handler(ev("GET", "/auth/callback", cookies=[cookie],
                           query={"code": "abc", "state": params["state"]}), None)
    assert r["statusCode"] == 403 and "tok3n" not in r["body"] and "tok3n" not in capsys.readouterr().out


def test_provider_error_is_denied(secured):
    cookie, params, _ = login(secured)
    r = secured.handler(ev("GET", "/auth/callback", cookies=[cookie],
                           query={"error": "access_denied", "state": params["state"]}), None)
    assert r["statusCode"] == 403


def test_tampered_or_expired_session_is_rejected(secured):
    good = auth.sign({"sub": "u", "name": "n", "email": "e", "exp": time.time() + 60})
    old = auth.sign({"sub": "u", "exp": time.time() - 1})
    for token in (good[:-2] + "xx", "no.es.valida", old, good.split(".")[0] + "." + good.split(".")[0]):
        r = secured.handler(ev("GET", "/api/incidents", cookies=[f"{auth.SESSION_COOKIE}={token}"]), None)
        assert r["statusCode"] == 401, token
    assert secured.handler(ev("GET", "/api/incidents", cookies=[f"{auth.SESSION_COOKIE}={good}"]), None)["statusCode"] == 200


def test_session_signed_with_another_key_is_rejected(secured, monkeypatch):
    token = auth.sign({"sub": "u", "exp": time.time() + 60})
    monkeypatch.setattr(auth, "_secret_cache", "otra-clave-" * 4)
    assert secured.handler(ev("GET", "/api/incidents", cookies=[f"{auth.SESSION_COOKIE}={token}"]), None)["statusCode"] == 401


def test_cross_origin_writes_are_blocked(secured):
    sess = f"{auth.SESSION_COOKIE}=" + auth.sign({"sub": "u", "exp": time.time() + 60})
    evil = secured.handler(ev("POST", "/api/incidents", {"title": "x"}, cookies=[sess],
                              headers={"origin": "https://evil.example.com"}), None)
    assert evil["statusCode"] == 403
    mine = secured.handler(ev("POST", "/api/incidents", {"title": "x"}, cookies=[sess],
                              headers={"origin": f"https://{HOST}"}), None)
    assert mine["statusCode"] == 201


def test_logout_is_a_post_that_clears_the_session_and_returns_the_cognito_logout_url(secured):
    sess = f"{auth.SESSION_COOKIE}=" + auth.sign({"sub": "u", "exp": time.time() + 60})
    r = secured.handler(ev("POST", "/auth/logout", cookies=[sess]), None)
    assert r["statusCode"] == 200
    loc = urllib.parse.urlparse(json.loads(r["body"])["url"])
    q = {k: v[0] for k, v in urllib.parse.parse_qs(loc.query).items()}
    assert loc.path == "/logout" and q == {"client_id": CLIENT, "logout_uri": f"https://{HOST}/auth/signed-out"}
    assert any(c.startswith(auth.SESSION_COOKIE + "=;") and "Max-Age=0" in c for c in r["cookies"])
    assert secured.handler(ev("GET", "/auth/signed-out"), None)["statusCode"] == 200


def test_logout_cannot_be_triggered_with_a_get_or_cross_site(secured):
    """OWASP CSRF: nada que cambie estado con GET; y el POST exige origen propio."""
    assert secured.handler(ev("GET", "/auth/logout"), None)["statusCode"] == 405
    for h in ({"sec-fetch-site": "cross-site"}, {"origin": "https://evil.example.com"}):
        assert secured.handler(ev("POST", "/auth/logout", headers=h), None)["statusCode"] == 403


@pytest.mark.parametrize("path", ["/auth/login", "/auth/callback", "/auth/signed-out"])
def test_other_auth_routes_only_accept_get(secured, path):
    assert secured.handler(ev("POST", path), None)["statusCode"] == 405


@pytest.mark.parametrize("site,expected", [
    ("same-origin", 201), ("none", 201), (None, 201),  # nuestra web, acción directa y navegadores sin la cabecera
    ("cross-site", 403), ("same-site", 403),  # same-site también: en *.on.aws puede ser otro inquilino
])
def test_fetch_metadata_is_enforced_on_writes(secured, site, expected):
    """OWASP: Sec-Fetch-Site es la defensa moderna más útil contra CSRF en peticiones no seguras."""
    sess = f"{auth.SESSION_COOKIE}=" + auth.sign({"sub": "u", "exp": time.time() + 60})
    headers = {"sec-fetch-site": site} if site else {}
    r = secured.handler(ev("POST", "/api/incidents", {"title": "x"}, cookies=[sess], headers=headers), None)
    assert r["statusCode"] == expected


def test_reads_are_not_blocked_by_fetch_metadata(secured):
    sess = f"{auth.SESSION_COOKIE}=" + auth.sign({"sub": "u", "exp": time.time() + 60})
    r = secured.handler(ev("GET", "/api/incidents", cookies=[sess], headers={"sec-fetch-site": "cross-site"}), None)
    assert r["statusCode"] == 200  # las lecturas son seguras; el navegador además impide que otra web lea la respuesta


def test_security_headers_are_on_every_response(secured):
    sess = f"{auth.SESSION_COOKIE}=" + auth.sign({"sub": "u", "exp": time.time() + 60, "name": "n"})
    responses = [secured.handler(ev("GET", "/"), None),                                   # redirección al login
                 secured.handler(ev("GET", "/", cookies=[sess]), None),                   # la web
                 secured.handler(ev("GET", "/api/me", cookies=[sess]), None),             # API
                 secured.handler(ev("GET", "/api/incidents"), None),                      # 401
                 secured.handler(ev("GET", "/auth/login"), None),                         # login
                 secured.handler(ev("GET", "/auth/signed-out"), None)]                    # página de auth
    for r in responses:
        h = {k.lower(): v for k, v in r["headers"].items()}
        assert h["x-content-type-options"] == "nosniff" and h["x-frame-options"] == "DENY"
        assert "frame-ancestors 'none'" in h["content-security-policy"] and "base-uri 'none'" in h["content-security-policy"]
        assert h["referrer-policy"] == "strict-origin-when-cross-origin" and h["cache-control"] == "no-store"
        assert h["strict-transport-security"].startswith("max-age=") and h["cross-origin-opener-policy"] == "same-origin"


def test_local_mode_has_no_login(app):
    r = app.handler(ev("GET", "/api/me"), None)
    assert json.loads(r["body"])["local"] is True


@pytest.mark.parametrize("state", ["estado-ñ", "💥", "a" * 5000, "\x00", "%00", "<script>"])
def test_hostile_state_values_are_rejected_without_crashing(secured, state):
    """hmac.compare_digest con str no admite no-ASCII: un `state` raro no debe producir un 500."""
    cookie, _, _ = login(secured)
    r = secured.handler(ev("GET", "/auth/callback", cookies=[cookie], query={"code": "abc", "state": state}), None)
    assert r["statusCode"] == 403


def test_hostile_session_and_login_cookies_never_crash(secured):
    for value in ("ñ.ñ", "💥", "a.b.c", "." * 50, "x" * 8000, "éé"):
        for name in (auth.SESSION_COOKIE, auth.LOGIN_COOKIE):
            r = secured.handler(ev("GET", "/api/incidents", cookies=[f"{name}={value}"]), None)
            assert r["statusCode"] == 401
