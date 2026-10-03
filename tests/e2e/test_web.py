"""Pruebas de navegador (Chromium) contra scripts/local.py: web + API + DynamoDB simulado."""

import glob
import os
import sys

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
    app = sys.modules["app"]  # el servidor local comparte tabla entre pruebas: se vacía en cada una
    for item in app._table.scan()["Items"]:
        app._table.delete_item(Key={"id": item["id"]})
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    pg = ctx.new_page()
    pg.route("**/fonts.googleapis.com/**", lambda r: r.abort())  # sin red: cae a fuentes locales
    errors = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    pg.goto(base_url)
    yield pg
    assert errors == []
    ctx.close()


def mk(page, title, status=None):
    """Crea una incidencia por API (como lo haría otro sistema) y, si se pide, fuerza su estado."""
    inc = page.evaluate(
        "async t=>(await fetch('/api/incidents',{method:'POST',headers:{'content-type':'application/json'},"
        "body:JSON.stringify({title:t})})).json()", title)
    if status:
        page.evaluate(
            "async([i,s])=>{await fetch('/api/incidents/'+i,{method:'PATCH',"
            "headers:{'content-type':'application/json'},body:JSON.stringify({status:s})})}",
            [inc["id"], status])
    return inc


def card_of(page, title):
    return page.locator("article.inc", has_text=title)


def test_empty_state_guides_the_first_step(page):
    page.get_by_text("Todo al día. No hay nada pendiente.").wait_for()
    page.locator("#list").get_by_role("button", name="Reportar un problema").click()
    assert page.locator("#new").is_visible() and page.evaluate("document.activeElement.id") == "t"


def test_report_guided_flow(page):
    """Reportar con opciones rápidas, ver lo que hizo el agente y resolver con un toque."""
    page.locator("#open-report").click()
    page.get_by_role("button", name="Sistema caído").click()  # plantilla: rellena el título
    assert page.input_value("#t") == "Sistema caído o sin respuesta"
    page.get_by_text("A todos los clientes").click()
    page.get_by_role("button", name="Reportar", exact=True).click()

    card = page.locator("article.inc").first
    card.wait_for()
    page.get_by_text("la clasifiqué como crítica").wait_for()  # aviso comprensible, no jerga
    assert card.locator(".sev").inner_text().lower() == "crítica"
    assert "en curso" in card.inner_text().lower() and "Revisar logs" in card.inner_text()  # lo hizo el agente
    assert not page.locator("#new").is_visible()
    card.get_by_text("Ver descripción").click()
    assert "Impacto: A todos los clientes." in card.inner_text()

    card.get_by_role("button", name="Marcar resuelta").click()
    page.get_by_role("button", name="Deshacer").wait_for()
    assert page.locator("article.inc").count() == 0  # sale de «Pendientes»
    page.get_by_role("button", name="Resueltas").click()
    assert page.locator("article.inc").count() == 1
    page.reload()  # persistencia en DynamoDB
    page.get_by_role("button", name="Resueltas 1").wait_for()


def test_primary_button_follows_the_state_and_undo(page):
    mk(page, "Error de impresora")
    page.reload()
    card = card_of(page, "Error de impresora")
    assert "abierta" in card.inner_text().lower()
    card.get_by_role("button", name="Empezar a atender").click()
    page.wait_for_function("document.querySelector('article.inc').innerText.toLowerCase().includes('en curso')")
    page.get_by_role("button", name="Deshacer").click()
    page.wait_for_function("document.querySelector('article.inc').innerText.toLowerCase().includes('abierta')")
    assert card_of(page, "Error de impresora").get_by_role("button", name="Empezar a atender").count() == 1


def test_most_urgent_goes_straight_to_the_agent(page):
    mk(page, "Fallo menor")
    mk(page, "Caída total del ERP", status="abierta")  # crítica, pero el agente la dejó abierta aquí
    page.reload()
    assert "sugerida" in page.locator("article.inc").first.inner_text().lower()  # la crítica va arriba
    page.get_by_role("button", name="Atender la más urgente").click()
    page.locator("#agent .reply").get_by_text("la puse en curso").wait_for()
    assert "Cambió el estado" in page.locator("#agent").inner_text()  # pasos legibles, no nombres técnicos
    page.wait_for_function(
        "[...document.querySelectorAll('article.inc')].some(a=>a.innerText.includes('Caída total')&&a.innerText.toLowerCase().includes('en curso'))")
    assert "abierta" in card_of(page, "Fallo menor").inner_text().lower()
    page.locator("#agent").get_by_role("button", name="Resumen del día").wait_for()  # siguiente paso sugerido


def test_ask_agent_from_a_card_shows_the_answer_inline(page):
    mk(page, "Wifi lenta", status="abierta")
    page.reload()
    card = card_of(page, "Wifi lenta")
    card.get_by_role("button", name="Preguntar al agente").click()
    card.locator(".answer .reply").get_by_text("Prioriza").wait_for()
    assert page.locator("#agent .reply").count() == 0  # no ensucia el panel principal


