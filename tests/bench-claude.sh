#!/usr/bin/env bash
# Mede o tempo de `claude -p --model <MODEL>` com uma imagem de teste,
# usando exatamente a mesma chamada do quiz-loop. Consome cota da assinatura.
#
#   tests/bench-claude.sh [repetições=3] [fixture=single]
set -uo pipefail

QH_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=../lib/sh/common.sh
source "$QH_REPO/lib/sh/common.sh"
# shellcheck source=../lib/sh/claude.sh
source "$QH_REPO/lib/sh/claude.sh"

runs="${1:-3}"
name="${2:-single}"
qh_load_config
fixtures="$QH_REPO/tests/fixtures/out"
[[ -f "$fixtures/$name.png" ]] || python3 "$QH_REPO/tests/fixtures/make_fixtures.py" "$fixtures" > /dev/null
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp "$fixtures/$name.png" "$work/questao.png"

printf 'modelo: %s | claude: %s | imagem: %s.png\n' "${CFG_MODEL}" "$(qh_claude_bin)" "$name"
total=0
okcount=0
for (( i = 1; i <= runs; i++ )); do
    out="$work/out-$i.txt"
    t0="$(qh_now_ms)"
    qh_claude_start answer "$work/questao.png" "$out"
    qh_claude_wait ""
    rc=$?
    ms=$(( $(qh_now_ms) - t0 ))
    total=$(( total + ms ))
    if (( rc == 0 )) && answer="$(qv validate "$out" 2> /dev/null)"; then
        okcount=$(( okcount + 1 ))
        printf '  %d: %5.1fs  JSON ok  %s\n' "$i" "$(awk -v m="$ms" 'BEGIN{print m/1000}')" "$answer"
    else
        printf '  %d: %5.1fs  FALHA (rc=%s) %s\n' "$i" "$(awk -v m="$ms" 'BEGIN{print m/1000}')" "$rc" \
            "$(head -c 200 "$out" "$out.err" 2> /dev/null | tr '\n' ' ')"
    fi
done
printf 'média: %.1fs em %d chamadas (%d com JSON válido)\n' "$(awk -v t="$total" -v n="$runs" 'BEGIN{print t/n/1000}')" "$runs" "$okcount"
