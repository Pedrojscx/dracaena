#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
OUT_DIR=${OUT_DIR:-dist/appimage}
case "$OUT_DIR" in
  /*|../*|*/../*|*/..) echo 'OUT_DIR deve ser relativo ao repositório, sem ..' >&2; exit 2 ;;
esac
# Base de build fixada por digest: AlmaLinux 8 (glibc 2.28) da PyPA, imagem manylinux_2_28.
# Mantenha igual ao BUILD_IMAGE de .github/workflows/appimage.yml.
BUILD_IMAGE=${BUILD_IMAGE:-quay.io/pypa/manylinux_2_28_x86_64@sha256:d086f64cddcace250ef0f0073583c51b8298159303290a730c9f59bd91edfd2c}
mkdir -p "$ROOT/$OUT_DIR"
docker run --rm --platform linux/amd64 \
  --mount "type=bind,source=$ROOT,target=/src,readonly" \
  --mount "type=bind,source=$ROOT/$OUT_DIR,target=/output" \
  -e OUT_DIR=/output -e "OUTPUT_UID=$(id -u)" -e "OUTPUT_GID=$(id -g)" \
  -w /src "$BUILD_IMAGE" bash packaging/appimage/container-build.sh >&2
printf '%s\n' "$ROOT/$OUT_DIR/dracaena-x86_64.AppImage"
