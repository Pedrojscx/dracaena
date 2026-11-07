#!/usr/bin/env bash
# Diagnóstico legado OCR (preservado para referência; não usado no modo DOM).
#
# Verifica dependências, ydotoold e acesso ao /dev/uinput, daemon de
# notificação, Hyprland, class do navegador, monitores e escalas, login do
# claude, OCR, o ambiente dos atalhos (ydotool, cursor e claude rodando via
# `hyprctl dispatch exec`, comparados ao terminal) e a detecção automática
# sobre o quiz aberto no Vivaldi (imagem anotada em
# $XDG_DATA_HOME/quiz-helper/doctor-detect.png). Não instala nem altera nada;
# para cada falha mostra como corrigir.
#   quiz-doctor env   só compara a consulta ao Claude no terminal e via hyprctl (Lua).
set -uo pipefail

QH_REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/../.." && pwd)"
# shellcheck source=common.sh
source "$QH_REPO/lib/sh/common.sh"
# shellcheck source=notify.sh
source "$QH_REPO/lib/sh/notify.sh"
# shellcheck source=hypr.sh
source "$QH_REPO/lib/sh/hypr.sh"
# shellcheck source=claude.sh
source "$QH_REPO/lib/sh/claude.sh"
# shellcheck source=input.sh
source "$QH_REPO/lib/sh/input.sh"

case "${1:-}" in
    env) shift; PYTHONPATH="$QH_REPO/lib" exec "$QH_PYTHON" -m quizhelper envcheck "$@" ;;
esac
case "${1:-}" in
    -h|--help) sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
esac

if [[ -t 1 ]]; then
    G=$'\e[32m' R=$'\e[31m' Y=$'\e[33m' B=$'\e[1m' N=$'\e[0m'
else
    G="" R="" Y="" B="" N=""
fi
FAILS=0
WARNS=0
ok()   { printf '%s[  OK  ]%s %s\n' "$G" "$N" "$*"; }
fail() { printf '%s[FALHA ]%s %s\n' "$R" "$N" "$1"; [[ -n "${2:-}" ]] && printf '         como corrigir: %s\n' "$2"; FAILS=$(( FAILS + 1 )); }
warn() { printf '%s[AVISO ]%s %s\n' "$Y" "$N" "$1"; [[ -n "${2:-}" ]] && printf '         sugestão: %s\n' "$2"; WARNS=$(( WARNS + 1 )); }
section() { printf '\n%s%s%s\n' "$B" "$*" "$N"; }

# ------------------------------------------------------------------ dependências
section "Dependências"
declare -A PKG=(
    [grim]=grim [slurp]=slurp [tesseract]=tesseract [magick]=imagemagick [ydotool]=ydotool
    [ydotoold]=ydotool [notify-send]=libnotify [wl-copy]=wl-clipboard [jq]=jq [python3]=python
    [hyprctl]=hyprland [gdbus]=glib2 [flock]=util-linux [timeout]=coreutils
)
missing_pkgs=()
for cmd in grim slurp tesseract magick ydotool ydotoold notify-send wl-copy jq python3 hyprctl gdbus flock timeout; do
    if command -v "$cmd" > /dev/null 2>&1; then
        ok "$cmd ($(command -v "$cmd"))"
    else
        fail "$cmd não encontrado" "sudo pacman -S --needed ${PKG[$cmd]}"
        missing_pkgs+=("${PKG[$cmd]}")
    fi
done
if command -v tesseract > /dev/null 2>&1; then
    if tesseract --list-langs 2> /dev/null | grep -qx eng; then
        ok "tesseract: idioma eng instalado"
    else
        fail "tesseract sem o idioma eng" "sudo pacman -S --needed tesseract-data-eng"
        missing_pkgs+=(tesseract-data-eng)
    fi
fi
if command -v python3 > /dev/null 2>&1; then
    if python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
        ok "python $(python3 -c 'import platform; print(platform.python_version())')"
    else
        fail "python 3.10+ necessário" "sudo pacman -S python"
    fi
fi
if command -v shellcheck > /dev/null 2>&1; then
    ok "shellcheck (só para os testes)"
else
    warn "shellcheck ausente (só necessário para rodar os testes)" "sudo pacman -S --needed shellcheck"
