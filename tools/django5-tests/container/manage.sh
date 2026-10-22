#!/bin/bash
# Usage: manage.sh <database> <step>...
# Steps: migrate | makemigrations-check | showmigrations | resource-join
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
    *) echo "unknown step $step"; exit 2 ;;
  esac
done
