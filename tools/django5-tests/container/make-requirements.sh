#!/bin/bash
# Runs the Makefile's requirements_awx target in a fresh venv, as the image build does
# (bootstrap pins from VENV_BOOTSTRAP, source-only packages, git requirements).
set -euo pipefail
rsync -a --delete --exclude awx/ui/node_modules --exclude .git /src/ /work/
cd /work
make requirements_awx VENV_BASE=/tmp/venvs PYTHON=python3.11 SHELL=/bin/bash
# rsa is removed on purpose (requirements_tower_uninstall.txt), so pip check reports its dependents
/tmp/venvs/awx/bin/pip check || true
/tmp/venvs/awx/bin/pip --version
/tmp/venvs/awx/bin/python -c 'import django, cryptography, setuptools; print("django", django.get_version(), "cryptography", cryptography.__version__, "setuptools", setuptools.__version__)'
