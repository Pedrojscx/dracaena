#!/usr/bin/env bash
# Suíte DOM offline.
set -uo pipefail
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if (( $# )); then
    echo 'Uso: tests/run.sh' >&2
    exit 2
fi
cd "$REPO" || exit 1
PYTHON="${QH_PYTHON:-${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper/venv/bin/python}"
[[ -x "$PYTHON" ]] || PYTHON="$(command -v python3)"
# Isola qualquer leitura de configuração/perfil pessoal, preservando só o cache
# do executável Chromium de testes (não é o perfil do navegador do usuário).
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-${XDG_CACHE_HOME:-$HOME/.cache}/ms-playwright}"
TEST_HOME="$(mktemp -d "${TMPDIR:-/tmp}/quiz-tests.XXXXXX")"
export HOME="$TEST_HOME" XDG_CONFIG_HOME="$TEST_HOME/config" XDG_DATA_HOME="$TEST_HOME/data"
export XDG_RUNTIME_DIR="$TEST_HOME/runtime" QH_RUNTIME_DIR="$TEST_HOME/runtime/quiz-helper"
export QH_NOTIFY_ENABLED=0 QH_REAL_FIXTURES="$TEST_HOME/no-real-fixtures"
export PYTHONPATH="$REPO/lib:$REPO/tests/py"
mkdir -p "$XDG_RUNTIME_DIR"
status=0
scripts=(bin/* lib/sh/*.sh install.sh uninstall.sh tests/*.sh)
for script in "${scripts[@]}"; do
    bash -n "$script" || status=1
done
if command -v shellcheck >/dev/null 2>&1; then
    shellcheck -x -P SCRIPTDIR "${scripts[@]}" || status=1
else
    echo 'ShellCheck indisponível; instale-o para completar a verificação.' >&2
    status=1
fi
"$PYTHON" -m compileall -q lib tests || status=1
"$PYTHON" -m unittest discover -s tests/py -v || status=1
python3 tests/check_publication.py || status=1
echo "Dados sintéticos temporários dos testes: $TEST_HOME"
exit "$status"
