"""Opt-in browser input acceptance against a running complete UCAgent runtime.

Set UCAGENT_XPRA_BROWSER_URLS to space-separated authenticated /api/xpra/ URLs
(direct CMD and/or Master proxies), and UCAGENT_XPRA_BROWSER_PASSWORD to their
shared password. Install Playwright browsers, or set
UCAGENT_XPRA_CHROMIUM_EXECUTABLE to an installed Chrome executable. The target
must run the full Agent workflow and have xterm and bash installed.
"""

import os
import uuid

import pytest


_URLS = os.environ.get("UCAGENT_XPRA_BROWSER_URLS", "").split()
pytestmark = pytest.mark.skipif(not _URLS, reason="Requires a running complete UCAgent and browsers")


def check_remote_right_click(page):
    """Check console clipboard menus and remote menus with a modifier key."""
    page.wait_for_function('document.querySelector("#status").textContent === "Connected"', timeout=30000)
    surface = page.locator("#display").element_handle().content_frame()
    canvas = surface.locator(".window:not(.override-redirect) canvas").first
    canvas.wait_for()
    surface.evaluate("""() => {
        window.contextEvents=[];
        document.addEventListener('contextmenu', event => contextEvents.push(event.defaultPrevented));
        window.mousePackets=[];
        const send=client.send;
        client.send=function(packet) {
            if(packet[0] === 'button-action') mousePackets.push(packet);
            return send.apply(this,arguments);
        };
    }""")
    canvas.click(button="right", position={"x": 100, "y": 100})
    surface.locator("#clipboard-menu").wait_for(state="visible")
    assert surface.evaluate("contextEvents.every(Boolean)")
    assert surface.evaluate("mousePackets.map(packet => [packet[2],packet[3]])") == []

    page.keyboard.press("Escape")
    surface.locator("#clipboard-menu").wait_for(state="hidden")

    # Xpra's macOS defaults swap Command and Control; preserve the shipped mapping.
    modifier = "Meta" if surface.evaluate("client.swap_keys") else "Control"
    canvas.hover(position={"x": 120, "y": 120})
    page.keyboard.down(modifier)
    page.mouse.down(button="right")
    try:
        surface.locator(".override-redirect canvas").wait_for(state="visible", timeout=10000)
    finally:
        page.mouse.up(button="right")
        page.keyboard.up(modifier)
    surface.locator(".override-redirect canvas").wait_for(state="detached", timeout=10000)
    assert surface.evaluate("contextEvents.every(Boolean)")
    surface.wait_for_function("client.buttons_pressed.size === 0")

    # A left click and real shell execution prove ordinary input remains usable.
    canvas.click(position={"x": 100, "y": 100})
    marker = "RIGHT_CLICK_OK_" + uuid.uuid4().hex
    page.keyboard.type("PS1='input> '; unset PROMPT_COMMAND; printf '\\033]0;" + marker + "\\007'")
    page.keyboard.press("Enter")
    surface.wait_for_function(
        "marker => Object.values(client.id_to_window).some(win => win.title === marker)", arg=marker,
        timeout=10000,
    )
    assert page.locator("#status").inner_text() == "Connected"
    # Only the embedded application owns right clicks; the page controls retain browser behavior.
    assert page.locator("#manager").evaluate(
        "element => element.dispatchEvent(new MouseEvent('contextmenu', {bubbles:true,cancelable:true}))"
    )


