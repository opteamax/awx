# Sourced by the container scripts.
# Syncs the AWX source from /src to /work and provides a venv matching its requirements.
#
# Environment:
#   GIT_REQS   requirements_git.txt to use (default: /src/requirements/requirements_git.txt)
#   /dab       if mounted, django-ansible-base is installed from this checkout (HEAD)
set -euo pipefail

mkdir -p /var/log/tower /var/lib/awx/projects /var/lib/awx/job_status /var/lib/awx/public/static
rsync -a --delete --exclude awx/ui/node_modules --exclude .git /src/ /work/
cd /work
[ -f VERSION ] || echo "${AWX_VERSION:-24.6.1}" > VERSION

GIT_REQS=${GIT_REQS:-/src/requirements/requirements_git.txt}
cp "$GIT_REQS" /tmp/req_git.txt
if [ -d /dab/.git ]; then
  DAB_REV=$(git -C /dab rev-parse HEAD)
  sed -i -E "s|^(django-ansible-base[^@]*) @ .*|\1 @ git+file://localhost/dab@${DAB_REV}|" /tmp/req_git.txt
fi
grep -vE '^(pip|setuptools|setuptools-scm|setuptools_scm|wheel)[=<> ]' requirements/requirements.txt > /tmp/req.txt
grep -vE '^(pip|jupyter|ipython|tox|debugpy|sdb|remote-pdb)[=<> ]?' requirements/requirements_dev.txt > /tmp/req_dev.txt

VENV=/venvs/$(cat /tmp/req.txt /tmp/req_dev.txt /tmp/req_git.txt | sha256sum | cut -c1-16)
if [ ! -e "$VENV/.done" ]; then
  echo "Creating venv $VENV" >&2
  rm -rf "$VENV"
  python3.11 -m venv "$VENV"
  "$VENV/bin/pip" install -q -U 'pip<24.1' 'setuptools<70' wheel
  "$VENV/bin/pip" install -q -r /tmp/req.txt
  "$VENV/bin/pip" install -q -r /tmp/req_dev.txt colorama
  "$VENV/bin/pip" install -q -r /tmp/req_git.txt
  touch "$VENV/.done"
fi
export PATH="$VENV/bin:$PATH" PYTHONPATH=/work
echo "venv: $VENV, Django $(python -c 'import django; print(django.get_version())')" >&2
