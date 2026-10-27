"""Browser check of the classic UI against the compose stack (Playwright, Chromium).

Usage: ui_check.py STATE_FILE
Logs in, opens the dashboard, finds the e2e job in the job list, shows its output and
logs out. Uncaught JavaScript errors on any page count as failures.
"""
import json
import sys

from playwright.sync_api import expect, sync_playwright

BASE = 'http://127.0.0.1:18052'
results = []


def check(name, fn):
    try:
        detail = fn()
        results.append(True)
        print(f'PASS {name}' + (f'  [{detail}]' if detail else ''), flush=True)
    except Exception as e:  # noqa
        results.append(False)
        print(f'FAIL {name}  [{type(e).__name__}: {str(e).splitlines()[0][:200]}]', flush=True)


state = json.load(open(sys.argv[1]))
with sync_playwright() as p:
    browser = p.chromium.launch()
    page = browser.new_page()
    js_errors = []
    page.on('pageerror', lambda e: js_errors.append(str(e)))

    def login():
        page.goto(f'{BASE}/#/login')
        page.get_by_label('Username').fill('admin')
        page.get_by_label('Password').fill('e2e-admin-pass')
        page.get_by_role('button', name='Log In').click()
        expect(page.get_by_role('heading', name='Dashboard')).to_be_visible(timeout=30000)

    def job_list():
        page.goto(f'{BASE}/#/jobs')
        expect(page.get_by_text('e2e-hello').first).to_be_visible(timeout=30000)

    def job_output():
        page.goto(f"{BASE}/#/jobs/playbook/{state['job']}/output")
        expect(page.get_by_text('Hello World!').first).to_be_visible(timeout=30000)

    def logout():
        page.locator('[data-ouia-component-id="toolbar-user-dropdown-toggle"]').click()
        page.locator('#logout-button').click()
        expect(page.get_by_role('button', name='Log In')).to_be_visible(timeout=30000)
        r = page.request.get(f'{BASE}/api/v2/me/')
        assert r.status == 401, f'session still valid after logout: {r.status}'

    check('UI login', login)
    check('UI job list shows the e2e job', job_list)
    check('UI job output', job_output)
    check('UI logout ends the session', logout)
    check('no JavaScript errors', lambda: (_ for _ in ()).throw(AssertionError('; '.join(js_errors)[:300])) if js_errors else None)
    browser.close()

print(f'\n{sum(results)}/{len(results)} UI checks passed')
sys.exit(0 if all(results) else 1)
