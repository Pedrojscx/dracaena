#!/usr/bin/env bash
# Desinstalador idempotente: remove só os symlinks em ~/.local/bin que
# apontam para este repositório e o arquivo de caminhos gerado. A config
# pessoal e os logs ficam, a menos que se use --purge.
set -euo pipefail

REPO="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
CONFIG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/quiz-helper"
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/quiz-helper"
PURGE=0
[[ "${1:-}" == --purge ]] && PURGE=1

if [[ -n "${XDG_RUNTIME_DIR:-}" && -r "$XDG_RUNTIME_DIR/quiz-helper/loop.pid" ]]; then
    "$REPO/bin/quiz-loop" --stop || true
fi

for c in quiz-loop quiz-ask quiz-doctor quiz-browser; do
    dst="$HOME/.local/bin/$c"
    if [[ -L "$dst" && "$(readlink -f "$dst")" == "$REPO/bin/$c" ]]; then
        rm -f "$dst"
        printf 'removido: %s\n' "$dst"
    fi
done
rm -f "$CONFIG_DIR/paths"

if (( PURGE )); then
    rm -rf "$CONFIG_DIR" "$DATA_DIR"
    printf 'removidos: %s e %s\n' "$CONFIG_DIR" "$DATA_DIR"
else
    printf 'mantidos: %s (config) e %s (logs e capturas); use --purge para apagar\n' \
        "$CONFIG_DIR" "$DATA_DIR"
fi
printf 'Lembre de remover as linhas do quiz-helper do hyprland.conf.\n'
