#!/usr/bin/env bash
# Instalador idempotente do quiz-helper.
#
#   ./install.sh            cria os symlinks em ~/.local/bin, a config inicial
#                           (sem sobrescrever) e fixa o caminho do claude
#   ./install.sh --check    só verifica as dependências
#
# Instala apenas dependências Python declaradas no venv privado.
# Não instala pacotes do sistema nem navegador; não edita o Hyprland.
set -euo pipefail
umask 077

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
BIN_DIR="$HOME/.local/bin"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/quiz-helper"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper"
COMMANDS=(quiz-loop quiz-ask quiz-doctor quiz-browser)

say() { printf '%s\n' "$*"; }

check_deps() {
    local missing=() cmd
    for cmd in python3 curl ss flock setsid; do
        command -v "$cmd" > /dev/null 2>&1 || missing+=("$cmd")
    done
    if (( ${#missing[@]} )); then
        say "Dependências DOM ausentes: ${missing[*]}. Instale pelo gerenciador do sistema."
        return 1
    fi
    python3 -c 'import sys, venv; sys.exit(sys.version_info < (3, 10))' || {
        say "Python 3.10+ com módulo venv é necessário."; return 1;
    }
    say "Dependências DOM básicas: OK."
}

if [[ "${1:-}" == --check ]]; then
    check_deps
    exit $?
fi

check_deps || exit 1

VENV="$DATA_DIR/venv"
if [[ ! -x "$VENV/bin/python" ]]; then
    python3 -m venv "$VENV" || { say "Falha ao criar venv: $VENV. Instale o suporte a venv do Python."; exit 1; }
fi
if ! "$VENV/bin/python" -m pip install --disable-pip-version-check -r "$REPO/requirements.txt"; then
    say "Falha ao instalar dependências declaradas. Verifique a rede/índice pip e execute install.sh novamente."
    exit 1
fi
say "Python DOM instalado em $VENV; nenhum navegador foi instalado."

mkdir -p "$BIN_DIR" "$CONFIG_DIR" "$DATA_DIR"

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

Próximos passos: quiz-browser, login no NetAcad, abra uma atividade e rode quiz-doctor.
O Chromium do Playwright é opcional e usado somente nos testes da guarda.
MSG
