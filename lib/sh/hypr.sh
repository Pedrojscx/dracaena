# shellcheck shell=bash
# Hyprland: janela ativa, monitores, cursor e dispatchers.
#
# Com a config em Lua (hyprland.lua), `hyprctl dispatch <args>` é avaliado
# como código Lua (`hl.dispatch(<args>)`), então a sintaxe antiga
# (`dispatch movecursor X Y`) falha com erro de sintaxe. Os dispatchers
# abaixo tentam a forma Lua e caem para a antiga quando ela não é aceita
# (config clássica hyprland.conf). A forma que funcionou fica memorizada.

# Primeira linha do último erro de dispatch (lida por input.sh e quiz-doctor).
# shellcheck disable=SC2034
QH_HYPR_ERROR=""

qh_hypr_active() { hyprctl -j activewindow 2> /dev/null; }
qh_hypr_monitors() { hyprctl -j monitors 2> /dev/null; }
qh_hypr_clients() { hyprctl -j clients 2> /dev/null; }

# Sessão bloqueada (tela de bloqueio na frente)? Via logind (LockedHint).
qh_session_locked() {
    [[ "$(loginctl show-session "${XDG_SESSION_ID:-auto}" -p LockedHint --value 2> /dev/null)" == yes ]]
}

# Imprime "X Y" (coordenadas globais lógicas) do cursor.
qh_cursor_pos() {
    local raw
    raw="$(hyprctl cursorpos 2> /dev/null)" || return 1
    raw="${raw//,/ }"
    # shellcheck disable=SC2086
    set -- $raw
    [[ "${1:-}" =~ ^-?[0-9]+$ && "${2:-}" =~ ^-?[0-9]+$ ]] || return 1
    printf '%s %s\n' "$1" "$2"
}

# qh_hypr_dispatch <expressão Lua> <dispatcher antigo> [args antigos...]
# Sucesso só com código 0 e saída "ok". Em falha, QH_HYPR_ERROR guarda a
# primeira linha do erro.
qh_hypr_dispatch() {
    local lua="$1" out rc
    shift
    if [[ "${_QH_HYPR_STYLE:-lua}" == lua ]]; then
        out="$(hyprctl dispatch "$lua" 2>&1)"
        rc=$?
        if (( rc == 0 )) && [[ "$out" == ok* ]]; then
            _QH_HYPR_STYLE=lua
            return 0
        fi
        QH_HYPR_ERROR="${out%%$'\n'*}"
    fi
    out="$(hyprctl dispatch "$@" 2>&1)"
    rc=$?
    if (( rc == 0 )) && [[ "$out" == ok* ]]; then
        _QH_HYPR_STYLE=legacy
        return 0
    fi
    # shellcheck disable=SC2034
    [[ "${_QH_HYPR_STYLE:-lua}" == legacy ]] && QH_HYPR_ERROR="${out%%$'\n'*}"
    _QH_HYPR_STYLE=""
    return 1
}

# Move o cursor para coordenadas globais lógicas exatas.
qh_cursor_move() {
    qh_hypr_dispatch "hl.dsp.cursor.move({ x = $1, y = $2 })" movecursor "$1" "$2"
}

# Executa um comando como um atalho faria (ambiente do Hyprland, não do shell).
qh_hypr_exec() {
    local cmd="$1" lua_cmd
    lua_cmd="${cmd//\\/\\\\}"
    lua_cmd="${lua_cmd//\"/\\\"}"
    qh_hypr_dispatch "hl.dsp.exec_cmd(\"$lua_cmd\")" exec "$cmd"
}

# Foca uma janela pelo endereço (0x...).
qh_hypr_focus() {
    qh_hypr_dispatch "hl.dsp.focus({ window = \"address:$1\" })" focuswindow "address:$1"
}
