#!/bin/bash
# Runs the AWX test suite (SQLite, --nomigrations as configured in pytest.ini).
source /tools/container/common.sh
mkdir -p /out
pip freeze > /out/freeze.txt
exec python -m pytest -p no:cacheprovider "$@"
