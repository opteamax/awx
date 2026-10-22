#!/bin/bash
# Usage: compile.sh [pip-compile args, e.g. --upgrade-package foo==1.2]
# Recompiles requirements/requirements.txt like requirements/updater.sh does, but with
# Python 3.11 and without --upgrade, so unrelated pins stay unchanged.
# If /dab is mounted, django-ansible-base is resolved from that checkout.
# Result: /out/requirements.txt
set -euo pipefail
rm -rf /r && cp -r /src/requirements /r && cd /r
if [ -d /dab/.git ]; then
  sed -i -E "s|^(django-ansible-base[^@]*) @ .*|\1 @ git+file://localhost/dab@$(git -C /dab rev-parse HEAD)|" requirements_git.txt
fi
python3.11 -m venv /tmp/pt && /tmp/pt/bin/pip install -q 'pip<24.1' 'pip-tools==7.4.1'
/tmp/pt/bin/pip-compile --no-header --quiet -r --allow-unsafe --no-strip-extras "$@" \
  --output-file requirements.txt requirements.in requirements_git.txt
# drop entries that come from requirements_git.txt, as updater.sh does
mkdir -p /out
grep -vE '^(certifi|ansible-runner|python3-saml|django-ansible-base)(\[| @|==)' requirements.txt \
  | grep -vE '^\s+# via -r requirements_git.txt$' > /out/requirements.txt
