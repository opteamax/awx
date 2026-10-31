# AWX 24.6.1 on Django 5.2 — opteamax fork

[![Opteamax image](https://github.com/opteamax/awx/actions/workflows/opteamax-image.yml/badge.svg?branch=django5%2F24.6.1)](https://github.com/opteamax/awx/actions/workflows/opteamax-image.yml)

**[English](#english)** · **[Deutsch](#deutsch)**

> This is an unofficial fork maintained by [Opteamax GmbH](https://opteam.ax). It is not
> affiliated with or supported by Red Hat or the Ansible project. Please report problems with
> it [here](https://github.com/opteamax/awx/issues), not upstream.

---

## English

### What this is

AWX has made no release since 24.6.1 (July 2024). Its Python dependencies have collected
vulnerabilities that cannot be fixed by rebuilding the image, mainly because 24.6.1 is tied to
Django 4.2, whose security support ended in April 2026. Upstream `devel` is no way out for
most users: it has dropped the classic UI, LDAP/SAML/RADIUS/TACACS+ and social login, and
OAuth2 tokens.

This fork keeps AWX 24.6.1 as it is — same UI, same API, same features, same database schema —
and replaces what is underneath:

- **Django 5.2 LTS** (supported until April 2028) instead of Django 4.2
- **current, patched Python dependencies**; the image build fails on any fixable high or
  critical vulnerability
- **AlmaLinux 9** (supported until 2032) instead of CentOS Stream 9 as base image
- an image that builds again (24.6.1 itself no longer builds today)

Details, every deviation from 24.6.1 and the known remaining issues are in
[OPTEAMAX-FORK.md](OPTEAMAX-FORK.md).

### Images

GitHub Actions builds the image from branch `django5/24.6.1`, scans it with
[trivy](https://trivy.dev) and only then publishes it. Every Monday it is rebuilt with the
latest AlmaLinux updates, and the published image is scanned every day.

| Tag | Meaning |
|---|---|
| `ghcr.io/opteamax/awx:24.6.1-django5` | the latest build — moves |
| `ghcr.io/opteamax/awx:24.6.1-django5-<YYYYMMDD>-<commit>` | one build — never changes |

Use a dated tag (or its digest) in production, so you know exactly what runs and can go back.
The available tags are listed on the
[package page](https://github.com/opteamax/awx/pkgs/container/awx). AWX reports its version as
`24.6.1+opteamax.django5`.

### Is it for you?

- **You run AWX 24.6.1.** Older versions: upgrade to 24.6.1 first, the usual way; the fork
  continues from 24.6.1's database.
- **You deploy with containers**: Docker Compose / Podman, or the awx-operator on Kubernetes.
- **Tested**: the full Python test suite, PostgreSQL 16, a Docker Compose deployment upgraded
  from `quay.io/ansible/awx:24.6.1` with real jobs (project sync from git, playbook run in an
  execution environment through receptor, ad hoc command), credentials written by 24.6.1, the
  classic UI in a browser, external logging through rsyslog, SAML login end to end.
  **Not tested**: deployments by the awx-operator, real LDAP/RADIUS/TACACS+ servers (only unit
  tests). If you use one of these, try it on a copy first and tell us how it went.

### What changes for you

Nothing in AWX's own database schema. Things you may notice:

- **SSO links**: logins via GitHub/Google/Azure AD/OIDC/SAML now start at
  `/sso/launch/<backend>/` (social-auth requires a POST with a CSRF token now). The UI does this
  for you. Bookmarks or IdP portal links pointing to `/sso/login/<backend>/` get HTTP 405 —
  change them to `/sso/launch/<backend>/` (SAML: `/sso/launch/saml/?idp=<name>`).
- **SAML**: responses must answer the AuthnRequest AWX sent (`InResponseTo` is checked).
  IdP-initiated logins still work.
- **SSO error messages** coming from social-auth are generic now ("Authentication could not be
  completed."); details are in the AWX log.
- **social_django** brings seven new migrations (`0016`-`0022`), applied by `awx-manage migrate`.
  One adds a check constraint `uid <> ''` and fails if such rows exist — see step 1 below.

### Upgrading, step by step

The upgrade is a change of the container image plus `awx-manage migrate`. Plan for a few
minutes of downtime. Your `SECRET_KEY` must stay the same — it does when you only change the
image; without it, AWX cannot decrypt the stored credentials.

#### 1. Check

Find out what you run and that the social-auth table is clean (both inside the AWX web
container, e.g. `docker exec -it awx_web bash`, or `kubectl exec` into the web pod):

```bash
awx-manage --version          # must print 24.6.1
awx-manage dbshell <<'SQL'
SELECT id, provider, user_id FROM social_auth_usersocialauth WHERE uid = '';
SQL
```

The query must return no rows. If it does, those social logins are broken anyway (no user id
from the provider); delete them, the users get a new link on their next login.

Let running jobs finish and keep schedules from starting new ones during the upgrade (e.g.
disable them, or pick a quiet time). A job that runs while the containers are replaced fails.

#### 2. Back up

```bash
# database (adjust container, user and database name)
docker exec awx_postgres pg_dump -U awx -Fc awx > awx-before-django5.dump
```

Keep the secret key and your settings files as well — for a Compose setup the files mounted to
`/etc/tower/` (`SECRET_KEY`, `settings.py`), with the awx-operator the secrets
`<name>-secret-key`, `<name>-postgres-configuration` and the AWX custom resource. If AWX runs in
a VM, a snapshot of the VM in addition does no harm.

#### 3a. Docker Compose / Podman

1. Pull the image: `docker pull ghcr.io/opteamax/awx:24.6.1-django5-<YYYYMMDD>-<commit>`
2. **If you build your own image on top of the AWX image** (e.g. to add podman, receptor or
   extra Python packages): rebuild it with the new base — usually `FROM` or a build argument
   such as `--build-arg BASE_IMAGE=ghcr.io/opteamax/awx:…`. The base is AlmaLinux 9 with `dnf`,
   as CentOS Stream 9 was, so such Dockerfiles normally work unchanged. Patches you apply to
   AWX's Python files keep working as long as they patched 24.6.1, since the AWX code is the same.
3. Change the image of all services that run the AWX image (web, task, and often receptor or
   rsyslog). A `docker-compose.override.yml` keeps a generated compose file untouched:

   ```yaml
   services:
     awx_web:
       image: ghcr.io/opteamax/awx:24.6.1-django5-<YYYYMMDD>-<commit>
     awx_task:
       image: ghcr.io/opteamax/awx:24.6.1-django5-<YYYYMMDD>-<commit>
   ```

4. Recreate the containers and migrate (only once, from one container):

   ```bash
   docker compose up -d
   docker exec awx_web awx-manage migrate --noinput
   docker exec awx_web awx-manage showmigrations --plan | grep -c '\[ \]'   # must print 0
   ```

   A task container that runs `wait-for-migrations` waits until this is done.
5. The execution-environment images podman pulled inside the old containers are gone with
   them; AWX pulls them again on the first job (pull policy "missing"), or pull them now:
   `docker exec awx_task podman pull <your EE image>`.

#### 3b. awx-operator (Kubernetes) — untested

Point the AWX custom resource at the fork; the operator rolls the pods and runs the
migrations itself. Use the operator release that belongs to 24.6.1 (2.19.1) — newer operators
expect a newer AWX.

```yaml
spec:
  image: ghcr.io/opteamax/awx
  image_version: 24.6.1-django5-<YYYYMMDD>-<commit>
  image_pull_policy: IfNotPresent
```

The rsyslog and init containers use the same image; that is intended. If you set
`control_plane_ee_image` or `ee_images`, they are not affected.

#### 4. Verify

- `curl -s https://<your-awx>/api/v2/ping/` reports `"version": "24.6.1+opteamax.django5"`.
- Log in to the UI; open a job from before the upgrade, including its output.
- Sync a project, run a job template and an ad hoc command.
- Check that a credential still works (a job that uses it), and every login method you use
  (local, LDAP, SAML, …).
- If you forward logs to an external aggregator, use "Test" in Settings → Logging.

### Going back

- **Before `awx-manage migrate`**: put the old image back and recreate the containers.
- **After it**: the old image does not know the new social_django migrations. Restore the
  database dump from step 2 (or the VM snapshot) and start the old image:

  ```bash
  docker compose stop awx_web awx_task
  docker exec awx_postgres sh -c 'dropdb -U awx awx && createdb -U awx awx'
  docker exec -i awx_postgres pg_restore -U awx -d awx --no-owner < awx-before-django5.dump
  # remove the image override, then
  docker compose up -d
  ```

  Everything AWX recorded after the upgrade (jobs, changes) is lost with the restore.

### Good to know

- **External logging** (Splunk, Loki, Elastic, …) needs an rsyslog process next to AWX. The
  awx-operator runs one as a sidecar; many Compose setups do not, so those settings silently do
  nothing there — with 24.6.1 just as with this fork. Run the image a second time as such a
  sidecar with `SUPERVISOR_CONFIG_PATH=/etc/supervisord_rsyslog.conf`, sharing the rsyslog
  socket and config volumes with web and task (see
  `tools/django5-tests/compose-e2e/docker-compose.yml`, profile `logging`).
- **Execution environments are separate images.** This fork updates the AWX control plane
  only; keep your EE images up to date yourself.
- **Building it yourself**: `make awx-kube-build VERSION=24.6.1+opteamax.django5
  IMAGE_KUBE=<your tag>` on branch `django5/24.6.1`; the tests are in
  [tools/django5-tests](tools/django5-tests/README.md).

---

## Deutsch

### Worum es geht

AWX hat seit 24.6.1 (Juli 2024) kein Release mehr veröffentlicht. In seinen
Python-Abhängigkeiten haben sich Schwachstellen angesammelt, die sich durch einen Neubau des
Images nicht beheben lassen — vor allem, weil 24.6.1 an Django 4.2 hängt, dessen
Sicherheitsunterstützung im April 2026 endete. Upstream `devel` ist für die meisten kein
Ausweg: Dort sind die klassische Oberfläche, LDAP/SAML/RADIUS/TACACS+ und Social Login sowie
OAuth2-Tokens entfernt.

Dieser Fork lässt AWX 24.6.1 wie es ist — gleiche Oberfläche, gleiche API, gleiche Funktionen,
gleiches Datenbankschema — und tauscht aus, was darunter liegt:

- **Django 5.2 LTS** (unterstützt bis April 2028) statt Django 4.2
- **aktuelle, gepatchte Python-Abhängigkeiten**; der Image-Build bricht bei jeder behebbaren
  Schwachstelle der Stufe hoch oder kritisch ab
- **AlmaLinux 9** (unterstützt bis 2032) statt CentOS Stream 9 als Basis-Image
- ein Image, das sich wieder bauen lässt (24.6.1 selbst baut heute nicht mehr)

Details, jede Abweichung von 24.6.1 und die bekannten offenen Punkte stehen in
[OPTEAMAX-FORK.md](OPTEAMAX-FORK.md) (Englisch).

### Images

GitHub Actions baut das Image aus dem Branch `django5/24.6.1`, prüft es mit
[trivy](https://trivy.dev) und veröffentlicht es erst danach. Jeden Montag wird es mit den
neuesten AlmaLinux-Updates neu gebaut, und das veröffentlichte Image wird täglich gescannt.

| Tag | Bedeutung |
|---|---|
| `ghcr.io/opteamax/awx:24.6.1-django5` | der neueste Build — wandert mit |
| `ghcr.io/opteamax/awx:24.6.1-django5-<JJJJMMTT>-<commit>` | genau ein Build — ändert sich nie |

Nimm in Produktion einen datierten Tag (oder dessen Digest): Dann weißt du genau, was läuft,
und kannst zurück. Die vorhandenen Tags stehen auf der
[Paketseite](https://github.com/opteamax/awx/pkgs/container/awx). AWX meldet die Version als
`24.6.1+opteamax.django5`.

### Passt das für dich?

- **Du betreibst AWX 24.6.1.** Ältere Versionen zuerst wie gewohnt auf 24.6.1 bringen; der Fork
  setzt auf der Datenbank von 24.6.1 auf.
- **Du betreibst AWX in Containern**: Docker Compose / Podman oder den awx-operator auf
  Kubernetes.
- **Getestet**: die komplette Python-Testsuite, PostgreSQL 16, ein Docker-Compose-Betrieb,
  aktualisiert von `quay.io/ansible/awx:24.6.1` mit echten Jobs (Projekt-Sync aus Git,
  Playbook-Lauf in einem Execution Environment über receptor, Ad-hoc-Kommando), von 24.6.1
  gespeicherte Credentials, die klassische Oberfläche im Browser, externes Logging über
  rsyslog, SAML-Login von Anfang bis Ende.
  **Nicht getestet**: Installationen über den awx-operator, echte LDAP/RADIUS/TACACS+-Server
  (nur Unit-Tests). Wer so etwas nutzt: erst an einer Kopie ausprobieren und uns gern
  berichten.

### Was sich für dich ändert

Nichts am Datenbankschema von AWX selbst. Was auffallen kann:

- **SSO-Links**: Logins über GitHub/Google/Azure AD/OIDC/SAML starten jetzt unter
  `/sso/launch/<backend>/` (social-auth verlangt inzwischen einen POST mit CSRF-Token). Die
  Oberfläche erledigt das selbst. Lesezeichen oder Links aus IdP-Portalen auf
  `/sso/login/<backend>/` liefern HTTP 405 — auf `/sso/launch/<backend>/` ändern (SAML:
  `/sso/launch/saml/?idp=<name>`).
- **SAML**: Antworten müssen zum AuthnRequest passen, den AWX geschickt hat (`InResponseTo` wird
  geprüft). Vom IdP angestoßene Logins funktionieren weiter.
- **SSO-Fehlermeldungen** aus social-auth sind jetzt allgemein gehalten („Authentication could
  not be completed.“); Details stehen im AWX-Log.
- **social_django** bringt sieben neue Migrationen (`0016`–`0022`) mit, die `awx-manage migrate`
  einspielt. Eine davon legt den Check-Constraint `uid <> ''` an und scheitert, wenn es solche
  Zeilen gibt — siehe Schritt 1.

### Umstellung Schritt für Schritt

Die Umstellung ist ein Wechsel des Container-Images plus `awx-manage migrate`. Plane ein paar
Minuten Ausfall ein. Dein `SECRET_KEY` muss gleich bleiben — das tut er, wenn du nur das Image
wechselst; ohne ihn kann AWX die gespeicherten Credentials nicht mehr entschlüsseln.

#### 1. Prüfen

Welche Version läuft, und ist die Social-Auth-Tabelle sauber? (Beides im AWX-Web-Container,
z. B. `docker exec -it awx_web bash`, oder per `kubectl exec` im Web-Pod.)

```bash
awx-manage --version          # muss 24.6.1 ausgeben
awx-manage dbshell <<'SQL'
SELECT id, provider, user_id FROM social_auth_usersocialauth WHERE uid = '';
SQL
```

Die Abfrage darf keine Zeilen liefern. Falls doch: Diese Social-Logins sind ohnehin kaputt
(keine Benutzerkennung vom Provider); lösche sie, die Benutzer werden beim nächsten Login neu
verknüpft.

Laufende Jobs zu Ende laufen lassen und verhindern, dass Schedules während der Umstellung neue
starten (z. B. deaktivieren oder eine ruhige Zeit wählen). Ein Job, der läuft, während die
Container ersetzt werden, schlägt fehl.

#### 2. Sichern

```bash
# Datenbank (Container, Benutzer und Datenbankname anpassen)
docker exec awx_postgres pg_dump -U awx -Fc awx > awx-vor-django5.dump
```

Sichere auch Secret Key und Einstellungen — bei Compose die nach `/etc/tower/` gemounteten
Dateien (`SECRET_KEY`, `settings.py`), beim awx-operator die Secrets `<name>-secret-key`,
`<name>-postgres-configuration` und die AWX-Custom-Resource. Läuft AWX in einer VM, schadet ein
zusätzlicher VM-Snapshot nicht.

#### 3a. Docker Compose / Podman

1. Image holen: `docker pull ghcr.io/opteamax/awx:24.6.1-django5-<JJJJMMTT>-<commit>`
2. **Wenn du ein eigenes Image auf dem AWX-Image aufbaust** (z. B. für podman, receptor oder
   zusätzliche Python-Pakete): mit der neuen Basis neu bauen — meist über `FROM` oder ein
   Build-Argument wie `--build-arg BASE_IMAGE=ghcr.io/opteamax/awx:…`. Die Basis ist AlmaLinux 9
   mit `dnf`, wie vorher CentOS Stream 9; solche Dockerfiles laufen normalerweise unverändert.
   Patches an AWX-Python-Dateien funktionieren weiter, sofern sie für 24.6.1 geschrieben waren —
   der AWX-Code ist derselbe.
3. Das Image aller Dienste ändern, die das AWX-Image nutzen (Web, Task, oft auch receptor oder
   rsyslog). Eine `docker-compose.override.yml` lässt eine generierte Compose-Datei unberührt:

   ```yaml
   services:
     awx_web:
       image: ghcr.io/opteamax/awx:24.6.1-django5-<JJJJMMTT>-<commit>
     awx_task:
       image: ghcr.io/opteamax/awx:24.6.1-django5-<JJJJMMTT>-<commit>
   ```

4. Container neu erstellen und migrieren (nur einmal, aus einem Container):

   ```bash
   docker compose up -d
   docker exec awx_web awx-manage migrate --noinput
   docker exec awx_web awx-manage showmigrations --plan | grep -c '\[ \]'   # muss 0 ausgeben
   ```

   Ein Task-Container, der `wait-for-migrations` aufruft, wartet, bis das erledigt ist.
5. Die Execution-Environment-Images, die podman in den alten Containern gezogen hatte, sind mit
   ihnen weg; AWX holt sie beim ersten Job neu (Pull-Policy „missing“), oder du ziehst sie
   gleich: `docker exec awx_task podman pull <dein EE-Image>`.

#### 3b. awx-operator (Kubernetes) — ungetestet

Die AWX-Custom-Resource auf den Fork zeigen lassen; der Operator tauscht die Pods und migriert
selbst. Nutze das Operator-Release, das zu 24.6.1 gehört (2.19.1) — neuere Operatoren erwarten
ein neueres AWX.

```yaml
spec:
  image: ghcr.io/opteamax/awx
  image_version: 24.6.1-django5-<JJJJMMTT>-<commit>
  image_pull_policy: IfNotPresent
```

rsyslog- und Init-Container nutzen dasselbe Image; das ist so gewollt. `control_plane_ee_image`
und `ee_images` sind davon nicht betroffen.

#### 4. Prüfen

- `curl -s https://<dein-awx>/api/v2/ping/` meldet `"version": "24.6.1+opteamax.django5"`.
- In der Oberfläche anmelden; einen Job von vor der Umstellung samt Ausgabe öffnen.
- Ein Projekt synchronisieren, ein Job-Template und ein Ad-hoc-Kommando starten.
- Prüfen, dass Credentials funktionieren (ein Job, der eines nutzt), und jede Anmeldeart, die du
  nutzt (lokal, LDAP, SAML, …).
- Wer Logs an einen externen Aggregator schickt: „Test“ unter Einstellungen → Logging.

### Zurück

- **Vor `awx-manage migrate`**: altes Image wieder eintragen und Container neu erstellen.
- **Danach**: Das alte Image kennt die neuen social_django-Migrationen nicht. Den Dump aus
  Schritt 2 (oder den VM-Snapshot) zurückspielen und das alte Image starten:

  ```bash
  docker compose stop awx_web awx_task
  docker exec awx_postgres sh -c 'dropdb -U awx awx && createdb -U awx awx'
  docker exec -i awx_postgres pg_restore -U awx -d awx --no-owner < awx-vor-django5.dump
  # Image-Override entfernen, dann
  docker compose up -d
  ```

  Alles, was AWX nach der Umstellung aufgezeichnet hat (Jobs, Änderungen), geht dabei verloren.

### Gut zu wissen

- **Externes Logging** (Splunk, Loki, Elastic, …) braucht einen rsyslog-Prozess neben AWX. Der
  awx-operator startet ihn als Sidecar; viele Compose-Installationen nicht — dort tun diese
  Einstellungen stillschweigend nichts, mit 24.6.1 genauso wie mit diesem Fork. Abhilfe: das
  Image ein zweites Mal als Sidecar mit `SUPERVISOR_CONFIG_PATH=/etc/supervisord_rsyslog.conf`
  starten, mit gemeinsamen Volumes für rsyslog-Socket und -Konfiguration mit Web und Task (siehe
  `tools/django5-tests/compose-e2e/docker-compose.yml`, Profil `logging`).
- **Execution Environments sind eigene Images.** Dieser Fork aktualisiert nur die AWX-Steuerung;
  deine EE-Images musst du selbst aktuell halten.
- **Selbst bauen**: `make awx-kube-build VERSION=24.6.1+opteamax.django5 IMAGE_KUBE=<dein Tag>`
  auf dem Branch `django5/24.6.1`; die Tests liegen in
  [tools/django5-tests](tools/django5-tests/README.md).

---

# Upstream AWX README

[![CI](https://github.com/ansible/awx/actions/workflows/ci.yml/badge.svg?branch=devel)](https://github.com/ansible/awx/actions/workflows/ci.yml) [![Code of Conduct](https://img.shields.io/badge/code%20of%20conduct-Ansible-yellow.svg)](https://docs.ansible.com/ansible/latest/community/code_of_conduct.html) [![Apache v2 License](https://img.shields.io/badge/license-Apache%202.0-brightgreen.svg)](https://github.com/ansible/awx/blob/devel/LICENSE.md) [![AWX Mailing List](https://img.shields.io/badge/mailing%20list-AWX-orange.svg)](https://groups.google.com/g/awx-project)
[![Ansible Matrix](https://img.shields.io/badge/matrix-Ansible%20Community-blueviolet.svg?logo=matrix)](https://chat.ansible.im/#/welcome) [![Ansible Discourse](https://img.shields.io/badge/discourse-Ansible%20Community-yellowgreen.svg?logo=discourse)](https://forum.ansible.com)

<img src="https://raw.githubusercontent.com/ansible/awx-logos/master/awx/ui/client/assets/logo-login.svg?sanitize=true" width=200 alt="AWX" />

AWX provides a web-based user interface, REST API, and task engine built on top of [Ansible](https://github.com/ansible/ansible). It is one of the upstream projects for [Red Hat Ansible Automation Platform](https://www.ansible.com/products/automation-platform).

To install AWX, please view the [Install guide](./INSTALL.md).

To learn more about using AWX, view the [AWX docs site](https://ansible.readthedocs.io/projects/awx/en/latest/).

The AWX Project Frequently Asked Questions can be found [here](https://www.ansible.com/awx-project-faq).

The AWX logos and branding assets are covered by [our trademark guidelines](https://github.com/ansible/awx-logos/blob/master/TRADEMARKS.md).

Contributing
------------

- Refer to the [Contributing guide](./CONTRIBUTING.md) to get started developing, testing, and building AWX.
- All code submissions are made through pull requests against the `devel` branch.
- All contributors must use git commit --signoff for any commit to be merged and agree that usage of --signoff constitutes agreement with the terms of [DCO 1.1](./DCO_1_1.md)
- Take care to make sure no merge commits are in the submission, and use `git rebase` vs. `git merge` for this reason.
- If submitting a large code change, it's a good idea to join the `#ansible-awx` channel on web.libera.chat and talk about what you would like to do or add first. This not only helps everyone know what's going on, but it also helps save time and effort if the community decides some changes are needed.

Reporting Issues
----------------

If you're experiencing a problem that you feel is a bug in AWX or have ideas for improving AWX, we encourage you to open an issue and share your feedback. But before opening a new issue, we ask that you please take a look at our [Issues guide](./ISSUES.md).

Code of Conduct
---------------

We ask all of our community members and contributors to adhere to the [Ansible code of conduct](http://docs.ansible.com/ansible/latest/community/code_of_conduct.html). If you have questions or need assistance, please reach out to our community team at [codeofconduct@ansible.com](mailto:codeofconduct@ansible.com)

Get Involved
------------

We welcome your feedback and ideas. Here's how to reach us with feedback and questions:

- Join the [Ansible AWX channel on Matrix](https://matrix.to/#/#awx:ansible.com)
- Join the [Ansible Community Forum](https://forum.ansible.com)
