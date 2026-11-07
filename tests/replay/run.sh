#!/usr/bin/env bash
# Roda todos os cenários de replay (ou os passados como argumento) com o
# quiz-loop de verdade em modo --replay e confere o resultado esperado de
# cada um. Nenhuma tela real, clique ou chamada ao Claude acontece.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../.." && pwd)"
FIXTURES="${FIXTURES:-$REPO/tests/fixtures/out}"
export QV_CACHE_DIR="${QV_CACHE_DIR:-$FIXTURES/.cache}"

if [[ ! -f "$FIXTURES/single.png" || "$REPO/tests/fixtures/make_fixtures.py" -nt "$FIXTURES/single.png" ]]; then
    python3 "$REPO/tests/fixtures/make_fixtures.py" "$FIXTURES" > /dev/null || exit 1
fi

if (( $# )); then
    scenarios=("$@")
else
    mapfile -t scenarios < <(find "$HERE" -mindepth 2 -maxdepth 2 -name scenario.json -printf '%h\n' | sort)
fi

pass=0
fail=0
for dir in "${scenarios[@]}"; do
    [[ "$dir" == /* ]] || dir="$HERE/$dir"
    name="$(basename "$dir")"
    run_dir="$(mktemp -d "${TMPDIR:-/tmp}/quiz-replay-run.XXXXXX")"
    args=(--replay "$dir" --fixtures "$FIXTURES" --run-dir "$run_dir")
    [[ "$(jq -r '.dry_run // false' "$dir/scenario.json")" == true ]] && args+=(--dry-run)
    start=$SECONDS
    if out="$("$REPO/bin/quiz-loop" "${args[@]}" 2>&1)"; then
        printf 'OK     %-26s (%ss)\n' "$name" "$(( SECONDS - start ))"
        pass=$(( pass + 1 ))
        rm -rf "$run_dir"
    else
        printf 'FALHA  %-26s (%ss) log: %s\n' "$name" "$(( SECONDS - start ))" "$run_dir/run.log"
        printf '%s\n' "$out" | sed 's/^/       /'
        fail=$(( fail + 1 ))
    fi
done
printf '\nreplay: %d ok, %d falha(s)\n' "$pass" "$fail"
(( fail == 0 ))
