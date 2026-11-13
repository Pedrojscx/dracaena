#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
OUT_DIR=${OUT_DIR:-dist/appimage}
case "$OUT_DIR" in
  /*|../*|*/../*|*/..) echo 'OUT_DIR deve ser relativo ao repositório, sem ..' >&2; exit 2 ;;
esac
mkdir -p "$ROOT/$OUT_DIR"
docker run --rm --platform linux/amd64 \
  --mount "type=bind,source=$ROOT,target=/src,readonly" \
  --mount "type=bind,source=$ROOT/$OUT_DIR,target=/output" \
  -e OUT_DIR=/output -e "OUTPUT_UID=$(id -u)" -e "OUTPUT_GID=$(id -g)" \
  -w /src ubuntu:22.04 bash packaging/appimage/container-build.sh >&2
printf '%s\n' "$ROOT/$OUT_DIR/dracaena-x86_64.AppImage"