def check_terminal_clipboard(page):
    """Round-trip selected terminal text through the real browser clipboard."""
    surface = page.locator("#display").element_handle().content_frame()
    canvas = surface.locator(".window:not(.override-redirect) canvas").first
    marker = "CLIPBOARD_" + uuid.uuid4().hex
    canvas.click(position={"x": 60, "y": 60})
    page.keyboard.type("PS1=''; unset PROMPT_COMMAND; printf '\\033[2J\\033[H" + marker + "\\r\\n'")
    page.keyboard.press("Enter")
    # xterm's default fixed font puts the first row at the top of its canvas.
    page.wait_for_timeout(300)
    canvas.dblclick(position={"x": 45, "y": 8})
    surface.wait_for_function("marker => client.clipboard_buffer === marker", arg=marker)
    canvas.click(button="right", position={"x": 45, "y": 8})
    assert not surface.locator("#clipboard-copy").is_disabled()
    surface.locator("#clipboard-copy").click()
    surface.wait_for_function("document.querySelector('#clipboard-dialog').open || document.querySelector('#clipboard-notice').textContent === 'Selection copied.'")
    accelerator = "Meta" if page.evaluate("navigator.platform.includes('Mac')") else "Control"
    if surface.locator("#clipboard-dialog").evaluate("element => element.open"):
        surface.locator("#clipboard-text").focus()
        page.keyboard.press(accelerator + "+c")
        surface.locator("#clipboard-cancel").click()

    # Paste into a local HTML field to prove a real clipboard write, not just a cache update.
    page.evaluate("""() => {
        let field=document.querySelector('#external-clipboard');
        if(!field){field=document.createElement('textarea');field.id='external-clipboard';
            field.style='position:fixed;top:0;left:0;z-index:100000';document.body.append(field);}
        field.value='';field.focus();
    }""")
    external = page.locator("#external-clipboard")
    page.keyboard.press(accelerator + "+v")
    page.wait_for_function("marker => document.querySelector('#external-clipboard').value === marker", arg=marker)

    # Copy a shell command locally, paste with the terminal menu, and execute it remotely.
    pasted = "PASTED_\N{CHECK MARK}_" + uuid.uuid4().hex
    external.fill("printf '\\033]0;" + pasted + "\\007'")
    external.select_text()
    page.keyboard.press(accelerator + "+c")
    canvas.click(button="right", position={"x": 70, "y": 40})
    surface.locator("#clipboard-paste").click()
    surface.wait_for_function("document.querySelector('#clipboard-dialog').open || document.querySelector('#clipboard-notice').textContent === 'Text pasted into the terminal.'")
    if surface.locator("#clipboard-dialog").evaluate("element => element.open"):
        surface.locator("#clipboard-text").focus()
        page.keyboard.press(accelerator + "+v")
        surface.locator("#clipboard-submit").click()
    assert not surface.evaluate("marker => Object.values(client.id_to_window).some(win => win.title === marker)", pasted)
    page.keyboard.press("Enter")
    surface.wait_for_function("marker => Object.values(client.id_to_window).some(win => win.title === marker)", arg=pasted)

    # Permission denial must expose a usable local dialog and keep its text out of the app until submitted.
    surface.evaluate("""() => Object.defineProperty(navigator,'clipboard', {configurable:true,value:{
        readText:()=>Promise.reject(new DOMException('Denied','NotAllowedError')),
        writeText:()=>Promise.reject(new DOMException('Denied','NotAllowedError'))
    }})""")
    canvas.click(button="right", position={"x": 70, "y": 40})
    surface.locator("#clipboard-paste").click()
    surface.locator("#clipboard-dialog[open]").wait_for()
    assert surface.locator("#clipboard-text").input_value() == ""
    fallback = "MANUAL_" + uuid.uuid4().hex
    surface.locator("#clipboard-text").fill("printf '\\033]0;" + fallback + "\\007'")
    assert surface.evaluate("client.capture_keyboard") is False
    surface.locator("#clipboard-submit").click()
    page.keyboard.press("Enter")
    surface.wait_for_function("marker => Object.values(client.id_to_window).some(win => win.title === marker)", arg=fallback)
    canvas.dblclick(position={"x": 45, "y": 8})
    surface.wait_for_function("marker => client.clipboard_buffer === marker", arg=marker)
    canvas.click(button="right", position={"x": 45, "y": 8})
    surface.locator("#clipboard-copy").click()
    surface.locator("#clipboard-dialog[open]").wait_for()
    assert surface.locator("#clipboard-text").input_value() == marker
    assert surface.locator("#clipboard-text").evaluate("element => element.readOnly")
    assert surface.locator("#clipboard-text").evaluate(
        "element => element.dispatchEvent(new MouseEvent('contextmenu', {bubbles:true,cancelable:true}))"
    )
    surface.locator("#clipboard-cancel").click()
    page.keyboard.press("Control+Shift+c")
    surface.locator("#clipboard-dialog[open]").wait_for()
    assert surface.locator("#clipboard-text").input_value() == marker
    surface.locator("#clipboard-cancel").click()
    page.keyboard.press(accelerator + "+v")
    surface.locator("#clipboard-dialog[open]").wait_for()
    surface.locator("#clipboard-cancel").click()

    # Control+C must interrupt the remote shell even in macOS browsers.
    canvas.click(position={"x": 70, "y": 60})
    page.keyboard.type("sleep 30; printf '\\033]0;INTERRUPT_FAILED\\007'")
    page.keyboard.press("Enter")
    page.keyboard.press("Control+c")
    interrupted = "INTERRUPTED_" + uuid.uuid4().hex
    page.keyboard.type("printf '\\033]0;" + interrupted + "\\007'")
    page.keyboard.press("Enter")
    surface.wait_for_function("marker => Object.values(client.id_to_window).some(win => win.title === marker)", arg=interrupted, timeout=10000)
    external.evaluate("element => element.remove()")


@pytest.mark.parametrize("base", _URLS or [""])
@pytest.mark.parametrize("browser_kind", ["chromium", "webkit"])
def test_full_agent_right_click_and_reconnect(base, browser_kind, tmp_path):
    """Exercise application context menus through direct CMD and Master entrypoints."""
    playwright_api = pytest.importorskip("playwright.sync_api")
    credentials = {
        "username": os.environ.get("UCAGENT_XPRA_BROWSER_USERNAME", "ucagent"),
        "password": os.environ["UCAGENT_XPRA_BROWSER_PASSWORD"],
    }
    base = base.rstrip("/") + "/"
    assert base.endswith("/api/xpra/")
    options = {}
    executable = os.environ.get("UCAGENT_XPRA_CHROMIUM_EXECUTABLE")
    if browser_kind == "chromium" and executable:
        options["executable_path"] = executable
    with playwright_api.sync_playwright() as playwright:
        browser = getattr(playwright, browser_kind).launch(headless=True, **options)
        context = browser.new_context(http_credentials=credentials, viewport={"width": 1280, "height": 900})
        try:
            tasks = context.request.get(base.removesuffix("api/xpra/") + "api/tasks")
            assert tasks.status == 200, tasks.text()
            assert len(tasks.json()["data"]["task_list"]["stage_list"]) > 1
            created = context.request.post(base + "sessions", data={
                "name": "Browser input acceptance", "mode": "console", "command": "bash -l",
            }, timeout=60000)
            assert created.status == 201, created.text()
            session = created.json()
            try:
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.goto(base + session["viewer_path"])
                check_remote_right_click(page)
                previous = page.locator("#display").get_attribute("src")
                page.locator("#reconnect").click()
                page.wait_for_function("previous => document.querySelector('#display').getAttribute('src') !== previous", arg=previous)
                check_remote_right_click(page)
                check_terminal_clipboard(page)
                assert not errors, errors
            except Exception:
                page.screenshot(path=str(tmp_path / "clipboard-failure.png"))
                raise
            finally:
                deleted = context.request.delete(base + "sessions/" + session["id"], timeout=15000)
                assert deleted.status == 200, deleted.text()
        finally:
            context.close()
            browser.close()
