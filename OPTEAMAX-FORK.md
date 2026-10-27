# opteamax fork of AWX 24.6.1

AWX has made no releases since 24.6.1 (July 2024). Upstream `devel` continues as the base for
Red Hat's product, but it has removed the classic UI, LDAP/SAML/RADIUS/TACACS+ and social
login (`awx/sso`) and OAuth2 tokens, so it does not replace 24.6.1 for us.

This fork keeps the AWX 24.6.1 feature set and brings its dependencies up to date:

- **Django 5.2 LTS** instead of Django 4.2, whose security support ended in April 2026
- **Dependency security upgrades**: a trivy scan of `requirements/requirements.txt` goes from
  217 known vulnerabilities (6 critical, 75 high) on 24.6.1 to 1 (medium, not reachable in
  AWX, see [Known remaining issues](#known-remaining-issues)), as of 2026-10-23

Branch: `django5/24.6.1`, based on the `24.6.1` tag. Where upstream `devel` already contains a
fix, it is cherry-picked (the commit message names the upstream commit).

## Related repositories

| Repository | Branch | Why |
|---|---|---|
| [opteamax/django-ansible-base](https://github.com/opteamax/django-ansible-base) | `awx-24.6.1-django5` | The revision AWX 24.6.1 was released against (`1213971`) plus Django 5 support. 24.6.1 referenced `@devel`, which is no longer compatible. |

The other git requirements (`ansible-runner`, `system-certifi`) are pinned to the commits that
were current at the 24.6.1 release.

## Upgrading an existing AWX 24.6.1 installation

The database schema of AWX itself is unchanged (still 249 migrations from 24.6.1).
`social_django` adds two migrations:

- `0016_alter_usersocialauth_extra_data`: metadata only
- `0017_usersocialauth_user_social_auth_uid_required`: adds a check constraint
  `uid <> ''`. It fails if such rows exist. Check before upgrading:

  ```sql
  SELECT id, provider, user_id FROM social_auth_usersocialauth WHERE uid = '';
  ```

Encrypted data (credentials, settings, OAuth2 application secrets) written by 24.6.1 stays
readable; `tools/django5-tests/django5-tests.sh upgrade-check 24.6.1` verifies this.

## Behaviour changes

- **SSO login start**: social-auth-app-django 6 only starts a login by POST with a CSRF token
  (login CSRF protection). `/api/v2/auth/` now returns `/sso/launch/<backend>/` as `login_url`;
  that page submits the POST and only accepts navigations from the same site. The 24.6.1 UI
  works unchanged. Direct links to `/sso/login/<backend>/` (bookmarks, IdP portals) return 405;
  use `/sso/launch/<backend>/` instead (for SAML: `/sso/launch/saml/?idp=<name>`).
- **SAML**: responses must answer the AuthnRequest AWX sent (`InResponseTo` is validated).
  IdP-initiated logins without `InResponseTo` still work.
- **Logout** keeps accepting GET, as the 24.6.1 UI uses it (Django 5 allows only POST by default).

## Building

`make awx-kube-build` (or `tools/django5-tests/django5-tests.sh build-image`) builds the
production image. Unmodified 24.6.1 no longer builds today; the fork fixes that and differs in:

- OpenSSL is no longer pinned to 3.0.7, which CentOS Stream 9 has dropped (upstream fix)
- `ui_next` is built from the ansible-ui commit of the 24.6.1 release (`UI_NEXT_GIT_COMMIT`);
  ansible-ui `main` now needs Node >= 18 while the image builds with Node 16
- pip 26.2, setuptools 83 (no `pkg_resources` any more), Cython 3
- `lxml` and `xmlsec` are built from source against the system libxml2 (`SRC_ONLY_PKGS` in the
  Makefile). uwsgi links the system libxml2; the libxml2 bundled in the lxml/xmlsec wheels
  would make xmlsec refuse to work in the web process. xmlsec stays at 1.3.13, newer versions
  do not compile against xmlsec1 1.2.29 of CentOS Stream 9.
- `requirements/requirements_git.txt` pulls django-ansible-base from the opteamax fork.

For [ansible-awx-installer](https://github.com/opteamax/ansible-awx-installer) the base image
must be configurable; branch `feature/awx-image-repo` adds the option "AWX image repository".

## Testing

`tools/django5-tests/` (see its [README](tools/django5-tests/README.md)) runs in containers:

- the Python test suite, PostgreSQL migration and upgrade checks, the Makefile install path
- a smoke test against uwsgi/daphne: login, websocket, wsrelay, OAuth2, SSO including a full
  SAML login
- `compose-e2e/run-e2e.sh`: the installer's docker compose stack, upgraded from
  `quay.io/ansible/awx:24.6.1` to the fork image (both with the installer's `Dockerfile.awx`):
  git project sync, a playbook run in the execution environment via receptor and podman, an
  ad hoc command, old jobs and credentials after the upgrade, and a browser check of the UI

Every check can also run against the unmodified release to tell regressions from existing
failures. The classic UI unit tests (2830) pass as on 24.6.1.

Not covered: real LDAP/RADIUS/TACACS+ servers (unit tests only), Kubernetes/awx-operator
deployments.

## Known remaining issues

- `twisted` CVE-2026-106454: DoS in the IMAP server of `twisted.mail`, no fixed version yet.
  AWX does not use `twisted.mail`.
- UI: the dependencies shipped to the browser have no known vulnerabilities (npm audit); the
  build tooling (react-scripts 5, webpack, ...) still has known issues and would need a
  larger migration. It does not end up in the image's runtime.
- Not scanned: packages of the CentOS Stream 9 base image, the execution environment image
  (`quay.io/ansible/awx-ee`), and what the installer's `Dockerfile.awx` adds (it installs
  ansible-core 2.16, which is end of life).
