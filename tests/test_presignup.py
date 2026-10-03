import pytest

import presignup


def event(email, source="PreSignUp_SignUp"):
    return {"triggerSource": source, "request": {"userAttributes": {"email": email}}, "response": {}}


@pytest.fixture
def rules(monkeypatch):
    monkeypatch.setenv("ALLOWED_SIGNUPS", "ana@empresa.com, @corp.com ,")


@pytest.mark.parametrize("email", ["ana@empresa.com", "ANA@Empresa.com", "luis@corp.com", "x@corp.com "])
def test_allowed_emails_and_domains(rules, email):
    out = presignup.handler(event(email), None)
    assert out["response"] == {"autoConfirmUser": False, "autoVerifyEmail": False}  # exige código de correo


@pytest.mark.parametrize("email", ["otra@empresa.com", "ana@empresa.com.evil.io", "x@sub.corp.com",
                                   "x@evilcorp.com", "a@evil.com@corp.com", "", "corp.com"])
def test_other_emails_are_rejected(rules, email):
    with pytest.raises(Exception, match="no está autorizado"):
        presignup.handler(event(email), None)


def test_empty_list_blocks_every_self_signup(monkeypatch):
    monkeypatch.setenv("ALLOWED_SIGNUPS", "")
    with pytest.raises(Exception, match="no está autorizado"):
        presignup.handler(event("ana@empresa.com"), None)


def test_admin_created_users_pass_even_with_empty_list(monkeypatch):
    monkeypatch.setenv("ALLOWED_SIGNUPS", "")
    ev = event("cualquiera@x.com", "PreSignUp_AdminCreateUser")
    assert presignup.handler(ev, None) is ev


def test_external_providers_are_rejected(rules):
    with pytest.raises(Exception):
        presignup.handler(event("ana@empresa.com", "PreSignUp_ExternalProvider"), None)