def test_chat_keeps_session(page):
    page.get_by_role("button", name="¿Qué atiendo primero?").click()
    page.locator("#agent .reply").get_by_text("Prioriza lo crítico").wait_for()
    assert "Revisó las incidencias" in page.locator("#agent").inner_text()
    sid = page.evaluate("localStorage.getItem('sid')")
    assert sid and len(sid) >= 33
    page.get_by_label("O escríbele lo que quieras").fill("otra pregunta")
    page.get_by_role("button", name="Enviar").click()
    page.locator("#agent .reply").get_by_text("otra pregunta").wait_for()
    assert page.evaluate("localStorage.getItem('sid')") == sid
    page.get_by_role("button", name="Nueva conversación").click()
    assert page.evaluate("localStorage.getItem('sid')") is None


def test_html_is_escaped(page):
    page.locator("#open-report").click()
    page.fill("#t", "<img src=x onerror=window.pwn=1>")
    page.get_by_role("button", name="Reportar", exact=True).click()
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
    assert pg.get_by_role("button", name="Atender la más urgente").is_visible()  # la acción clave, sin scroll
    ctx.close()


def test_conversation_thread_is_kept_and_survives_reload(page):
    """El detalle de la conversación: cada pregunta y cada respuesta quedan visibles, también al recargar."""
    page.get_by_role("button", name="¿Qué atiendo primero?").click()
    page.locator("#agent .msg.bot .reply").first.wait_for()
    page.get_by_label("O escríbele lo que quieras").fill("segunda pregunta")
    page.get_by_role("button", name="Enviar").click()
    page.locator("#agent .msg.bot .reply").nth(1).get_by_text("segunda pregunta").wait_for()

    me = page.locator("#agent .msg.me")
    assert me.count() == 2 and "¿Qué atiendo primero?" in me.nth(0).inner_text()  # etiqueta legible, no el prompt
    assert "segunda pregunta" in me.nth(1).inner_text()
    assert page.locator("#agent .msg.bot").count() == 2
    assert page.locator("#agent .suggest").count() == 1  # un único bloque de siguientes pasos, al final

    page.reload()
    page.locator("#agent .msg.me").nth(1).wait_for()
    assert page.locator("#agent .msg.me").count() == 2 and page.locator("#agent .msg.bot .reply").count() == 2
    page.get_by_role("button", name="Nueva conversación").click()
    assert page.locator("#agent .msg").count() == 0
    page.reload()
    page.get_by_role("button", name="Resumen del día").first.wait_for()
    assert page.locator("#agent .msg").count() == 0  # no reaparece


def test_register_an_incident_by_chatting(page):
    """Escribir «registra…» crea la incidencia sin pedir ids ni datos: aparece resaltada en la lista."""
    page.get_by_label("O escríbele lo que quieras").fill("Registra una incidencia: la impresora no imprime")
    page.get_by_role("button", name="Enviar").click()
    page.locator("#agent .msg.bot .reply").get_by_text("Registrada").wait_for()
    assert "Registró la incidencia" in page.locator("#agent").inner_text()
    card = card_of(page, "la impresora no imprime")
    card.wait_for()
    assert "new" in card.get_attribute("class")  # resaltada para que se vea qué cambió


def test_each_incident_shows_when_it_was_registered(page):
    mk(page, "Impresora rota")
    page.reload()
    card = card_of(page, "Impresora rota")
    text = card.locator(".when").inner_text()
    assert text.startswith("Registrada el ") and "hace un momento" in text


def test_filter_by_day(page):
    mk(page, "Impresora rota")
    page.reload()
    today = page.evaluate("new Date().toLocaleDateString('en-CA')")
    page.fill("#day", today)
    assert card_of(page, "Impresora rota").count() == 1
    page.fill("#day", "2020-01-01")
    page.get_by_text("No hay nada registrado ese día.").wait_for()
    assert page.locator("article.inc").count() == 0
    assert "pendientes 0" in page.locator("#filters").inner_text().lower()
    page.get_by_role("button", name="Todas las fechas").click()
    assert card_of(page, "Impresora rota").count() == 1 and not page.locator("#clear-day").is_visible()


def test_warns_when_a_similar_incident_is_already_registered(page):
    mk(page, "Pasarela de pagos caída")
    page.reload()
    page.locator("#open-report").click()
    page.fill("#t", "la pasarela de pagos esta caida")
    page.locator("#dup").wait_for(state="visible")
    assert "Pasarela de pagos caída" in page.locator("#dup").inner_text()
    assert "registrada hace un momento" in page.locator("#dup").inner_text()
    page.fill("#t", "se fue la luz en la oficina")
    page.locator("#dup").wait_for(state="hidden")
    page.fill("#t", "pasarela de pagos caida")
    page.get_by_role("button", name="Verla").click()
    assert not page.locator("#new").is_visible()
    page.wait_for_function("document.querySelector('article.inc.new')")  # lleva a la existente, resaltada


def test_old_conversations_are_discarded_after_a_version_change(page):
    page.evaluate("localStorage.removeItem('v');localStorage.setItem('sid','x'.repeat(40));"
                  "localStorage.setItem('thread',JSON.stringify([{q:'vieja',reply:'antigua'}]))")
    page.reload()
    page.get_by_role("button", name="Resumen del día").first.wait_for()
    assert page.locator("#agent .msg").count() == 0
    assert page.evaluate("localStorage.getItem('sid')") is None and page.evaluate("localStorage.getItem('v')") == "3"
