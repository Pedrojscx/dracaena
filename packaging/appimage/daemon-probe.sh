#!/bin/sh
# daemon-probe.sh <app> <fuse|extract>: sobe "daemon --simulate" num ambiente
# limpo (env -i, PATH=$PROBE_PATH ou /nonexistent, HOME, TMPDIR e
# XDG_RUNTIME_DIR temporários), espera o socket IPC e consulta "status" com o
# próprio executável como cliente. POSIX sh e sem Python, para rodar igual no
# host e no ubuntu:22.04 puro.
#
#   PROBE_PATH=<dir>       PATH dos processos testados (padrão /nonexistent)
#   PROBE_RUN_DIR=<dir>    XDG_RUNTIME_DIR a usar (padrão: temporário); o
#                          verify.sh passa um diretório visível do host para
#                          mandar o "hello" de fora, inclusive no contêiner
#   PROBE_WAIT_FILE=<arq>  depois do status, mantém o daemon vivo até esse
#                          arquivo existir (até 60 s)
#
# Saída: 0 se o daemon respondeu ao status, 1 caso contrário.
set -u
app="$1"
test_path="${PROBE_PATH:-/nonexistent}"
flag=""
[ "${2:-extract}" = extract ] && flag="--appimage-extract-and-run"

base="$(mktemp -d)"
mkdir -p "$base/home" "$base/run" "$base/tmp"
run="${PROBE_RUN_DIR:-$base/run}"
chmod 700 "$run"
sock="$run/dracaena/ctl.sock"

run_app() {
    # shellcheck disable=SC2086  # $flag vazio some de propósito
    env -i HOME="$base/home" TMPDIR="$base/tmp" XDG_RUNTIME_DIR="$run" PATH="$test_path" "$app" $flag "$@"
}

# setsid: o daemon fica num grupo próprio e o grupo inteiro (runtime do
# AppImage + processo extraído) é encerrado no fim. TMPDIR próprio: o runtime
# deixa o diretório do extract-and-run para trás.
# shellcheck disable=SC2016  # expande no sh filho
setsid sh -c 'exec env -i HOME="$1/home" TMPDIR="$1/tmp" XDG_RUNTIME_DIR="$2" PATH="$5" "$3" ${4:+"$4"} daemon --simulate' \
    sh "$base" "$run" "$app" "$flag" "$test_path" >"$base/daemon.log" 2>&1 &
pid=$!

result=1
waited=0
while [ "$waited" -lt 60 ]; do
    [ -S "$sock" ] && break
    kill -0 "$pid" 2>/dev/null || break
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
    if [ -n "${PROBE_WAIT_FILE:-}" ]; then
        i=0
        while [ ! -e "$PROBE_WAIT_FILE" ] && [ "$i" -lt 120 ]; do sleep 0.5; i=$((i + 1)); done
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
