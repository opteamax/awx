"""End-to-end checks against the compose stack: real project syncs and jobs.

Usage: e2e.py seed|verify STATE_FILE
  seed    create resources, sync a git project and run a job (run with the old release)
  verify  check what seed created, then sync and run jobs again (run after the upgrade)
"""
import base64
import json
import sys
import time

import requests

API = 'http://127.0.0.1:18052/api/v2'
AUTH = {'Authorization': 'Basic ' + base64.b64encode(b'admin:e2e-admin-pass').decode()}
PROJECT_URL = 'https://github.com/ansible/ansible-tower-samples'
results = []


def check(name, cond, detail=''):
    results.append(bool(cond))
    print(('PASS ' if cond else 'FAIL ') + name + (f'  [{detail}]' if detail else ''), flush=True)


def api(method, path, **kwargs):
    r = requests.request(method, f'{API}{path}', headers=AUTH, timeout=60, **kwargs)
    if r.status_code >= 400:
        print(f'  {method} {path} -> {r.status_code}: {r.text[:500]}', flush=True)
    r.raise_for_status()
    return r.json() if r.text else {}


def get_or_create(path, name, **fields):
    found = api('GET', f'{path}?name={name}')['results']
    return found[0] if found else api('POST', path, json={'name': name, **fields})


def wait(path, timeout=900):
    deadline = time.time() + timeout
    while time.time() < deadline:
        obj = api('GET', path)
        if obj['status'] in ('successful', 'failed', 'error', 'canceled'):
            return obj
        time.sleep(5)
    return api('GET', path)


def stdout(path):
    r = requests.get(f'{API}{path}stdout/?format=txt', headers=AUTH, timeout=60)
    return r.text


def sync_project(project):
    update = api('POST', f"/projects/{project['id']}/update/")
    result = wait(f"/project_updates/{update['id']}/")
    check('project sync (git clone)', result['status'] == 'successful', f"{result['status']} {result.get('job_explanation', '')[:200]}")
    if result['status'] != 'successful':
        print(stdout(f"/project_updates/{update['id']}/")[-3000:])
    return result


def run_job(template):
    job = api('POST', f"/job_templates/{template['id']}/launch/")
    result = wait(f"/jobs/{job['id']}/")
    # The job status is final before the callback receiver has stored all events
    deadline = time.time() + 120
    while not result.get('event_processing_finished') and time.time() < deadline:
        time.sleep(2)
        result = api('GET', f"/jobs/{job['id']}/")
    out = stdout(f"/jobs/{job['id']}/")
    check('job run in execution environment', result['status'] == 'successful', f"{result['status']} {result.get('job_explanation', '')[:200]}")
    check('job output contains playbook result', 'Hello World!' in out, out[-200:].replace('\n', ' ') if 'Hello World!' not in out else '')
    if result['status'] != 'successful':
        print(out[-3000:])
    events = api('GET', f"/jobs/{job['id']}/job_events/")['count']
    check('job events recorded', events > 0, events)
    return result


def run_adhoc(inventory, credential):
    cmd = api('POST', f"/inventories/{inventory['id']}/ad_hoc_commands/", json={'module_name': 'ping', 'limit': 'localhost', 'credential': credential})
    result = wait(f"/ad_hoc_commands/{cmd['id']}/")
    check('ad hoc command (ping)', result['status'] == 'successful', result['status'])


def seed(state_file):
    ping = api('GET', '/ping/')
    check('ping', ping.get('version'), ping.get('version'))
    org = get_or_create('/organizations/', 'e2e')
    machine = api('GET', '/credential_types/?namespace=ssh')['results'][0]
    cred = get_or_create('/credentials/', 'e2e-machine', organization=org['id'], credential_type=machine['id'],
                         inputs={'username': 'e2e', 'password': 'e2e-cred-secret'})
    inventory = get_or_create('/inventories/', 'e2e-inv', organization=org['id'])
    if not api('GET', f"/inventories/{inventory['id']}/hosts/?name=localhost")['results']:
        api('POST', f"/inventories/{inventory['id']}/hosts/", json={'name': 'localhost', 'variables': 'ansible_connection: local\nansible_python_interpreter: "{{ ansible_playbook_python }}"'})
    project = get_or_create('/projects/', 'e2e-project', organization=org['id'], scm_type='git', scm_url=PROJECT_URL)
    sync_project(project)
    template = get_or_create('/job_templates/', 'e2e-hello', inventory=inventory['id'], project=project['id'], playbook='hello_world.yml')
    job = run_job(template)
    json.dump({'org': org['id'], 'credential': cred['id'], 'inventory': inventory['id'], 'project': project['id'],
               'template': template['id'], 'job': job['id'], 'version': ping.get('version')}, open(state_file, 'w'))
    run_adhoc(inventory, cred['id'])


