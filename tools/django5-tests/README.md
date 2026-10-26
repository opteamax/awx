# Django 5 port test harness

Test tooling for the opteamax fork of AWX 24.6.1 running on Django 5.2. The regular
AWX development environment (`make docker-compose`) builds the full UI and receptor;
this harness only needs Docker and checks the Python side in a `python:3.11` container.

Every check can also run against an unmodified reference (`--baseline 24.6.1`), so a
change can be judged against what already failed before it.

## Usage

```bash
T=tools/django5-tests/django5-tests.sh
$T image                          # build the test image once
$T pytest                         # unit + functional + conf + sso tests (SQLite)
$T pytest awx/main/tests/unit -x  # any pytest arguments
$T pgcheck                        # PostgreSQL: fresh migrate, makemigrations --check, DAB join
$T upgrade-check 24.6.1           # migrate a DB with 24.6.1, then with the working tree
$T smoke                          # uwsgi + daphne: login/logout, websocket, OAuth2, API
$T make-requirements              # Makefile install path in a fresh venv (quick, Debian)
$T build-image                    # production image via make awx-kube-build (CentOS Stream 9)
$T compile --upgrade-package foo==1.2   # recompile requirements.txt, other pins unchanged
$T services-down                  # stop PostgreSQL/Redis containers

$T --baseline 24.6.1 pytest       # same checks against the unmodified release
$T --dab ../django-ansible-base pytest  # use a local django-ansible-base checkout
```

Results (JUnit XML, `pip freeze`, compiled requirements) go to `~/.cache/awx-django5-tests`
unless `--out` is given. To see which tests newly fail compared to the release:

```bash
$T --baseline 24.6.1 --out /tmp/baseline pytest
$T pytest
tools/django5-tests/compare_junit.py /tmp/baseline/pytest.xml ~/.cache/awx-django5-tests/pytest.xml
```

Virtualenvs live in the Docker volume `awx-django5-test-venvs`, keyed by a hash of the
requirements, so changing a pin creates a fresh venv on the next run.

All containers use `--network host` (PostgreSQL on port 55432, Redis on 56379), which also
avoids bridge networking issues with TLS on some hosts.

## End-to-end upgrade test with real jobs

`compose-e2e/run-e2e.sh` reproduces the docker compose stack of
[opteamax/ansible-awx-installer](https://github.com/opteamax/ansible-awx-installer) (web, task,
receptor, postgres, redis; configuration rendered from `bootstrap_awx.py`), builds the
installer's `Dockerfile.awx` on top of two AWX images and tests the upgrade between them:

```bash
$T build-image localhost/opteamax/awx:24.6.1-django5
tools/django5-tests/compose-e2e/run-e2e.sh quay.io/ansible/awx:24.6.1 \
    localhost/opteamax/awx:24.6.1-django5 ../ansible-awx-installer
```

Phase 1 sets up the old release the way the installer does and runs a git project sync
(github.com/ansible/ansible-tower-samples), a job in the execution environment via receptor
and podman, and an ad hoc command. Phase 2 switches to the new image, migrates, checks the old
job and the encrypted credential, and runs the same jobs again. `--keep` leaves the stack up
(port 18052, admin / e2e-admin-pass).

## Known baseline failures

These fail on the unmodified 24.6.1 release too and are unrelated to the port:

- `test_generic.py`, `test_job_template.py`: collection errors with current pytest
  (marks applied to fixtures)
- `test_settings.py::test_logging_aggregator_connection_test_valid`: needs `rsyslogd`
- `test_credential.py::test_default_cred_types`, `test_db.py::test_sql_above_threshold`

## Upgrading a dependency

1. Raise the lower bound in `requirements/requirements.in` and add a comment why.
2. `$T compile --upgrade-package <name>==<version>` and copy the result to
   `requirements/requirements.txt`; review that only the intended pins moved.
3. Update `licenses/` if packages were added or removed (`test_licenses.py` checks this).
4. Run `pytest`, `pgcheck` and `smoke` and compare against the known failures above.