fi
if (( ${#missing_pkgs[@]} )); then
    printf '         instalar tudo: sudo pacman -S --needed %s\n' "$(printf '%s\n' "${missing_pkgs[@]}" | sort -u | tr '\n' ' ')"
fi

# ------------------------------------------------------------------ ydotool
section "ydotool (cliques e roda do mouse)"
if [[ -e /dev/uinput ]]; then
    if [[ -r /dev/uinput && -w /dev/uinput ]]; then
        if id -nG | tr ' ' '\n' | grep -qx input; then
            ok "acesso ao /dev/uinput (grupo input)"
        else
            warn "acesso ao /dev/uinput só por ACL da sessão (uaccess), não pelo grupo input" \
                "sudo usermod -aG input \"$USER\" e encerre a sessão para valer de forma permanente"
        fi
    else
        fail "sem acesso ao /dev/uinput" "sudo usermod -aG input \"$USER\" e faça logout/login"
    fi
else
    fail "/dev/uinput não existe" "sudo modprobe uinput (e adicione uinput em /etc/modules-load.d/)"
fi
if pgrep -x ydotoold > /dev/null 2>&1; then
    if sock="$(qh_ydotool_socket)"; then
        ok "ydotoold rodando (socket $sock)"
    else
        fail "ydotoold rodando, mas nenhum socket encontrado (\$XDG_RUNTIME_DIR/.ydotool_socket ou /tmp/.ydotool_socket)" \
            "reinicie o daemon: systemctl --user restart ydotool"
    fi
else
    fail "ydotoold não está rodando" "systemctl --user enable --now ydotool.service"
fi

# ------------------------------------------------------------------ notificações
section "Notificações"
server="$(qh_notify_server)"
if [[ -n "$server" ]]; then
    ok "daemon de notificação: $server"
else
    fail "nenhum daemon de notificação respondeu no D-Bus" "inicie mako, dunst ou swaync no hyprland.conf (exec-once)"
fi
if qh_notify_dnd_active; then
    if [[ "${CFG_NOTIFY_OVER_DND:-1}" == 1 ]]; then
        warn "\"não perturbe\" ativo: as notificações do quiz-helper vão como críticas para aparecer" \
            "desligue o modo (swaync-client --toggle-dnd ou SUPER+SHIFT+D) se preferir notificações normais"
    else
        fail "\"não perturbe\" ativo e NOTIFY_OVER_DND=0: as notificações do quiz-helper ficam escondidas" \
            "desligue o modo (swaync-client --toggle-dnd) ou use NOTIFY_OVER_DND=1"
    fi
else
    ok "\"não perturbe\" desligado"
fi
if command -v notify-send > /dev/null 2>&1; then
    if qh_notify_has_print_id; then
        ok "notify-send $(notify-send --version 2> /dev/null | awk '{print $2}') com -p/-r (substituição de status)"
    else
        warn "notify-send sem -p; usando gdbus para substituir a notificação de status"
    fi
fi

# ------------------------------------------------------------------ Hyprland
section "Hyprland, navegador e monitores"
if [[ -z "${HYPRLAND_INSTANCE_SIGNATURE:-}" ]] || ! hyprctl version > /dev/null 2>&1; then
    fail "Hyprland não acessível (HYPRLAND_INSTANCE_SIGNATURE vazio ou hyprctl falhou)" \
        "rode o quiz-doctor de dentro da sessão do Hyprland"
else
    ok "$(hyprctl version 2> /dev/null | head -n1 | cut -d' ' -f1-2)"
    monitors="$(qh_hypr_monitors)"
    while IFS= read -r line; do ok "monitor $line"; done < <(jq -r '.[] |
        "\(.name): \(.width)x\(.height) em \(.x),\(.y), escala \(.scale)\(if .focused then " (foco)" else "" end)"' <<< "$monitors")
    while IFS= read -r name; do
        [[ -n "$name" ]] && warn "monitor $name com a tela apagada (DPMS); capturas nele falham" \
            "ligue a tela do monitor $name (onde fica o navegador) antes de usar o quiz-loop"
    done < <(jq -r '.[] | select(.dpmsStatus == false) | .name' <<< "$monitors")
    qh_load_config 2> /dev/null || true
    regex="${CFG_BROWSER_CLASS_REGEX:-^vivaldi}"
    clients="$(hyprctl -j clients 2> /dev/null)"
    match="$(jq -r --arg re "$regex" '[.[] | select(.class | test($re))] | first // empty |
        "\(.class) no monitor \(.monitor), \(.size[0])x\(.size[1]) em \(.at[0]),\(.at[1])"' <<< "$clients" 2> /dev/null)"
    if [[ -n "$match" ]]; then
        ok "navegador encontrado (BROWSER_CLASS_REGEX=$regex): $match"
    else
        classes="$(jq -r '[.[].class] | unique | join(", ")' <<< "$clients" 2> /dev/null)"
        fail "nenhuma janela casa com BROWSER_CLASS_REGEX=$regex (abertas: ${classes:-nenhuma})" \
            "abra o Vivaldi ou ajuste BROWSER_CLASS_REGEX em $QH_USER_CONFIG (veja a class com: hyprctl activewindow -j)"
    fi
fi

# ------------------------------------------------------------------ configuração
section "Configuração"
if [[ -f "$QH_USER_CONFIG" ]]; then
    if qv config --default "$QH_DEFAULT_CONFIG" --user "$QH_USER_CONFIG" > /dev/null 2> "${TMPDIR:-/tmp}/qh-doctor.err"; then
        ok "config válida: $QH_USER_CONFIG"
    else
        fail "config inválida: $(< "${TMPDIR:-/tmp}/qh-doctor.err")" "corrija $QH_USER_CONFIG (compare com $QH_DEFAULT_CONFIG)"
    fi
else
    warn "sem config pessoal ($QH_USER_CONFIG); usando os padrões" "rode ./install.sh"
fi
for p in answer retry; do
    if [[ -r "$QH_PROMPTS/$p.txt" ]]; then
        ok "prompt $p: $QH_PROMPTS/$p.txt"
    else
        fail "prompt ausente: $QH_PROMPTS/$p.txt" "restaure o arquivo com git checkout -- prompts/"
    fi
done
for c in quiz-loop quiz-ask quiz-doctor; do
    target="$HOME/.local/bin/$c"
    if [[ -L "$target" && "$(readlink -f "$target")" == "$QH_REPO/bin/$c" ]]; then
        ok "atalho $target"
    else
        warn "$target não aponta para este repositório" "rode ./install.sh"
    fi
done

# ------------------------------------------------------------------ Claude
section "Claude Code"
if bin="$(qh_claude_bin)"; then
    ok "claude: $bin ($("$bin" --version 2> /dev/null | head -n1))"
    tmpdir_sys="/tmp/claude-$(id -u)"
    if [[ -d "$tmpdir_sys" && "$(stat -c %u "$tmpdir_sys")" != "$(id -u)" ]]; then
        warn "$tmpdir_sys pertence a outro usuário ($(stat -c %U "$tmpdir_sys")); o claude recusa usá-lo" \
            "o quiz-helper contorna com um CLAUDE_CODE_TMPDIR próprio; para limpar de vez: sudo rm -rf $tmpdir_sys"
    fi
    if (unset CLAUDE_CODE_TMPDIR; qh_claude_env && [[ -O "$CLAUDE_CODE_TMPDIR" ]]); then
        ok "diretório temporário do claude nos atalhos: $QH_RUNTIME_DIR/claude-tmp (ou CLAUDE_CODE_TMPDIR)"
    else
        fail "não consegui preparar o diretório temporário do claude" "verifique permissões em $QH_RUNTIME_DIR"
    fi
    if status="$(timeout 20 "$bin" auth status 2> /dev/null)" && [[ "$(jq -r '.loggedIn' <<< "$status" 2> /dev/null)" == true ]]; then
        ok "login ativo ($(jq -r '[.authMethod, (.subscriptionType // empty)] | join(", ")' <<< "$status"))"
    else
        fail "claude sem login" "rode: claude auth login"
    fi
    if [[ -z "${CFG_CLAUDE_BIN:-}" && ! -r "$QH_PATHS_FILE" ]]; then
        warn "caminho do claude não fixado; atalhos do Hyprland podem não achar o PATH" "rode ./install.sh"
    fi
else
    fail "claude não encontrado" "instale o Claude Code e rode ./install.sh para fixar o caminho"
fi

# ------------------------------------------------------------------ OCR
section "OCR"
if command -v magick > /dev/null 2>&1 && command -v tesseract > /dev/null 2>&1; then
    tmpd="$(mktemp -d)"
    font="$(fc-match -f '%{file}' 'Liberation Sans' 2> /dev/null)"
    magick -size 520x90 xc:white ${font:+-font "$font"} -pointsize 26 -fill '#1f2933' \
        -annotate +20+55 'Power supply unit converts AC' "$tmpd/ocr.png" 2> /dev/null
    text="$(qv analyze "$tmpd/ocr.png" --no-cache 2> /dev/null | jq -r '.lines[0].text // ""')"
    if [[ "$text" == "Power supply unit converts AC" ]]; then
        ok "OCR leu o texto de teste corretamente"
    else
        fail "OCR leu '$text' (esperado 'Power supply unit converts AC')" "verifique tesseract e tesseract-data-eng"
    fi
    rm -rf "$tmpd"
fi

# ------------------------------------------------------------------ ambiente dos atalhos
section "Ambiente dos atalhos (terminal x hyprctl dispatch exec)"
probe="$QH_REPO/lib/sh/env-probe.sh"
term_out="$QH_RUNTIME_DIR/probe-terminal.txt"
bind_out="$QH_RUNTIME_DIR/probe-atalho.txt"
mkdir -p "$QH_RUNTIME_DIR"
rm -f "$term_out" "$bind_out"
"$probe" "$term_out" --claude
if qh_hypr_exec "$(printf '%q %q --claude' "$probe" "$bind_out")"; then
    for (( i = 0; i < 1200; i++ )); do
        [[ -f "$bind_out" ]] && break
        sleep 0.1
    done
else
    printf '         hyprctl dispatch exec falhou: %s\n' "$QH_HYPR_ERROR"
fi
probe_val() { sed -n "s/^$2=//p" "$1" 2> /dev/null | head -n1; }
if [[ ! -f "$bind_out" ]]; then
    fail "a sonda não rodou pelo hyprctl dispatch exec (como um atalho)" "veja hyprctl configerrors e se o Hyprland aceita exec"
else
    for key in CURSOR YDOTOOL_CLICK YDOTOOL_WHEEL CLAUDE; do
        case "$key" in
            CURSOR) label="mover o cursor (dispatcher do Hyprland)" ;;
            YDOTOOL_CLICK) label="ydotool click" ;;
            YDOTOOL_WHEEL) label="ydotool roda do mouse" ;;
            CLAUDE) label="claude -p" ;;
        esac
        t="$(probe_val "$term_out" "$key")"
        b="$(probe_val "$bind_out" "$key")"
        if [[ "$t" == 0 && "$b" == 0 ]]; then
            ok "$label: funciona no terminal e no atalho"
        elif [[ "$b" == 0 ]]; then
            warn "$label: funciona no atalho, mas falha no terminal: $(probe_val "$term_out" "${key}_ERR")"
        elif [[ "$t" == 0 ]]; then
            fail "$label: funciona no terminal, mas FALHA no atalho: $(probe_val "$bind_out" "${key}_ERR")" \
                "diferença de ambiente entre o shell e o Hyprland; veja $bind_out"
        else
            fail "$label: falha no terminal ($(probe_val "$term_out" "${key}_ERR")) e no atalho ($(probe_val "$bind_out" "${key}_ERR"))"
        fi
    done
    printf '         ambiente do atalho: YDOTOOL_SOCKET=%s, socket usado=%s, CLAUDE_CODE_TMPDIR=%s, ~/.local/bin no PATH=%s\n' \
        "$(probe_val "$bind_out" YDOTOOL_SOCKET_ENV)" "$(probe_val "$bind_out" YDOTOOL_SOCKET_FOUND)" \
        "$(probe_val "$bind_out" CLAUDE_CODE_TMPDIR_ENV)" "$(probe_val "$bind_out" PATH_HAS_LOCAL_BIN)"