def verify(state_file):
    state = json.load(open(state_file))
    ping = api('GET', '/ping/')
    check('ping after upgrade', ping.get('version') and ping['version'] != state['version'], f"{state['version']} -> {ping.get('version')}")
    # Capacity is recalculated by the next node heartbeat after the restart
    start = time.time()
    while not any(g['name'] == 'controlplane' and g['capacity'] > 0 for g in ping['instance_groups']) and time.time() - start < 180:
        time.sleep(5)
        ping = api('GET', '/ping/')
    check('controlplane has capacity', any(g['name'] == 'controlplane' and g['capacity'] > 0 for g in ping['instance_groups']),
          f"after {time.time() - start:.0f}s: {ping['instance_groups']}")
    old = api('GET', f"/jobs/{state['job']}/")
    check('job from before the upgrade still readable', old['status'] == 'successful' and 'Hello World!' in stdout(f"/jobs/{state['job']}/"), old['status'])
    cred = api('GET', f"/credentials/{state['credential']}/")
    check('credential password still stored encrypted', cred['inputs'].get('password') == '$encrypted$', cred['inputs'].get('password'))
    sync_project(api('GET', f"/projects/{state['project']}/"))
    run_job(api('GET', f"/job_templates/{state['template']}/"))
    run_adhoc(api('GET', f"/inventories/{state['inventory']}/"), state['credential'])


def wait_for_log(text, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        received = requests.get('http://127.0.0.1:18090/received', timeout=10).json()
        if any(text in body for body in received):
            return True
        time.sleep(3)
    return False


def logging_check(state_file):
    """External logging through rsyslog/omhttp (needs the compose profile "logging")."""
    state = json.load(open(state_file))
    api('PATCH', '/settings/logging/', json={
        'LOG_AGGREGATOR_HOST': 'http://log_listener', 'LOG_AGGREGATOR_PORT': 8090, 'LOG_AGGREGATOR_TYPE': 'other',
        'LOG_AGGREGATOR_PROTOCOL': 'https', 'LOG_AGGREGATOR_VERIFY_CERT': False, 'LOG_AGGREGATOR_LEVEL': 'INFO',
        'LOG_AGGREGATOR_LOGGERS': ['awx', 'activity_stream', 'job_events', 'system_tracking'], 'LOG_AGGREGATOR_ENABLED': True})
    # rsyslog is reconfigured asynchronously after the settings change
    deadline, r = time.time() + 120, None
    while time.time() < deadline:
        r = requests.post(f'{API}/settings/logging/test/', headers=AUTH, timeout=60)
        if r.status_code == 202:
            break
        time.sleep(5)
    check('logging test endpoint (rsyslog config with omhttp)', r.status_code == 202, f'{r.status_code} {r.text[:200]}')
    # Each call sends one test message; messages sent before rsyslogd has restarted with the
    # new configuration are lost, so repeat until one arrives.
    delivered = False
    for _ in range(12):
        requests.post(f'{API}/settings/logging/test/', headers=AUTH, timeout=60)
        if wait_for_log('AWX Connection Test Message', timeout=10):
            delivered = True
            break
    check('test message delivered via rsyslog/omhttp', delivered)
    # The callback receiver picks up LOG_AGGREGATOR_ENABLED only after its settings cache expires
    time.sleep(60)
    run_job(api('GET', f"/job_templates/{state['template']}/"))
    check('job events forwarded to the log receiver', wait_for_log('Hello World'))
    api('PATCH', '/settings/logging/', json={'LOG_AGGREGATOR_ENABLED': False})


if __name__ == '__main__':
    {'seed': seed, 'verify': verify, 'logging': logging_check}[sys.argv[1]](sys.argv[2])
    print(f'\n{sum(results)}/{len(results)} e2e checks passed')
    sys.exit(0 if all(results) else 1)
