#!/bin/bash
# Usage: manage.sh <database> <step>...
# Steps: migrate | makemigrations-check | showmigrations | resource-join | seed-secrets | verify-secrets
# Runs against PostgreSQL on 127.0.0.1:55432.
source /tools/container/common.sh
export PGDATABASE=$1; shift
cp /tools/container/settings/*.py /work/
export DJANGO_SETTINGS_MODULE=pgsettings
M() { python -m django "$@" 2>&1 | grep -vE "staticfiles.W004|^System check identified|^WARNINGS:|^$"; }
for step in "$@"; do
  echo "=== $step"
  case $step in
    migrate) M migrate --noinput | grep -vE '^\s+Applying .* OK$' ;;
    makemigrations-check) M makemigrations --check --dry-run ;;
    showmigrations) echo "applied: $(python -m django showmigrations --plan 2>/dev/null | grep -c '\[X\]')" ;;
    resource-join) python - <<'EOF'
# The django-ansible-base resource relation must join on the casted primary key only.
import django; django.setup()
from awx.main.models import Organization
org = Organization.objects.create(name='dab-join-check')
try:
    sql = str(Organization.objects.select_related('resource').filter(pk=org.pk).query)
    join = sql[sql.index('LEFT OUTER JOIN'):sql.index('WHERE')]
    print('JOIN:', join)
    assert '::integer' not in join, 'unexpected integer cast of Resource.object_id in join'
    o = Organization.objects.select_related('resource').get(pk=org.pk)
    assert Organization.objects.filter(resource__ansible_id=o.resource.ansible_id).count() == 1
    assert [x.resource.ansible_id for x in Organization.objects.prefetch_related('resource').filter(pk=org.pk)] == [o.resource.ansible_id]
    print('resource-join OK')
finally:
    org.delete()
EOF
    ;;
    seed-secrets) python - <<'EOF'
# Store encrypted values with the code under test (e.g. the old release).
import django; django.setup()
from django.conf import settings
from awx.main.models import Credential, CredentialType, Organization, OAuth2Application
org, _ = Organization.objects.get_or_create(name='secrets-check')
ssh = CredentialType.objects.get(namespace='ssh', managed=True)
Credential.objects.create(name='secrets-check', credential_type=ssh, organization=org,
                          inputs={'username': 'u', 'password': 'pw-secret-check', 'ssh_key_data': 'KEY-secret-check'})
settings.SOCIAL_AUTH_GITHUB_SECRET = 'setting-secret-check'
app = OAuth2Application.objects.create(name='secrets-check', organization=org, client_type='confidential',
                                       authorization_grant_type='password')
open('/out/secrets-check-client-secret', 'w').write(app.client_secret)
print('seeded encrypted credential, setting and OAuth2 application')
EOF
    ;;
    verify-secrets) python - <<'EOF'
# Decrypt values stored by seed-secrets, possibly written by another release.
import django; django.setup()
from django.conf import settings
from awx.main.models import Credential, OAuth2Application
from awx.main.utils.encryption import decrypt_field
cred = Credential.objects.get(name='secrets-check')
assert cred.inputs['password'].startswith('$encrypted$'), 'password not stored encrypted'
assert decrypt_field(cred, 'password') == 'pw-secret-check', 'credential password mismatch'
assert decrypt_field(cred, 'ssh_key_data') == 'KEY-secret-check', 'ssh key mismatch'
assert settings.SOCIAL_AUTH_GITHUB_SECRET == 'setting-secret-check', 'encrypted setting mismatch'
app = OAuth2Application.objects.get(name='secrets-check')
assert app.client_secret == open('/out/secrets-check-client-secret').read(), 'OAuth2 client secret mismatch'
print('verify-secrets OK')
EOF
    ;;
    *) echo "unknown step $step"; exit 2 ;;
  esac
done
