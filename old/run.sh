#! /usr/bin/env bash
set -euxo nounset -o pipefail
(( UID ))
(( ! $# ))
[[ -n ${VIRTUAL_ENV:-} ]] ||
. ~/venv/bin/activate
python app.py
#python app-1.py
#python app-0.py
