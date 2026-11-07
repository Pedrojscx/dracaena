#!/usr/bin/env bash
# Testa lib/sh/input.sh e o dispatcher de cursor de lib/sh/hypr.sh com
# ydotool e hyprctl simulados: sucesso nas duas sintaxes de dispatch (Lua e
# antiga), socket ausente, daemon recusando conexão e sintaxe inválida. O
# erro real (stderr) precisa chegar a QH_INPUT_ERROR e ao log.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export QH_REPO
QH_REPO="$(cd "$HERE/../.." && pwd)"
PASS=0
FAIL=0
ERRORS=()

check() {
    local desc="$1"
    shift
    if "$@"; then PASS=$(( PASS + 1 )); else FAIL=$(( FAIL + 1 )); ERRORS+=("$CASE: $desc"); fi
}

# run_case <nome> <comando bash usando as funções de entrada>
run_case() {
    CASE="$1"
    T="$(mktemp -d "${TMPDIR:-/tmp}/quiz-input-test.XXXXXX")"
    mkdir -p "$T/run"
    export MOCK_DIR="$T" XDG_RUNTIME_DIR="$T/run"
    unset YDOTOOL_SOCKET
    if [[ "${MAKE_SOCKET:-1}" == 1 ]]; then
        python3 -c "import socket,sys; s=socket.socket(socket.AF_UNIX); s.bind(sys.argv[1])" "$T/run/.ydotool_socket"
    fi
    PATH="$HERE/mocks:$PATH" bash -c '
        source "$QH_REPO/lib/sh/common.sh"
        source "$QH_REPO/lib/sh/hypr.sh"
        source "$QH_REPO/lib/sh/input.sh"
        QH_INPUT_LOG="$MOCK_DIR/input.log"
        '"$2"'
        rc=$?
        printf "%s\n" "$QH_INPUT_ERROR" > "$MOCK_DIR/error.txt"
        exit $rc' > "$T/out" 2>&1
    RC=$?
}
err() { cat "$T/error.txt"; }
logged() { grep -qF -- "$1" "$T/input.log"; }
called() { grep -qF -- "$1" "$T/calls.log"; }

run_case "clique com sucesso (hyprland.lua)" 'qh_click 300 400'
check "retorna 0" test "$RC" -eq 0
check "move o cursor com hl.dsp.cursor.move" called 'hyprctl dispatch hl.dsp.cursor.move({ x = 300, y = 400 })'
check "clica com ydotool click 0xC0 no socket descoberto" called "ydotool click 0xC0 [socket=$T/run/.ydotool_socket]"
check "registra comando e código" logged "entrada: ydotool click 0xC0 -> rc=0"
rm -rf "$T"

run_case "clique com sucesso (hyprland.conf)" 'MOCK_HYPR_STYLE=legacy; export MOCK_HYPR_STYLE; qh_click 300 400'
check "retorna 0" test "$RC" -eq 0
check "cai para dispatch movecursor" called "hyprctl dispatch movecursor 300 400"
rm -rf "$T"

run_case "rolagem com a sintaxe do ydotool 1.x" 'qh_scroll 10 20 -3'
check "retorna 0" test "$RC" -eq 0
check "usa mousemove --wheel -x 0 -y -3" called "ydotool mousemove --wheel -x 0 -y -3"
rm -rf "$T"

MAKE_SOCKET=0 run_case "socket ausente" 'qh_click 1 2'
check "falha" test "$RC" -ne 0
check "erro diz que o socket não foi encontrado" bash -c "grep -q 'socket do ydotoold não encontrado' '$T/error.txt'"
check "nem chama o ydotool" bash -c "! grep -q '^ydotool' '$T/calls.log'"
rm -rf "$T"

run_case "daemon recusa a conexão" 'MOCK_YDOTOOL=noconnect; export MOCK_YDOTOOL; qh_click 1 2'
check "falha com o código do ydotool" test "$RC" -eq 2
check "primeira linha do stderr real em QH_INPUT_ERROR" bash -c "grep -q \"^failed to connect socket\" '$T/error.txt'"
check "log tem comando, código e stderr completo" bash -c "grep -q 'ydotool click 0xC0 -> rc=2 stderr: failed to connect socket' '$T/input.log' && grep -q 'Please check if ydotoold is running' '$T/input.log'"
rm -rf "$T"

run_case "sintaxe inválida" 'MOCK_YDOTOOL=syntax; export MOCK_YDOTOOL; qh_scroll 1 2 -3'
check "falha" test "$RC" -eq 1
check "erro real: Unknown command" bash -c "grep -q 'Unknown command: mousemove' '$T/error.txt'"
rm -rf "$T"

run_case "dispatcher de cursor recusado nas duas sintaxes" 'MOCK_HYPR_STYLE=none; export MOCK_HYPR_STYLE; qh_click 1 2'
check "falha antes do ydotool" bash -c "! grep -q '^ydotool' '$T/calls.log'"
check "erro diz que mover o cursor falhou" bash -c "grep -q '^mover o cursor falhou' '$T/error.txt'"
rm -rf "$T"

printf 'entrada (ydotool/hyprctl simulados): %d verificações ok, %d falha(s)\n' "$PASS" "$FAIL"
for e in "${ERRORS[@]}"; do printf '  FALHA: %s\n' "$e"; done
(( FAIL == 0 ))
