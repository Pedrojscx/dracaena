# shellcheck shell=bash
# Entrada: cursor via dispatcher do Hyprland (coordenadas globais exatas,
# sem aceleração) e botões/roda via ydotool. Cada comando executado vai para
# QH_INPUT_LOG (comando exato, código de saída e stderr completo); em falha,
# QH_INPUT_ERROR guarda a primeira linha do erro real para a notificação.
# Guarda onde o script deixou o cursor para a parada de emergência.

QH_LAST_X=""
QH_LAST_Y=""
QH_INPUT_ERROR=""
QH_INPUT_LOG="${QH_INPUT_LOG:-}"

# Socket do ydotoold: YDOTOOL_SOCKET do ambiente, senão o primeiro socket
# existente entre os caminhos padrão do daemon. Os atalhos do Hyprland não
# herdam o ambiente do shell, então isto roda antes de toda chamada.
qh_ydotool_socket() {
    local s
    for s in "${YDOTOOL_SOCKET:-}" "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket" /tmp/.ydotool_socket; do
        if [[ -n "$s" && -S "$s" ]]; then
            printf '%s\n' "$s"
            return 0
        fi
    done
    return 1
}

_qh_input_log() {
    [[ -n "$QH_INPUT_LOG" ]] || return 0
    printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$QH_INPUT_LOG"
}

# Roda um comando de entrada registrando tudo; falha -> QH_INPUT_ERROR.
_qh_run() {
    local err rc
    err="$("$@" 2>&1 > /dev/null)"
    rc=$?
    if (( rc == 0 )); then
        _qh_input_log "entrada: $* -> rc=0"
        return 0
    fi
    _qh_input_log "entrada: $* -> rc=$rc stderr: ${err:-<vazio>}"
    QH_INPUT_ERROR="${err%%$'\n'*}"
    [[ -n "$QH_INPUT_ERROR" ]] || QH_INPUT_ERROR="$1 saiu com código $rc"
    return "$rc"
}

_qh_ydo() {
    local sock
    if sock="$(qh_ydotool_socket)"; then
        export YDOTOOL_SOCKET="$sock"
    else
        QH_INPUT_ERROR="socket do ydotoold não encontrado (${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/.ydotool_socket)"
        _qh_input_log "entrada: ydotool $* -> $QH_INPUT_ERROR"
        return 1
    fi
    _qh_run ydotool "$@"
}

# Lembra a posição atual do cursor como referência (início ou retomada).
qh_input_anchor() {
    local pos
    pos="$(qh_cursor_pos)" || return 1
    read -r QH_LAST_X QH_LAST_Y <<< "$pos"
}

# Retorna 0 se o usuário mexeu o mouse (mais de MOUSE_ABORT_PX da referência).
qh_mouse_moved() {
    [[ -n "$QH_LAST_X" ]] || return 1
    local pos x y limit="${CFG_MOUSE_ABORT_PX:-30}"
    pos="$(qh_cursor_pos)" || return 1
    read -r x y <<< "$pos"
    (( (x - QH_LAST_X) * (x - QH_LAST_X) + (y - QH_LAST_Y) * (y - QH_LAST_Y) > limit * limit ))
}

_qh_move() {
    if ! qh_cursor_move "$1" "$2"; then
        QH_INPUT_ERROR="mover o cursor falhou: ${QH_HYPR_ERROR:-hyprctl dispatch}"
        _qh_input_log "entrada: mover cursor para $1,$2 -> $QH_INPUT_ERROR"
        return 1
    fi
    _qh_input_log "entrada: mover cursor para $1,$2 -> ok"
    QH_LAST_X="$1"
    QH_LAST_Y="$2"
}

qh_click() {
    QH_INPUT_ERROR=""
    _qh_move "$1" "$2" || return 1
    qh_ms_sleep 40
    _qh_ydo click 0xC0
}

# qh_drag x y x2 y2 passos pausa_ms
qh_drag() {
    local x="$1" y="$2" x2="$3" y2="$4" steps="${5:-12}" pause="${6:-15}" i nx ny
    QH_INPUT_ERROR=""
    _qh_move "$x" "$y" || return 1
    qh_ms_sleep 60
    _qh_ydo click 0x40 || return 1
    qh_ms_sleep 80
    for (( i = 1; i <= steps; i++ )); do
        nx=$(( x + (x2 - x) * i / steps ))
        ny=$(( y + (y2 - y) * i / steps ))
        _qh_move "$nx" "$ny" || { _qh_ydo click 0x80; return 1; }
        qh_ms_sleep "$pause"
    done
    qh_ms_sleep 80
    _qh_ydo click 0x80
}

# qh_scroll x y quantidade (negativo = para baixo no ydotool 1.x:
# `ydotool mousemove --wheel -x 0 -y <n>`)
qh_scroll() {
    QH_INPUT_ERROR=""
    _qh_move "$1" "$2" || return 1
    qh_ms_sleep 40
    _qh_ydo mousemove --wheel -x 0 -y "$3"
}
