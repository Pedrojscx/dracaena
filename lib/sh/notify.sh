# shellcheck shell=bash
# Notificações compatíveis com qualquer daemon freedesktop (mako, dunst,
# swaync...). Usa só o básico da especificação: resumo, corpo, urgência,
# tempo de expiração e substituição por id (`notify-send -p/-r`). Se o
# libnotify não tiver `-p`, cai para `gdbus` chamando Notify diretamente
# com replaces_id. A notificação de status é sempre substituída, nunca
# empilhada.

QH_NOTIFY_ID_FILE="$QH_RUNTIME_DIR/notify.id"
QH_APP_NAME="quiz-helper"
QH_NOTIFY_ENABLED="${QH_NOTIFY_ENABLED:-1}"

qh_notify_has_print_id() {
    if [[ -z "${_QH_NOTIFY_P:-}" ]]; then
        if notify-send --help 2>&1 | grep -q -- '--print-id'; then
            _QH_NOTIFY_P=1
        else
            _QH_NOTIFY_P=0
        fi
    fi
    [[ "$_QH_NOTIFY_P" == 1 ]]
}

# Nome do daemon em execução (GetServerInformation), ou vazio.
qh_notify_server() {
    gdbus call --session --dest org.freedesktop.Notifications \
        --object-path /org/freedesktop/Notifications \
        --method org.freedesktop.Notifications.GetServerInformation 2> /dev/null |
        sed -n "s/^('\([^']*\)', '[^']*', '\([^']*\)'.*/\1 \2/p"
}

_qh_notify_gdbus() {
    # $1 replaces_id $2 resumo $3 corpo $4 urgência(0-2) $5 expiração(ms)
    local out
    out="$(gdbus call --session --dest org.freedesktop.Notifications \
        --object-path /org/freedesktop/Notifications \
        --method org.freedesktop.Notifications.Notify \
        "$QH_APP_NAME" "uint32 $1" "" "$2" "$3" "[]" "{'urgency': <byte $4>}" "int32 $5" 2> /dev/null)" || return 1
    out="${out#(uint32 }"
    printf '%s\n' "${out%%,*}"
}

# Modo "não perturbe" ativo no daemon? (swaync, mako ou dunst; outros: não)
qh_notify_dnd_active() {
    if command -v swaync-client > /dev/null 2>&1; then
        [[ "$(swaync-client --get-dnd 2> /dev/null)" == true ]] && return 0
    fi
    if command -v makoctl > /dev/null 2>&1; then
        makoctl mode 2> /dev/null | grep -qx 'do-not-disturb' && return 0
    fi
    if command -v dunstctl > /dev/null 2>&1; then
        [[ "$(dunstctl is-paused 2> /dev/null)" == true ]] && return 0
    fi
    return 1
}

# Urgência efetiva: com "não perturbe" ativo e NOTIFY_OVER_DND=1, sobe para
# crítica (que os daemons mostram mesmo nesse modo); senão, a pedida.
qh_notify_urgency() {
    if [[ "$1" != critical && "${CFG_NOTIFY_OVER_DND:-1}" == 1 ]] && qh_notify_dnd_active; then
        printf 'critical\n'
    else
        printf '%s\n' "$1"
    fi
}

# qh_notify <resumo> <corpo> [low|normal|critical] [expiração_ms] [substituir=1]
# Com substituir=1 reaproveita o id salvo (notificação de status única).
qh_notify() {
    local summary="$1" body="${2:-}" urgency="${3:-normal}" expire="${4:-0}" replace="${5:-1}"
    if [[ "$QH_NOTIFY_ENABLED" != 1 ]]; then
        [[ "${QH_VERBOSE:-0}" == 1 ]] && printf '[notificação] %s\n' "${body//$'\n'/ | }" >&2
        return 0
    fi
    mkdir -p "$QH_RUNTIME_DIR"
    urgency="$(qh_notify_urgency "$urgency")"
    local old="" id=""
    [[ "$replace" == 1 && -r "$QH_NOTIFY_ID_FILE" ]] && old="$(< "$QH_NOTIFY_ID_FILE")"
    [[ "$old" =~ ^[0-9]+$ ]] || old=""
    if qh_notify_has_print_id; then
        local args=(-a "$QH_APP_NAME" -u "$urgency" -t "$expire" -p)
        [[ -n "$old" ]] && args+=(-r "$old")
        id="$(notify-send "${args[@]}" -- "$summary" "$body" 2> /dev/null)" || id=""
    fi
    if [[ -z "$id" ]]; then
        local u=1
        [[ "$urgency" == low ]] && u=0
        [[ "$urgency" == critical ]] && u=2
        id="$(_qh_notify_gdbus "${old:-0}" "$summary" "$body" "$u" "$expire")" || id=""
    fi
    [[ "$replace" == 1 && "$id" =~ ^[0-9]+$ ]] && printf '%s\n' "$id" > "$QH_NOTIFY_ID_FILE"
    return 0
}
