#!/bin/bash
# End-to-end upgrade test of the installer's docker compose stack with real jobs.
#
# Usage: run-e2e.sh OLD_AWX_IMAGE NEW_AWX_IMAGE INSTALLER_DIR [--keep]
#   e.g. run-e2e.sh quay.io/ansible/awx:24.6.1 localhost/opteamax/awx:24.6.1-django5 ../ansible-awx-installer
#
# Builds the installer's Dockerfile.awx on top of both images, sets the stack up with the old
# one the way bootstrap_awx.py does, runs a project sync, a job and an ad hoc command, then
# switches to the new image, migrates and checks old data and new jobs.
#
# SWAP_SCRIPT=<path> switches with that script instead (a deployment's own upgrade script that
# reads the pending.env written by swap() below) and requires it to report "done".
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
OLD=$1; NEW=$2; INSTALLER=$(cd "$3" && pwd); KEEP=${4:-}
TOOLS_IMAGE=awx-django5-test
STATE=$(mktemp -d)
export AWX_PORT=18052
cd "$HERE"

compose() { docker compose -f "$HERE/docker-compose.yml" "$@"; }
web() { docker exec awx_e2e_web "$@"; }
e2e() { docker run --rm --network host -v "$HERE:/e2e:ro" -v "$STATE:/state" "$TOOLS_IMAGE" python /e2e/e2e.py "$1" /state/state.json; }
PLAYWRIGHT_IMAGE=awx-e2e-playwright
ui() { docker run --rm --network host --ipc host -v "$HERE:/e2e:ro" -v "$STATE:/state" "$PLAYWRIGHT_IMAGE" python /e2e/ui_check.py /state/state.json; }

wait_web() {
  for _ in $(seq 120); do
    curl -sf -o /dev/null "http://127.0.0.1:$AWX_PORT/api/v2/ping/" && return 0
    sleep 5
  done
  echo "AWX web did not come up"; return 1
}

check_decrypt() {
  web awx-manage shell -c "
from awx.main.models import Credential
from awx.main.utils.encryption import decrypt_field
c = Credential.objects.get(name='e2e-machine')
assert decrypt_field(c, 'password') == 'e2e-cred-secret', 'credential decryption failed'
print('PASS credential decrypts to the original secret')"
}

build() {
  docker build --network host -q -f "$INSTALLER/Dockerfile.awx" --build-arg "BASE_IMAGE=$1" -t "$2" "$INSTALLER" >/dev/null
  echo "built $2 from $1"
}

wait_exec() {
  for _ in $(seq 60); do web awx-manage check >/dev/null 2>&1 && return 0; sleep 5; done
  echo "awx-manage not usable in awx_web"; return 1
}

# Steps from bootstrap_awx.py after the containers are up (it migrates before the API answers)
bootstrap() {
  wait_exec
  web awx-manage migrate --noinput | tail -1
  wait_web
  web awx-manage shell -c "
from django.contrib.auth import get_user_model
User = get_user_model(); u, _ = User.objects.get_or_create(username='admin')
u.is_superuser = True; u.is_staff = True; u.email = 'admin@example.com'; u.set_password('e2e-admin-pass'); u.save()"
  web awx-manage create_preload_data
  web awx-manage register_default_execution_environments
}

ensure_queues() {
  for _ in $(seq 60); do
    docker exec awx_e2e_task awx-manage register_queue --queuename=controlplane --hostnames=awx_task >/dev/null 2>&1 \
      && docker exec awx_e2e_task awx-manage register_queue --queuename=default --hostnames=awx_task >/dev/null 2>&1 && return 0
    sleep 5
  done
  echo "could not register queues"; return 1
}

# The production switch, run against this stack: compose override in $HERE, status in $STATE/swap.
swap() {
  local dir=$STATE/swap rc
  mkdir -p "$dir"
  printf 'services:\n  awx_web:\n    image: awx-e2e-podman:new\n  awx_task:\n    image: awx-e2e-podman:new\n  receptor:\n    image: awx-e2e-podman:new\n' \
    > "$dir/override.new.yml"
  {
    echo "STATE_DIR=$dir"
    echo "COMPOSE_DIR=$HERE"
    echo "NEW_IMAGE=awx-e2e-podman:new"
    echo "OLD_IMAGE=awx-e2e-podman:old"
    echo "SNAP=e2e-swap"
    echo "FROM_VERSION=$(curl -sf "http://127.0.0.1:$AWX_PORT/api/v2/ping/" | python3 -c 'import json, sys; print(json.load(sys.stdin)["version"])')"
    echo "TO_VERSION=$(docker run --rm --entrypoint /var/lib/awx/venv/awx/bin/python3 awx-e2e-podman:new -c 'import awx; print(awx.__version__)')"
    echo "AWX_PORT=$AWX_PORT"
    echo "PROJECT_ID=$1"
    echo "WAIT_IDLE_MIN=5"
    echo "WEB=awx_e2e_web TASK=awx_e2e_task RECEPTOR=awx_e2e_receptor PG=awx_e2e_postgres"
  } > "$dir/pending.env"
  rc=0; bash "$SWAP_SCRIPT" "$dir/pending.env" || rc=$?
  rm -f "$HERE/docker-compose.override.yml"
  echo "swap: rc=$rc $(cat "$dir/status.json")"
  grep -q '"state": "done"' "$dir/status.json"
}

collect_logs() {
  mkdir -p "$STATE/logs"
  for c in awx_e2e_web awx_e2e_task awx_e2e_receptor awx_e2e_rsyslog; do docker logs "$c" > "$STATE/logs/$1-$c.log" 2>&1 || true; done
}

trap '[ "$KEEP" = --keep ] || compose down -v >/dev/null 2>&1; echo "state and logs: $STATE"' EXIT
export COMPOSE_PROGRESS=quiet
# rsyslog sidecar and log receiver for the external logging check
export COMPOSE_PROFILES=logging

docker build --network host -q -f "$HERE/ui.Dockerfile" -t "$PLAYWRIGHT_IMAGE" "$HERE" >/dev/null
build "$OLD" awx-e2e-podman:old
build "$NEW" awx-e2e-podman:new
compose down -v >/dev/null 2>&1 || true

echo "### phase 1: $OLD"
export AWX_IMAGE=awx-e2e-podman:old
compose up -d postgres redis receptor awx_web
bootstrap || { collect_logs old; exit 1; }
compose up -d
ensure_queues
rc=0
e2e seed || rc=1
check_decrypt || rc=1
ui || rc=1
e2e logging || rc=1
collect_logs old

echo "### phase 2: $NEW"
if [ -n "${SWAP_SCRIPT:-}" ]; then
  swap "$(python3 -c 'import json, sys; print(json.load(open(sys.argv[1]))["project"])' "$STATE/state.json")" \
    || { collect_logs new; exit 1; }
  export AWX_IMAGE=awx-e2e-podman:new
else
  export AWX_IMAGE=awx-e2e-podman:new
  compose up -d
  wait_exec && web awx-manage migrate --noinput | tail -1
fi
wait_web || { collect_logs new; exit 1; }
echo "unapplied migrations: $(web awx-manage showmigrations --plan | grep -c '\[ \]' || true)"
ensure_queues
e2e verify || rc=1
check_decrypt || rc=1
ui || rc=1
e2e logging || rc=1
collect_logs new
exit $rc
