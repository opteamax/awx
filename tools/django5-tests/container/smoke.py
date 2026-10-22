"""Black-box smoke test against running uwsgi (:8013) and daphne (:8051)."""
import base64
import json
import sys

import requests
import websocket

API = 'http://127.0.0.1:8013'
WS = 'ws://127.0.0.1:8051'
results = []


def check(name, cond, detail='', resp=None):
    results.append(cond)
    if not cond and resp is not None:
        print('     body:', resp.text[:600].replace('\n', ' '))
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{detail}]' if detail else ''))


s = requests.Session()
r = s.get(f'{API}/api/v2/ping/')
check('GET /api/v2/ping/', r.status_code == 200, r.status_code)

# Session login as the UI does it: fetch CSRF cookie, then POST the login form
r = s.get(f'{API}/api/login/')
csrf = s.cookies.get('csrftoken')
r = s.post(f'{API}/api/login/', data={'username': 'admin', 'password': 'smoke-pass', 'next': '/api/'},
           headers={'X-CSRFToken': csrf, 'Referer': f'{API}/api/login/'}, allow_redirects=False)
check('POST /api/login/ (session)', r.status_code in (200, 302) and 'awx_sessionid' in s.cookies, r.status_code)
print('     set-cookie:', r.headers.get('Set-Cookie', '')[:300])
r = s.get(f'{API}/api/v2/me/')
check('GET /api/v2/me/ with session', r.status_code == 200 and r.json()['results'][0]['username'] == 'admin', r.status_code, r)

# Websocket via daphne/channels 4 with the session cookie, subscribe like the UI
cookie = '; '.join(f'{k}={v}' for k, v in s.cookies.items())
try:
    ws = websocket.create_connection(f'{WS}/websocket/', header=[f'Cookie: {cookie}'], origin=API, timeout=10)
    first = json.loads(ws.recv())
    check('websocket connect (channels 4)', first.get('accept') is True and first.get('user'), str(first)[:80])
    ws.send(json.dumps({'xrftoken': s.cookies.get('csrftoken'), 'groups': {'jobs': ['status_changed']}}))
    reply = json.loads(ws.recv())
    check('websocket subscribe', 'groups_current' in reply, str(reply)[:80])
    ws.close()
except Exception as e:  # noqa
    check('websocket connect (channels 4)', False, repr(e))

# Logout via GET, as the 24.6.1 UI does (Django 5 removed GET for LogoutView)
r = s.get(f'{API}/api/logout/', allow_redirects=False)
check('GET /api/logout/', r.status_code in (200, 302), r.status_code)
r = s.get(f'{API}/api/v2/me/')
check('session invalid after logout', r.status_code == 401, r.status_code)

# OAuth2 personal access token (django-oauth-toolkit 1.7.1 on Django 5.2)
basic = {'Authorization': 'Basic ' + base64.b64encode(b'admin:smoke-pass').decode()}
r = requests.post(f'{API}/api/v2/tokens/', json={'description': 'smoke', 'scope': 'write'}, headers=basic)
check('POST /api/v2/tokens/ (basic auth)', r.status_code == 201, r.status_code)
token = r.json().get('token') if r.status_code == 201 else None
r = requests.get(f'{API}/api/v2/me/', headers={'Authorization': f'Bearer {token}'})
check('GET /api/v2/me/ with bearer token', r.status_code == 200, r.status_code)

# OAuth2 application + password grant via /api/o/token/
r = requests.post(f'{API}/api/v2/applications/', headers=basic,
                  json={'name': 'smoke-app', 'organization': 1, 'client_type': 'confidential', 'authorization_grant_type': 'password'})
check('POST /api/v2/applications/', r.status_code == 201, r.status_code)
if r.status_code == 201:
    app = r.json()
    r = requests.post(f'{API}/api/o/token/', data={'grant_type': 'password', 'username': 'admin', 'password': 'smoke-pass', 'scope': 'read'},
                      auth=(app['client_id'], app['client_secret']))
    check('POST /api/o/token/ (password grant)', r.status_code == 200 and 'access_token' in r.json(), r.status_code, r)
    if r.status_code == 200:
        r = requests.post(f'{API}/api/o/revoke_token/', data={'token': r.json()['access_token']}, auth=(app['client_id'], app['client_secret']))
        check('POST /api/o/revoke_token/', r.status_code == 200, r.status_code)

# A few representative API reads and a write
for path in ['/api/v2/organizations/', '/api/v2/job_templates/', '/api/v2/instances/', '/api/v2/settings/all/', '/api/v2/metrics/', '/api/v2/role_definitions/']:
    r = requests.get(f'{API}{path}', headers=basic)
    check(f'GET {path}', r.status_code == 200, r.status_code)
r = requests.post(f'{API}/api/v2/organizations/', headers=basic, json={'name': 'smoke-org'})
check('POST /api/v2/organizations/', r.status_code == 201, r.status_code)
r = requests.post(f'{API}/api/v2/inventories/', headers=basic, json={'name': 'smoke-inv', 'organization': r.json().get('id')})
check('POST /api/v2/inventories/', r.status_code == 201, r.status_code)

print(f'\n{sum(results)}/{len(results)} checks passed')
sys.exit(0 if all(results) else 1)