fi

# ------------------------------------------------------------------ detecção da página
section "Detecção da página (quiz aberto no Vivaldi)"
DETECT_IMG="$QH_DATA_DIR/doctor-detect.png"
if [[ -z "${match:-}" ]]; then
    warn "nenhuma janela do Vivaldi; teste de detecção pulado" "abra um quiz no Vivaldi e rode quiz-doctor de novo"
elif qh_session_locked; then
    warn "sessão bloqueada; teste de detecção pulado (a captura pegaria a tela de bloqueio)" \
        "desbloqueie a sessão, abra um quiz no Vivaldi e rode quiz-doctor de novo"
else
    vjson="$(jq -c --arg re "$regex" '[.[] | select(.class | test($re))] | first' <<< "$clients")"
    vaddr="$(jq -r '.address' <<< "$vjson")"
    vws="$(jq -r '.workspace.id' <<< "$vjson")"
    vmon="$(jq -r '.monitor' <<< "$vjson")"
    prev_win="$(qh_hypr_active | jq -r '.address // empty')"
    prev_ws="$(jq -r --argjson m "$vmon" '.[] | select(.id == $m) | .activeWorkspace.id' <<< "$monitors")"
    switched=0
    if [[ "$prev_ws" != "$vws" ]]; then
        # A captura pega o que está na tela: mostra o workspace do Vivaldi por
        # um instante e depois devolve o workspace e a janela anteriores.
        qh_hypr_focus "$vaddr" && switched=1
        sleep 0.8
    fi
    wjson="$(qv window --active "$vjson" --monitors "$(qh_hypr_monitors)" --regex "$regex")"
    shot="$QH_RUNTIME_DIR/doctor-window.png"
    captured=0
    if [[ "$(jq -r '.window.dpms' <<< "$wjson")" == true ]]; then
        geom="$(jq -r '.window.geometry' <<< "$wjson")"
        scale="$(jq -r '.window.scale' <<< "$wjson")"
        origin="$(jq -r '"\(.window.at[0]),\(.window.at[1])"' <<< "$wjson")"
        timeout 10 grim -g "$geom" -s "$scale" -t png "$shot" && captured=1
    fi
    if (( switched )); then
        qh_hypr_dispatch "hl.dsp.focus({ workspace = $prev_ws })" workspace "$prev_ws"
        [[ -n "$prev_win" ]] && qh_hypr_focus "$prev_win"
    fi
    refocus=$switched
    if (( ! captured )); then
        fail "não consegui capturar a janela do Vivaldi (monitor $(jq -r '.window.monitor' <<< "$wjson") apagado?)" \
            "deixe o Vivaldi visível num monitor ligado"
    else
        ok "captura da janela: $(jq -r '"\(.window.size[0])x\(.window.size[1]) em \(.window.at[0]),\(.window.at[1]), monitor \(.window.monitor), escala \(.window.scale)"' <<< "$wjson")$( (( refocus )) && echo " (workspace $vws mostrado por um instante; workspace e janela anteriores devolvidos)")"
        det="$(qv detect --image "$shot" --scale "$scale" --arrow --origin "$origin" --annotate "$DETECT_IMG" \
            --default "$QH_DEFAULT_CONFIG" --user "$QH_USER_CONFIG" 2> "$QH_RUNTIME_DIR/doctor-detect.err")"
        if [[ -z "$det" ]]; then
            fail "a detecção falhou: $(head -c 300 "$QH_RUNTIME_DIR/doctor-detect.err")"
        else
            ok "área de conteúdo (sem a interface do Vivaldi): $(jq -r '.content | "\(.[2])x\(.[3]) em \(.[0]),\(.[1])"' <<< "$det")$(jq -r 'if .module_right then " — lista de módulos ignorada até x=\(.module_right)" else "" end' <<< "$det")"
            if [[ "$(jq -r '.panel != null' <<< "$det")" == true ]]; then
                ok "painel do quiz: $(jq -r '.panel | "\(.[2])x\(.[3]) em \(.[0]),\(.[1])"' <<< "$det") (âncoras: $(jq -r '.anchors | join("; ")' <<< "$det"))"
                if [[ "$(jq -r '.arrow != null' <<< "$det")" == true ]]; then
                    ok "seta de avançar: $(jq -r '.arrow | "\(.method) em \(.global[0]),\(.global[1]) na tela"' <<< "$det")"
                else
                    warn "seta de avançar não encontrada ($(jq -r '.arrow_reason' <<< "$det"))" \
                        "o quiz-loop vai pedir um clique na seta quando precisar"
                fi
            else
                warn "painel do quiz não encontrado: $(jq -r '.reason' <<< "$det")" \
                    "abra uma questão do quiz no Vivaldi e role até o topo dela"
            fi
            ok "imagem anotada: $DETECT_IMG"
        fi
        rm -f "$shot" "${shot%.png}".content.png "${shot%.png}".panel.png "${shot%.png}".*.page.json "$shot".page.json
    fi
fi

printf '\n'
if (( FAILS )); then
    printf '%s%d falha(s), %d aviso(s).%s\n' "$R" "$FAILS" "$WARNS" "$N"
    exit 1
fi
printf '%sTudo certo%s (%d aviso(s)).\n' "$G" "$N" "$WARNS"
