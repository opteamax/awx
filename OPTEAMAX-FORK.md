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

The image build is unchanged (`make awx-kube-build` etc.), with these differences:

- pip 26.2, setuptools 83 (no `pkg_resources` any more), Cython 3
- `lxml` and `xmlsec` are built from source against the system libxml2 (`SRC_ONLY_PKGS` in the
  Makefile). uwsgi links the system libxml2; the libxml2 bundled in the lxml/xmlsec wheels
  would make xmlsec refuse to work in the web process.
- `requirements/requirements_git.txt` pulls django-ansible-base from the opteamax fork.

## Testing

`tools/django5-tests/` runs the test suite, PostgreSQL migration and upgrade checks, the
Makefile install path and a smoke test against uwsgi/daphne (login, websocket, wsrelay, OAuth2,
SSO including a full SAML login) in a `python:3.11` container. Every check can also run
against the unmodified release to tell regressions from existing failures. See its
[README](tools/django5-tests/README.md).

Not covered: running jobs (dispatcher, receptor, execution environments), real LDAP/RADIUS/
TACACS+ servers (only unit tests), the UI build, the awx-operator.

## Known remaining issues

- `twisted` CVE-2026-106454: DoS in the IMAP server of `twisted.mail`, no fixed version yet.
  AWX does not use `twisted.mail`.
- Dependencies not managed by `requirements.txt` are not covered by the scan: the UI
  (`awx/ui`, Node.js packages), the base image packages, ansible-core in execution environments.
