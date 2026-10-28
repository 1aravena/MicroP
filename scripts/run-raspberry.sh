#!/bin/sh
set -eu
task_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$task_dir"
if [ ! -x .venv/bin/python ]; then
  printf '%s\n' 'Falta el entorno Raspberry. Consulta docs/integracion-final.md.' >&2
  exit 1
fi
exec .venv/bin/python -m backend --config backend/config.raspberry.json "$@"
