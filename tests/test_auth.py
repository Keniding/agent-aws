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
    cookie, p, r = login(secured)
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


def test_logout_clears_session_and_cognito_session(secured):
    r = secured.handler(ev("GET", "/auth/logout"), None)
    loc = urllib.parse.urlparse(r["headers"]["location"])
    q = {k: v[0] for k, v in urllib.parse.parse_qs(loc.query).items()}
    assert loc.path == "/logout" and q == {"client_id": CLIENT, "logout_uri": f"https://{HOST}/auth/signed-out"}
    assert any(c.startswith(auth.SESSION_COOKIE + "=;") and "Max-Age=0" in c for c in r["cookies"])
    assert secured.handler(ev("GET", "/auth/signed-out"), None)["statusCode"] == 200


def test_auth_routes_only_accept_get(secured):
    assert secured.handler(ev("POST", "/auth/login"), None)["statusCode"] == 405


def test_local_mode_has_no_login(app):
    r = app.handler(ev("GET", "/api/me"), None)
    assert json.loads(r["body"])["local"] is True
