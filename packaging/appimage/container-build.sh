#!/usr/bin/env bash
set -euo pipefail
ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
OUT_DIR=${OUT_DIR:-dist/appimage}
[[ "$OUT_DIR" = /* ]] || OUT_DIR="$ROOT/$OUT_DIR"
[[ $(uname -m) = x86_64 ]] || { echo 'Build exige x86_64' >&2; exit 2; }
. /etc/os-release
[[ "$ID:$VERSION_ID" = ubuntu:22.04 ]] || { echo 'Build exige ubuntu:22.04' >&2; exit 2; }
export DEBIAN_FRONTEND=noninteractive
apt-get update >&2
apt-get install -y --no-install-recommends build-essential ca-certificates curl xz-utils \
  libssl-dev zlib1g-dev libffi-dev libbz2-dev liblzma-dev libsqlite3-dev \
  libreadline-dev libncurses-dev libgdbm-dev uuid-dev file desktop-file-utils >&2
WORK=$(mktemp -d /tmp/dracaena-build.XXXXXX)
trap 'rm -rf "$WORK"' EXIT
fetch() {
  curl --fail --location --retry 2 --proto '=https' --tlsv1.2 "$1" -o "$2" >&2
  printf '%s  %s\n' "$3" "$2" | sha256sum --check >&2
}
fetch https://www.python.org/ftp/python/3.12.8/Python-3.12.8.tar.xz "$WORK/python.tar.xz" \
  c909157bb25ec114e5869124cc2a9c4a4d4c1e957ca4ff553f1edc692101154e
tar -xf "$WORK/python.tar.xz" -C "$WORK"
cd "$WORK/Python-3.12.8"
./configure --prefix="$WORK/python" --enable-shared --with-ensurepip=install >&2
make -j"${BUILD_JOBS:-4}" >&2
make install >&2
export LD_LIBRARY_PATH="$WORK/python/lib"
PY="$WORK/python/bin/python3.12"
"$PY" -c 'import sys; assert sys.version_info[:3] == (3, 12, 8)'
# Dependências de execução desta fase; o navegador reserva é opcional e fica fora.
"$PY" -m pip install --index-url https://pypi.org/simple --disable-pip-version-check \
  --require-hashes --only-binary=:all: -r "$ROOT/packaging/appimage/requirements-build.txt" >&2
"$PY" -c 'import PyInstaller; assert PyInstaller.__version__ == "6.22.3"'
fetch https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage \
  "$WORK/appimagetool" ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0
fetch https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64 \
  "$WORK/runtime" 2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d
chmod +x "$WORK/appimagetool"
cd "$ROOT"
"$PY" -m PyInstaller --noconfirm --clean --distpath "$WORK/dist" \
  --workpath "$WORK/freeze" packaging/appimage/dracaena.spec >&2
APPDIR="$WORK/Dracaena.AppDir"
mkdir -p "$APPDIR/usr/bin" "$OUT_DIR"
cp -a "$WORK/dist/dracaena/." "$APPDIR/usr/bin/"
cp packaging/appimage/{AppRun,dracaena.desktop,dracaena.svg} "$APPDIR/"
chmod +x "$APPDIR/AppRun"
ln -s dracaena.svg "$APPDIR/.DirIcon"
desktop-file-validate "$APPDIR/dracaena.desktop"
ARCH=x86_64 "$WORK/appimagetool" --appimage-extract-and-run \
  --runtime-file "$WORK/runtime" "$APPDIR" "$OUT_DIR/dracaena-x86_64.AppImage" >&2
find "$APPDIR/usr/bin" -type f -printf '%s %P\n' | sort -nr > "$OUT_DIR/bundled-sizes.txt"
"$PY" -m pip freeze > "$OUT_DIR/build-packages.txt"
sha256sum "$OUT_DIR/dracaena-x86_64.AppImage" >&2
stat -c '%s bytes' "$OUT_DIR/dracaena-x86_64.AppImage" >&2
if [[ -n ${OUTPUT_UID:-} && -n ${OUTPUT_GID:-} ]]; then
  chown "$OUTPUT_UID:$OUTPUT_GID" "$OUT_DIR" "$OUT_DIR/"{dracaena-x86_64.AppImage,bundled-sizes.txt,build-packages.txt}
fi
printf '%s\n' "$OUT_DIR/dracaena-x86_64.AppImage"
