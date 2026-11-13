#!/bin/sh
# daemon-probe.sh <app> <fuse|extract>: sobe "daemon --simulate" num ambiente
# limpo (env -i, PATH=$PROBE_PATH ou /nonexistent, HOME, TMPDIR e XDG_RUNTIME_DIR
# temporários), espera
# o socket IPC e consulta "status" com o próprio executável como cliente. Se
# PROBE_HELLO=1 e houver python3 no ambiente que chama, também envia o pedido
# IPC "hello" cru pelo socket (o Python aqui é só cliente externo; o daemon
# testado continua sem acesso a ele). Usado pelo verify.sh no host e no
# contêiner; POSIX sh para rodar no ubuntu:22.04 puro.
# Saída: 0 se o daemon respondeu ao status, 1 caso contrário.
set -u
app="$1"
test_path="${PROBE_PATH:-/nonexistent}"
flag=""
[ "${2:-extract}" = extract ] && flag="--appimage-extract-and-run"

base="$(mktemp -d)"
mkdir -p "$base/home" "$base/run" "$base/tmp"
chmod 700 "$base/run"
sock="$base/run/dracaena/ctl.sock"

run_app() {
    # shellcheck disable=SC2086  # $flag vazio some de propósito
    env -i HOME="$base/home" TMPDIR="$base/tmp" XDG_RUNTIME_DIR="$base/run" PATH="$test_path" "$app" $flag "$@"
}

# setsid: o daemon fica num grupo próprio e o grupo inteiro (runtime do
# AppImage + processo extraído) é encerrado no fim.
# shellcheck disable=SC2016  # expande no sh filho
# TMPDIR próprio: o runtime deixa o diretório do extract-and-run para trás.
setsid sh -c 'exec env -i HOME="$1" TMPDIR="$1/../tmp" XDG_RUNTIME_DIR="$2" PATH="$5" "$3" ${4:+"$4"} daemon --simulate' \
    sh "$base/home" "$base/run" "$app" "$flag" "$test_path" >"$base/daemon.log" 2>&1 &
pid=$!

result=1
waited=0
while [ "$waited" -lt 60 ]; do
    if [ -S "$sock" ]; then
        break
    fi
    if ! kill -0 "$pid" 2>/dev/null; then
        break
    fi
    sleep 0.5
    waited=$((waited + 1))
done

echo "comando:     env -i HOME=<tmp> TMPDIR=<tmp> XDG_RUNTIME_DIR=<tmp> PATH=$test_path <app> $flag daemon --simulate"
if [ -S "$sock" ]; then
    echo "socket:      criado em ~$((waited / 2))s ($(stat -c '%a' "$sock"))"
    out="$(run_app status 2>&1)"
    rc=$?
    echo "status rc:   $rc"
    echo "status out:  $out"
    case "$out" in
        *'"ok": true'*) [ "$rc" = 0 ] && result=0 ;;
    esac
    if [ "${PROBE_HELLO:-0}" = 1 ]; then
        if command -v python3 >/dev/null 2>&1; then
            hello="$(python3 -I -c '
import socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(5)
s.connect(sys.argv[1])
s.sendall(b"{\"v\": 0, \"id\": 1, \"cmd\": \"hello\"}\n")
buf = b""
while not buf.endswith(b"\n"):
    chunk = s.recv(65536)
    if not chunk:
        break
    buf += chunk
sys.stdout.write(buf.decode())
' "$sock" 2>&1)"
            echo "hello rc:    $?"
            echo "hello out:   $hello"
        else
            echo "hello:       NÃO TESTADO (sem python3 como cliente externo)"
        fi
    fi
else
    echo "socket:      não apareceu em 30s"
fi

kill -TERM -- "-$pid" 2>/dev/null
i=0
while kill -0 "$pid" 2>/dev/null && [ "$i" -lt 20 ]; do sleep 0.5; i=$((i + 1)); done
kill -KILL -- "-$pid" 2>/dev/null
echo "daemon log:"
sed 's/^/  > /' "$base/daemon.log"
rm -rf "$base"
exit "$result"
