#!/usr/bin/env bash
# Sonda de ambiente do quiz-helper, usada pelo quiz-doctor.
#
#   env-probe.sh <arquivo de saída> [--claude]
#
# Roda, com as mesmas bibliotecas do quiz-loop, um movimento de cursor para
# a posição atual (sem efeito visível), `ydotool click 0x00` (nenhum botão),
# a roda com deslocamento 0 e, com --claude, um `claude -p` mínimo. Grava
# KEY=código e KEY_ERR=primeira linha do erro. O quiz-doctor executa a sonda
# no terminal e via `hyprctl dispatch exec` (o ambiente de um atalho) para
# achar diferenças entre os dois.
set -uo pipefail

QH_REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
# shellcheck source=common.sh
source "$QH_REPO/lib/sh/common.sh"
# shellcheck source=hypr.sh
source "$QH_REPO/lib/sh/hypr.sh"
# shellcheck source=input.sh
source "$QH_REPO/lib/sh/input.sh"
# shellcheck source=claude.sh
source "$QH_REPO/lib/sh/claude.sh"

out="${1:?arquivo de saída}"
want_claude="${2:-}"
tmp="$out.tmp"
: > "$tmp"
emit() { printf '%s=%s\n' "$1" "$2" >> "$tmp"; }

qh_read_kv "$QH_DEFAULT_CONFIG"
qh_read_kv "$QH_PATHS_FILE"
qh_read_kv "$QH_USER_CONFIG"
emit PATH_HAS_LOCAL_BIN "$([[ ":$PATH:" == *":$HOME/.local/bin:"* ]] && echo 1 || echo 0)"
emit YDOTOOL_SOCKET_ENV "${YDOTOOL_SOCKET:-<ausente>}"
emit YDOTOOL_SOCKET_FOUND "$(qh_ydotool_socket || echo '<nenhum>')"
emit CLAUDE_CODE_TMPDIR_ENV "${CLAUDE_CODE_TMPDIR:-<ausente>}"

if pos="$(qh_cursor_pos)"; then
    read -r x y <<< "$pos"
    if qh_cursor_move "$x" "$y"; then emit CURSOR 0; else emit CURSOR 1; emit CURSOR_ERR "$QH_HYPR_ERROR"; fi
else
    emit CURSOR 1
    emit CURSOR_ERR "hyprctl cursorpos falhou"
fi

QH_INPUT_ERROR=""
if _qh_ydo click 0x00; then emit YDOTOOL_CLICK 0; else emit YDOTOOL_CLICK 1; emit YDOTOOL_CLICK_ERR "$QH_INPUT_ERROR"; fi
QH_INPUT_ERROR=""
if _qh_ydo mousemove --wheel -x 0 -y 0; then emit YDOTOOL_WHEEL 0; else emit YDOTOOL_WHEEL 1; emit YDOTOOL_WHEEL_ERR "$QH_INPUT_ERROR"; fi

if [[ "$want_claude" == --claude ]]; then
    if bin="$(qh_claude_bin)"; then
        qh_claude_env
        work="$(mktemp -d)"
        ans="$(cd "$work" && timeout 90 "$bin" -p --model "${CFG_MODEL:-haiku}" --tools "" --strict-mcp-config \
            --disable-slash-commands --no-session-persistence --output-format text \
            "Responda apenas com a palavra ok." 2> "$work/err" < /dev/null)"
        rc=$?
        if (( rc == 0 )) && [[ "${ans,,}" == *ok* ]]; then
            emit CLAUDE 0
        else
            emit CLAUDE "${rc/#0/1}"
            emit CLAUDE_ERR "$(head -n1 "$work/err" 2> /dev/null || true)${ans:+ (resposta: ${ans:0:80})}"
        fi
        rm -rf "$work"
    else
        emit CLAUDE 127
        emit CLAUDE_ERR "claude não encontrado"
    fi
fi
mv -f "$tmp" "$out"
