#!/bin/bash
# Test harness for the Django 5 port of AWX 24.6.1. See README.md.
#
# Usage: tools/django5-tests/django5-tests.sh [options] <command> [args]
#
# Options:
#   --baseline REF   test git REF (e.g. 24.6.1) instead of the working tree; uses
#                    baseline-requirements_git.txt for the git requirements
#   --dab PATH       install django-ansible-base from this local checkout (HEAD)
#   --out DIR        output directory (default: ~/.cache/awx-django5-tests)
#
# Commands:
#   image                build the test image
#   pytest [ARGS]        run the test suite (default: unit, functional, conf, sso)
#   pgcheck              fresh migrate, makemigrations --check, DAB resource join on PostgreSQL
#   upgrade-check REF    migrate a database with REF first, then with the working tree
#   smoke                uwsgi + daphne smoke test (login, websocket, OAuth2, API)
#   compile [ARGS]       pip-compile requirements.txt into the output dir (args go to pip-compile)
#   services-down        stop the PostgreSQL and Redis containers
#
# All containers use --network host: PostgreSQL listens on 55432, Redis on 56379.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(git -C "$HERE" rev-parse --show-toplevel)
IMAGE=awx-django5-test
PG=awx-django5-test-pg
REDIS=awx-django5-test-redis
OUT=${XDG_CACHE_HOME:-$HOME/.cache}/awx-django5-tests
BASELINE=
DAB=

while [ $# -gt 0 ]; do
  case $1 in
    --baseline) BASELINE=$2; shift 2 ;;
    --dab) DAB=$(cd "$2" && pwd); shift 2 ;;
    --out) OUT=$2; shift 2 ;;
    *) break ;;
  esac
done
CMD=${1:?command required, see header of $0}; shift
mkdir -p "$OUT"

# Checks out REF into a temporary worktree (removed on exit) and stores its path in WT.
cleanup_worktrees=()
worktree() {
  WT=$(mktemp -d "${TMPDIR:-/tmp}/awx-$1-XXXXXX")
  git -C "$REPO" worktree add -q --detach "$WT" "$1"
  cleanup_worktrees+=("$WT")
}
cleanup() {
  for d in "${cleanup_worktrees[@]}"; do git -C "$REPO" worktree remove --force "$d"; done
}
trap cleanup EXIT

# Runs a container script against SRC (the working tree or a baseline worktree).
run_in() {
  local src=$1; shift
  local args=(--rm --network host -v "$src:/src:ro" -v "$HERE:/tools:ro" -v awx-django5-test-venvs:/venvs -v "$OUT:/out")
  [ -n "$DAB" ] && args+=(-v "$DAB:/dab:ro")
  [ "$src" != "$REPO" ] && args+=(-e GIT_REQS=/tools/baseline-requirements_git.txt)
  docker run "${args[@]}" "$IMAGE" "$@"
}

# Sets SRC to the source under test.
source_dir() {
  if [ -n "$BASELINE" ]; then worktree "$BASELINE"; SRC=$WT; else SRC=$REPO; fi
}

services_up() {
  docker inspect "$PG" >/dev/null 2>&1 || docker run -d --rm --name "$PG" --network host \
    -e POSTGRES_USER=awx -e POSTGRES_PASSWORD=awx -e POSTGRES_DB=awx -e PGPORT=55432 postgres:15 >/dev/null
  docker inspect "$REDIS" >/dev/null 2>&1 || docker run -d --rm --name "$REDIS" --network host \
    redis:7 redis-server --port 56379 >/dev/null
  docker exec "$PG" sh -c 'until pg_isready -q -p 55432; do sleep 1; done'
}

fresh_db() {
  docker exec "$PG" psql -q -p 55432 -U awx -c "DROP DATABASE IF EXISTS $1" -c "CREATE DATABASE $1" 2>&1 | grep -v NOTICE || true
  docker exec "$REDIS" redis-cli -p 56379 flushall >/dev/null
}

case $CMD in
  image)
    docker build --network host -t "$IMAGE" "$HERE"
    ;;
  pytest)
    source_dir
    [ $# -eq 0 ] && set -- -q -n 8 --continue-on-collection-errors -rfE --junitxml=/out/pytest.xml \
      awx/main/tests/unit awx/main/tests/functional awx/conf/tests awx/sso/tests
    run_in "$SRC" /tools/container/pytest.sh "$@"
    ;;
  pgcheck)
    source_dir; services_up; fresh_db awx_pgcheck
    run_in "$SRC" /tools/container/manage.sh awx_pgcheck migrate showmigrations makemigrations-check resource-join
    ;;
  upgrade-check)
    from=${1:?REF to upgrade from required}
    services_up; fresh_db awx_upgrade
    worktree "$from"
    echo "### migrate with $from"
    run_in "$WT" /tools/container/manage.sh awx_upgrade migrate showmigrations
    echo "### migrate with working tree"
    run_in "$REPO" /tools/container/manage.sh awx_upgrade migrate showmigrations makemigrations-check resource-join
    ;;
  smoke)
    source_dir; services_up; fresh_db awx_smoke
    run_in "$SRC" /tools/container/smoke.sh awx_smoke
    ;;
  compile)
    run_in "$REPO" /tools/container/compile.sh "$@"
    echo "written: $OUT/requirements.txt"
    ;;
  services-down)
    docker stop "$PG" "$REDIS" 2>/dev/null || true
    ;;
  *)
    echo "unknown command: $CMD" >&2; exit 2 ;;
esac
