"""Opt-in real browser acceptance for the graphical waveform runtime fixture.

Start test_waveform_xpra_runtime.py --serve, then set UCAGENT_WAVE_XPRA_URL and
UCAGENT_WAVE_XPRA_PASSWORD. UCAGENT_XPRA_CHROMIUM_EXECUTABLE may select Chrome.
UCAGENT_WAVE_XPRA_ARTIFACTS preserves screenshots outside pytest's temp folder.
"""

import os
from pathlib import Path
from urllib.parse import urlencode

import pytest


_URL = os.environ.get('UCAGENT_WAVE_XPRA_URL', '')
pytestmark = pytest.mark.skipif(not _URL, reason='Requires the real waveform Xpra fixture server')


@pytest.mark.parametrize('browser_kind', ['chromium', 'webkit'])
def test_wave_link_displays_restored_waveform_and_accepts_remote_input(browser_kind, tmp_path):
    """Open /wave/, observe actual Tk pixels and round-trip keyboard input over Xpra."""
    from playwright.sync_api import sync_playwright

    base = _URL.rstrip('/')
    credentials = dict(username='ucagent', password=os.environ['UCAGENT_WAVE_XPRA_PASSWORD'])
    artifacts = Path(os.environ.get('UCAGENT_WAVE_XPRA_ARTIFACTS', str(tmp_path)))
    artifacts.mkdir(parents=True, exist_ok=True)
    options = {}
    if browser_kind == 'chromium' and os.environ.get('UCAGENT_XPRA_CHROMIUM_EXECUTABLE'):
        options['executable_path'] = os.environ['UCAGENT_XPRA_CHROMIUM_EXECUTABLE']
    with sync_playwright() as playwright:
        browser = getattr(playwright, browser_kind).launch(headless=True, **options)
        context = browser.new_context(http_credentials=credentials, viewport={'width': 1440, 'height': 950})
        page = context.new_page()
        try:
            response = context.request.get(base + '/workspace/test-fixture.json')
            assert response.ok, response.text()
            fixture = response.json()
            page.goto(base + '/wave/?' + urlencode({'meta': fixture['meta']}))
            page.wait_for_url('**/api/xpra/sessions/*/view', timeout=45000)
            page.wait_for_function("document.querySelector('#status').textContent === 'Connected'", timeout=30000)
            surface = page.locator('#display').element_handle().content_frame()
            surface.wait_for_function(
                "Object.values(client.id_to_window).some(win => win.title.includes('fake_verdi'))", timeout=30000)
            canvas = surface.locator('.window:not(.override-redirect) canvas').first
            canvas.wait_for()
            # Check a drawn trace, not just a window registration or connected socket.
            surface.wait_for_function("""() => [...document.querySelectorAll('.window canvas')].some(canvas => {
                try { const data=canvas.getContext('2d').getImageData(0,0,canvas.width,canvas.height).data;
                    let count=0; for(let i=0;i<data.length;i+=4) {
                        if(data[i]<140 && data[i+1]>150 && data[i+2]>100) count++;
                    } return count>100;
                } catch(error) {return false;}
            })""")
            current = context.request.get(base + '/workspace/' + fixture['state_file']).json()
            for key in ('waveform', 'sources', 'signals', 'native_unit', 'start', 'end', 'cursor'):
                assert current[key] == fixture[key]
            assert current['display_unit'] == '10fs'
            prior = current['reviewed']
            canvas.click(position={'x': 160, 'y': 160})
            page.keyboard.press('r')
            page.wait_for_function("""async ({url, prior}) => {
                const state=await (await fetch(url)).json(); return state.reviewed>prior;
            }""", arg={'url': base + '/workspace/' + fixture['state_file'], 'prior': prior})
            surface.wait_for_function(
                "Object.values(client.id_to_window).some(win => win.title.includes('Reviewed'))")
            page.screenshot(path=str(artifacts / (browser_kind + '-fake-verdi.png')))
            viewer_url = page.url
            page.reload()
            page.wait_for_function("document.querySelector('#status').textContent === 'Connected'", timeout=30000)
            # A second canonical open reuses the same live application and viewer URL.
            page.goto(base + '/wave/?' + urlencode({'meta': fixture['meta']}))
            page.wait_for_url(viewer_url, timeout=45000)
            page.wait_for_function("document.querySelector('#status').textContent === 'Connected'", timeout=30000)
            sessions = context.request.get(base + '/api/xpra/sessions').json()
            assert sessions['active_count'] == 1 and len(sessions['sessions']) == 1
        except Exception:
            page.screenshot(path=str(artifacts / (browser_kind + '-failure.png')))
            details = context.request.get(base + '/api/xpra/sessions').text()
            (artifacts / (browser_kind + '-sessions.json')).write_text(details)
            raise
        finally:
            context.close()
            browser.close()
