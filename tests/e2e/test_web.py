"""Pruebas de navegador (Chromium) contra scripts/local.py: web + API + DynamoDB simulado."""

import glob
import os

import pytest

import local

sync_api = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def base_url():
    srv, mock = local.serve(0)
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()
    mock.stop()


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        exe = os.environ.get("CHROMIUM_PATH")
        if not exe and not os.path.exists(p.chromium.executable_path):
            # entornos con Chromium preinstalado de otra revisión que la de Playwright
            found = glob.glob(os.path.join(os.environ.get("PLAYWRIGHT_BROWSERS_PATH", ""),
                                           "chromium-*/chrome-linux*/chrome"))
            exe = found[0] if found else None
        b = p.chromium.launch(executable_path=exe or None)
        yield b
        b.close()


@pytest.fixture
def page(browser, base_url):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())  # sin red: cae a fuentes locales
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(base_url)
    yield pg
    assert errors == []
    ctx.close()


def test_full_flow(page):
    page.get_by_label("Título").fill("Caída del servicio de pagos")
    page.get_by_label("Descripción").fill("Timeouts desde las 10:00")
    page.get_by_role("button", name="Registrar y clasificar").click()
    card = page.locator("article.inc").first
    card.wait_for()
    assert "Caída del servicio de pagos" in card.inner_text()
    assert card.locator(".sev").inner_text().lower() == "crítica"
    assert "Revisar logs" in card.inner_text()
    assert "Abiertas 1 // En curso 0 // Resueltas 0" in page.locator("#counts").text_content()

    card.get_by_label("Estado de Caída del servicio de pagos").select_option("en_curso")
    page.wait_for_function("document.querySelector('#counts').textContent.includes('En curso 1')")

    page.get_by_role("button", name="Resueltas").click()
    assert page.locator("article.inc").count() == 0
    page.get_by_role("button", name="En curso").click()
    assert page.locator("article.inc").count() == 1

    page.reload()  # persistencia en DynamoDB
    assert page.locator("article.inc").count() == 1


def test_chat_keeps_session(page):
    page.get_by_label("Mensaje").fill("¿Qué atiendo primero?")
    page.get_by_role("button", name="Enviar").click()
    page.locator("#log .msg").nth(1).get_by_text("Prioriza lo crítico").wait_for()
    sid = page.evaluate("localStorage.getItem('sid')")
    assert sid and len(sid) >= 33
    page.get_by_label("Mensaje").fill("otra")
    page.get_by_role("button", name="Enviar").click()
    page.locator("#log .msg").nth(3).get_by_text("Prioriza").wait_for()
    assert page.evaluate("localStorage.getItem('sid')") == sid


def test_html_is_escaped(page):
    page.get_by_label("Título").fill("<img src=x onerror=window.pwn=1>")
    page.get_by_role("button", name="Registrar y clasificar").click()
    page.locator("article.inc").first.wait_for()
    assert page.evaluate("window.pwn") is None
    assert "<img" in page.locator("article.inc h3").first.inner_text()


@pytest.mark.parametrize("theme,surface", [("light", "rgb(245, 242, 235)"),
                                            ("dark", "rgb(23, 27, 25)"),
                                            ("contrast", "rgb(245, 242, 235)")])
def test_themes(page, theme, surface):
    page.get_by_role("button", name={"light": "Papel", "dark": "Tinta",
                                     "contrast": "Alto contraste"}[theme]).click()
    assert page.evaluate("getComputedStyle(document.body).backgroundColor") == surface
    page.reload()  # el tema persiste
    assert page.evaluate("document.documentElement.dataset.theme") == theme


def test_design_rules(page):
    """Sin sombras, tarjetas rectas, controles con radio 2px, titular en serif."""
    assert page.evaluate("getComputedStyle(document.querySelector('.card')).boxShadow") == "none"
    assert page.evaluate("getComputedStyle(document.querySelector('.card')).borderRadius") == "0px"
    assert page.evaluate("getComputedStyle(document.querySelector('#go')).borderRadius") == "2px"
    assert "EB Garamond" in page.evaluate("getComputedStyle(document.querySelector('h1')).fontFamily")


def test_mobile_no_horizontal_scroll(browser, base_url):
    ctx = browser.new_context(viewport={"width": 375, "height": 800})
    pg = ctx.new_page()
    pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())
    pg.goto(base_url)
    assert pg.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    ctx.close()
