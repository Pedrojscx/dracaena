# shellcheck shell=bash
# Chamada ao Claude Code (`claude -p`) com a imagem da questão.
#
# O claude roda dentro da pasta da imagem com apenas a ferramenta Read
# liberada, sem servidores MCP, sem comandos/skills e sem salvar sessão.

# qh_prompt <answer|retry> <imagem> [resposta anterior]
qh_prompt() {
    local file="$QH_PROMPTS/$1.txt" image="$2" previous="${3:-}" text
    [[ -r "$file" ]] || qh_die "prompt ausente: $file"
    text="$(< "$file")"
    text="${text//\{IMAGE\}/$image}"
    text="${text//\{PREVIOUS\}/$previous}"
    printf '%s\n' "$text"
}

# Junta várias capturas (rolagens) em uma imagem vertical.
qh_stitch() {
    local out="$1"
    shift
    if (( $# == 1 )); then
        cp -f "$1" "$out"
    else
        magick "$@" -background white -splice 0x8 -append "$out"
    fi
}

# O claude recusa um diretório temporário que não seja do usuário (ex.: um
# /tmp/claude-<uid> criado pelo root). Nos atalhos do Hyprland não há o
# ambiente do shell interativo, então fixamos um diretório próprio quando
# CLAUDE_CODE_TMPDIR não vier definido.
qh_claude_env() {
    if [[ -z "${CLAUDE_CODE_TMPDIR:-}" ]]; then
        export CLAUDE_CODE_TMPDIR="$QH_RUNTIME_DIR/claude-tmp"
    fi
    mkdir -p "$CLAUDE_CODE_TMPDIR" && chmod 700 "$CLAUDE_CODE_TMPDIR"
}

# qh_claude_start <answer|retry> <imagem> <saída> [anterior]
# Inicia em segundo plano; define QH_CLAUDE_PID. stdout -> saída, stderr -> saída.err
qh_claude_start() {
    local kind="$1" image="$2" out="$3" previous="${4:-}" bin prompt dir
    bin="$(qh_claude_bin)" || { printf 'claude não encontrado\n' > "$out.err"; QH_CLAUDE_PID=""; return 1; }
    qh_claude_env || { printf 'não consegui criar %s\n' "$CLAUDE_CODE_TMPDIR" > "$out.err"; QH_CLAUDE_PID=""; return 1; }
    prompt="$(qh_prompt "$kind" "$image" "$previous")"
    dir="$(dirname "$image")"
    local extra=()
    # shellcheck disable=SC2206
    [[ -n "${CFG_CLAUDE_EXTRA_ARGS:-}" ]] && extra=(${CFG_CLAUDE_EXTRA_ARGS})
    (
        cd "$dir" || exit 1
        exec timeout --kill-after=5 "${CFG_CLAUDE_TIMEOUT:-45}" "$bin" -p --model "${CFG_MODEL:-haiku}" \
            --tools Read --allowedTools Read --strict-mcp-config --disable-slash-commands \
            --no-session-persistence --output-format text "${extra[@]}" "$prompt"
    ) > "$out" 2> "$out.err" < /dev/null &
    QH_CLAUDE_PID=$!
}

# Espera o claude terminar. Chama "$1" (função de checagem) a cada 200 ms;
# se ela retornar 0, mata o claude e retorna 3. Retorna o código do claude.
qh_claude_wait() {
    local check="${1:-}" rc
    while kill -0 "$QH_CLAUDE_PID" 2> /dev/null; do
        if [[ -n "$check" ]] && "$check"; then
            kill -TERM "$QH_CLAUDE_PID" 2> /dev/null
            wait "$QH_CLAUDE_PID" 2> /dev/null
            return 3
        fi
        sleep 0.2
    done
    wait "$QH_CLAUDE_PID"
    rc=$?
    return "$rc"
}
