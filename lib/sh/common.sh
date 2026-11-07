# shellcheck shell=bash
# Base compartilhada: caminhos, configuração e chamada ao pacote quizhelper (Python do venv).
# Uso: QH_REPO definido pelo script chamador antes de `source`.

: "${QH_REPO:?QH_REPO não definido}"

# Números sempre com ponto decimal (printf/awk/sleep), seja qual for o locale.
export LC_NUMERIC=C

# Somente novas pastas/arquivos: dados locais privados por padrão.
umask 077

QH_CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/quiz-helper"
QH_DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper"
if [[ -n "${XDG_RUNTIME_DIR:-}" && -d "${XDG_RUNTIME_DIR}" ]]; then
    QH_RUNTIME_DIR="${QH_RUNTIME_DIR:-$XDG_RUNTIME_DIR/quiz-helper}"
else
    QH_RUNTIME_DIR="${QH_RUNTIME_DIR:-/tmp/quiz-helper-$(id -u)}"
fi
QH_DEFAULT_CONFIG="$QH_REPO/config/quiz-helper.conf"
QH_USER_CONFIG="$QH_CONFIG_DIR/config"
QH_PATHS_FILE="$QH_CONFIG_DIR/paths"
QH_PROMPTS="$QH_REPO/prompts"
QH_VENV="${QH_VENV:-$QH_DATA_DIR/venv}"
QH_PYTHON="${QH_PYTHON:-$QH_VENV/bin/python}"

export QH_CONFIG_DIR QH_DATA_DIR QH_RUNTIME_DIR QH_PROMPTS

qh_die() {
    printf 'quiz-helper: %s\n' "$*" >&2
    exit 1
}

qh_warn() {
    printf 'quiz-helper: %s\n' "$*" >&2
}

# Executa o pacote Python do repositório com o Python do venv (Playwright).
qv() {
    PYTHONPATH="$QH_REPO/lib${PYTHONPATH:+:$PYTHONPATH}" "$QH_PYTHON" -m quizhelper "$@"
}

# Lê um arquivo KEY=VALUE sem executá-lo e define CFG_<KEY>.
qh_read_kv() {
    local file="$1" line key value
    [[ -r "$file" ]] || return 0
    while IFS= read -r line || [[ -n "$line" ]]; do
        line="${line#"${line%%[![:space:]]*}"}"
        [[ -z "$line" || "$line" == \#* ]] && continue
        if [[ "$line" =~ ^([A-Z][A-Z0-9_]*)[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            key="${BASH_REMATCH[1]}"
            value="${BASH_REMATCH[2]}"
            value="${value%"${value##*[![:space:]]}"}"
            if [[ ${#value} -ge 2 && ( "$value" == \"*\" || "$value" == \'*\' ) ]]; then
                value="${value:1:${#value}-2}"
            fi
            printf -v "CFG_$key" '%s' "$value"
        else
            qh_warn "linha ignorada em $file: $line"
        fi
    done < "$file"
}

# Padrões do repositório < caminhos resolvidos na instalação < config do usuário.
qh_load_config() {
    qh_read_kv "$QH_DEFAULT_CONFIG"
    qh_read_kv "$QH_PATHS_FILE"
    qh_read_kv "$QH_USER_CONFIG"
    # Valida tipos e valores com o mesmo parser do Python.
    if ! qv config > /dev/null; then
        qh_die "configuração inválida em $QH_USER_CONFIG"
    fi
}

qh_require() {
    local missing=() cmd
    for cmd in "$@"; do
        command -v "$cmd" > /dev/null 2>&1 || missing+=("$cmd")
    done
    if (( ${#missing[@]} )); then
        qh_die "comandos ausentes: ${missing[*]} (rode quiz-doctor)"
    fi
}
