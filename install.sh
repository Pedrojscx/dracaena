#!/usr/bin/env bash
# Instalador idempotente do quiz-helper.
#
#   ./install.sh            cria os symlinks em ~/.local/bin, a config inicial
#                           (sem sobrescrever) e fixa o caminho do claude
#   ./install.sh --check    só verifica as dependências
#
# Não instala pacotes, não usa sudo e não edita o hyprland.conf: lista o que
# falta com o comando pacman correspondente e mostra as linhas dos atalhos.
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/quiz-helper"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper"
COMMANDS=(quiz-loop quiz-ask quiz-doctor)

say() { printf '%s\n' "$*"; }

check_deps() {
    local -A pkg=(
        [grim]=grim [slurp]=slurp [tesseract]=tesseract [magick]=imagemagick [ydotool]=ydotool
        [notify-send]=libnotify [wl-copy]=wl-clipboard [jq]=jq [python3]=python [gdbus]=glib2
        [hyprctl]=hyprland [flock]=util-linux
    )
    local missing=() cmd
    for cmd in "${!pkg[@]}"; do
        command -v "$cmd" > /dev/null 2>&1 || missing+=("${pkg[$cmd]}")
    done
    if command -v tesseract > /dev/null 2>&1 && ! tesseract --list-langs 2> /dev/null | grep -qx eng; then
        missing+=(tesseract-data-eng)
    fi
    if (( ${#missing[@]} )); then
        say "Dependências faltando. Instale com:"
        say "  sudo pacman -S --needed $(printf '%s\n' "${missing[@]}" | sort -u | tr '\n' ' ')"
        return 1
    fi
    say "Dependências: OK"
}

if [[ "${1:-}" == --check ]]; then
    check_deps
    exit $?
fi

deps_ok=1
check_deps || deps_ok=0

mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$DATA_DIR"

# Remove symlinks de comandos que deixaram de existir (ex.: quiz-calibrate).
for dst in "$BIN_DIR"/quiz-*; do
    [[ -L "$dst" ]] || continue
    target="$(readlink "$dst")"
    if [[ "$target" == "$REPO/bin/"* && ! -e "$target" ]]; then
        rm -f "$dst"
        say "symlink obsoleto removido: $dst"
    fi
done

for c in "${COMMANDS[@]}"; do
    src="$REPO/bin/$c"
    dst="$BIN_DIR/$c"
    chmod +x "$src"
    if [[ -L "$dst" ]]; then
        if [[ "$(readlink -f "$dst")" == "$src" ]]; then
            say "symlink já existe: $dst"
            continue
        fi
        ln -sfn "$src" "$dst"
        say "symlink atualizado: $dst -> $src"
    elif [[ -e "$dst" ]]; then
        say "AVISO: $dst existe e não é symlink; não foi alterado"
    else
        ln -s "$src" "$dst"
        say "symlink criado: $dst -> $src"
    fi
done

if [[ -f "$CONFIG_DIR/config" ]]; then
    say "config pessoal mantida: $CONFIG_DIR/config"
else
    cp "$REPO/config/quiz-helper.conf" "$CONFIG_DIR/config"
    say "config criada: $CONFIG_DIR/config"
fi

# Binds do Hyprland não carregam o PATH do shell interativo: fixa o claude.
# Mantém o caminho do lançador (symlink), não o binário versionado para o
# qual ele aponta: o claude se atualiza sozinho e troca esse destino.
claude_bin=""
for c in "$(command -v claude 2> /dev/null || true)" "$HOME/.local/bin/claude" "$HOME/.claude/local/claude"; do
    if [[ -n "$c" && -x "$c" ]]; then
        claude_bin="$(cd "$(dirname "$c")" && pwd)/$(basename "$c")"
        break
    fi
done
if [[ -n "$claude_bin" && -x "$claude_bin" ]]; then
    printf '# Gerado pelo install.sh; não editar (use a config pessoal para sobrepor).\nCLAUDE_BIN=%s\n' \
        "$claude_bin" > "$CONFIG_DIR/paths"
    say "claude: $claude_bin (gravado em $CONFIG_DIR/paths)"
else
    say "AVISO: claude não encontrado; instale o Claude Code e rode ./install.sh de novo"
fi

case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *) say "AVISO: $BIN_DIR não está no PATH do shell (os atalhos usam o caminho completo)" ;;
esac

cat <<MSG

Atalhos do Hyprland (a config não é editada automaticamente).

Config em Lua (hyprland.lua): copie config/hyprland-binds.lua para
~/.config/hypr/quiz-helper.lua e adicione ao hyprland.lua:

  do local chunk = loadfile(os.getenv("HOME") .. "/.config/hypr/quiz-helper.lua") if chunk then chunk() end end

Config clássica (hyprland.conf):

$(sed 's/^/  /' "$REPO/config/hyprland-binds.conf" | grep -v '^  #')

Próximos passos: quiz-doctor com um quiz aberto no Vivaldi, depois quiz-loop --dry-run.
MSG
(( deps_ok )) || exit 1
