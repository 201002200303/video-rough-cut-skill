#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

SKIP_PYTHON_DEPS=0
for arg in "$@"; do
  case "$arg" in
    --skip-python-deps)
      SKIP_PYTHON_DEPS=1
      ;;
    *)
      echo "Unknown argument: $arg" >&2
      exit 2
      ;;
  esac
done

echo "== Video Rough Cut Skill Linux setup =="
echo "Project: ${PROJECT_ROOT}"

PYTHON_BIN=""
for candidate in python3.12 python3.11 python3.10 python3; do
  if command -v "${candidate}" >/dev/null 2>&1; then
    PYTHON_BIN="${candidate}"
    break
  fi
done

if [[ -z "${PYTHON_BIN}" ]]; then
  echo "Python 3.10-3.12 was not found. Install Python, then rerun this script." >&2
  exit 1
fi

if [[ ! -d ".venv" ]]; then
  echo "Creating virtual environment: .venv"
  "${PYTHON_BIN}" -m venv .venv
fi

VENV_PYTHON="${PROJECT_ROOT}/.venv/bin/python"
if [[ ! -x "${VENV_PYTHON}" ]]; then
  echo "Virtual environment Python not found: ${VENV_PYTHON}" >&2
  exit 1
fi

"${VENV_PYTHON}" -m pip install --upgrade pip

SETUP_ARGS=("scripts/setup_environment.py" "--install-system-deps" "--yes")
if [[ "${SKIP_PYTHON_DEPS}" -eq 0 ]]; then
  SETUP_ARGS+=("--install-python-deps")
fi

"${VENV_PYTHON}" "${SETUP_ARGS[@]}"

echo
echo "Setup finished."
echo "Activate later with: source .venv/bin/activate"
