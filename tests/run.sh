#!/usr/bin/env bash
# Roda toda a bateria de testes, sem cliques reais e sem chamar o Claude:
#   1. shellcheck em todos os scripts bash
#   2. testes unitários do Python (unittest), inclusive localização sobre as
#      telas sintéticas geradas com ImageMagick
#   3. wrapper de entrada com ydotool/hyprctl simulados
#   4. cenários de replay do quiz-loop completo (captura da janela inteira)
#
#   tests/run.sh [--no-shellcheck] [--only unit|input|replay|shellcheck]
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export FIXTURES="$REPO/tests/fixtures/out"
export QV_CACHE_DIR="$FIXTURES/.cache"
ONLY=""
SKIP_SC=0
while (( $# )); do
    case "$1" in
        --no-shellcheck) SKIP_SC=1 ;;
        --only) ONLY="${2:?}"; shift ;;
        *) sed -n '2,8p' "$0"; exit 2 ;;
    esac
    shift
done

status=0
step() { printf '\n== %s\n' "$*"; }

python3 "$REPO/tests/fixtures/make_fixtures.py" "$FIXTURES" > /dev/null || exit 1

if [[ -z "$ONLY" || "$ONLY" == shellcheck ]] && (( ! SKIP_SC )); then
    step "shellcheck"
    if command -v shellcheck > /dev/null 2>&1; then
        mapfile -t scripts < <(cd "$REPO" && { ls bin/* tests/input/mocks/*; ls lib/sh/*.sh tests/*.sh tests/replay/*.sh tests/input/*.sh install.sh uninstall.sh; } 2> /dev/null)
        if (cd "$REPO" && shellcheck -x -P SCRIPTDIR "${scripts[@]}"); then
            echo "shellcheck: ${#scripts[@]} scripts ok"
        else
            status=1
        fi
    else
        echo "shellcheck não instalado: sudo pacman -S --needed shellcheck"
        status=1
    fi
fi

if [[ -z "$ONLY" || "$ONLY" == unit ]]; then
    step "unittest"
    (cd "$REPO/tests/unit" && python3 -m unittest -q) || status=1
fi

if [[ -z "$ONLY" || "$ONLY" == input ]]; then
    step "entrada (ydotool e hyprctl simulados)"
    "$REPO/tests/input/run.sh" || status=1
fi

if [[ -z "$ONLY" || "$ONLY" == replay ]]; then
    step "replay"
    "$REPO/tests/replay/run.sh" || status=1
fi

printf '\n'
if (( status )); then echo "RESULTADO: FALHOU"; else echo "RESULTADO: tudo passou"; fi
exit "$status"
