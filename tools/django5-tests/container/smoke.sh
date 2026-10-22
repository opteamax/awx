#!/bin/bash
# Usage: smoke.sh <database>
# Starts uwsgi (:8013) and daphne (:8051) against PostgreSQL :55432 / Redis :56379
# and runs smoke.py against them.
source /tools/container/common.sh
set +e
export PGDATABASE=$1
cp /tools/container/settings/*.py /work/
export DJANGO_SETTINGS_MODULE=smokesettings
M() { python -m django "$@"; }
echo "channels $(python -c 'import channels; print(channels.__version__)')"

echo "=== migrate"; M migrate --noinput 2>&1 | tail -1
echo "=== check --deploy"; M check --deploy 2>&1 | grep -E "^System check identified|ERRORS|\.E[0-9]" | head -5
echo "=== collectstatic"; M collectstatic --noinput 2>&1 | tail -1
python - <<'EOF'
import django; django.setup()
from awx.main.models import User, Organization
u, _ = User.objects.get_or_create(username='admin', defaults={'is_superuser': True, 'is_staff': True, 'email': 'admin@example.com'})
u.set_password('smoke-pass'); u.save()
Organization.objects.get_or_create(name='Default')
EOF

uwsgi --http 127.0.0.1:8013 --module awx.wsgi:application --master --processes 2 --enable-threads --lazy-apps \
      --static-map /static=/var/lib/awx/public/static --die-on-term > /tmp/uwsgi.log 2>&1 &
daphne -b 127.0.0.1 -p 8051 --websocket_timeout -1 awx.asgi:channel_layer > /tmp/daphne.log 2>&1 &
for i in $(seq 60); do
  curl -sf -o /dev/null http://127.0.0.1:8013/api/v2/ping/ \
    && python -c 'import socket,sys; sys.exit(socket.socket().connect_ex(("127.0.0.1",8051)))' && break
  sleep 1
done

echo "=== smoke checks"
python /tools/container/smoke.py; rc=$?
echo "=== tracebacks"
for f in /var/log/tower/*.log /tmp/uwsgi.log /tmp/daphne.log; do
  grep -q Traceback "$f" && { echo "## $f"; grep -v "^\s*\^*\s*$" "$f" | grep -A40 -m3 Traceback; }
done | head -150
exit $rc
