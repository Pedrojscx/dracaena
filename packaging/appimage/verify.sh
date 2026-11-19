#!/usr/bin/env bash
# verify.sh <arquivo.AppImage>: prova que o AppImage roda sem o Python do
# sistema e sem o venv do projeto.
#
#   (a) host: env -i HOME=<temporário> PATH=/nonexistent (sem PYTHON*/VIRTUAL_ENV);
#       TMPDIR=<temporário> também, porque o runtime não apaga o diretório
#       do --appimage-extract-and-run;
#       usa FUSE se houver (cai para --appimage-extract-and-run se falhar),
#       senão --appimage-extract-and-run;
#   (b) contêiner sem Python (ubuntu:22.04 puro; confere "command -v python3"
#       vazio lá dentro), mesmos comandos, sempre --appimage-extract-and-run;
#   (c) tamanho do arquivo, maiores bibliotecas embutidas (.so), tamanho
#       extraído e, se existirem ao lado do AppImage, bundled-sizes.txt e
#       build-packages.txt gerados pelo build.
#
# Critérios em (a) e (b), todos sem marca de erro de ambiente (traceback,
# import, biblioteca compartilhada ausente, falha do carregador PyInstaller):
#   --help                  exit 0 e texto de uso do programa
#   doctor                  exit 0 ou 1 (1 = pendências, ex.: sem navegador)
#                           e relatório JSON com "checks"
#   daemon --simulate       socket IPC criado e "status" (o próprio executável
#                           como cliente) com exit 0 e "ok": true
#   hello.toggle_cmd        pedido IPC "hello" ao daemon acima, mandado do host
#                           por python3 -I (só cliente externo; o daemon testado
#                           não o vê; no contêiner, pelo XDG_RUNTIME_DIR montado):
#                           toggle_cmd[0] tem de ser o arquivo .AppImage
#                           (host: o caminho real; contêiner: /work/app.AppImage).
#                           Sem python3 no host fica NÃO TESTADO
#   --version e -V          exit 0 e saída "dracaena <versão>"
#
# Variáveis opcionais:
#   VERIFY_VERSION=0            artefato anterior ao --version: registra como
#                               PENDENTE em vez de reprovar (padrão: 1, exige)
#   VERIFY_PATH_TOOLS="readlink dirname"   relaxa PATH=/nonexistent para um
#                               diretório só com essas ferramentas (confere que
#                               não há python nele); o padrão é o critério estrito
#   VERIFY_IMAGE=ubuntu:22.04   imagem do item (b)
#   VERIFY_SKIP_CONTAINER=1     pula (b) e o registra como NÃO TESTADO
#   VERIFY_HOST_MODE=auto|fuse|extract   modo do item (a) (padrão: auto)
#   VERIFY_TOP=15               quantas bibliotecas listar
#   VERIFY_TIMEOUT=120          limite em segundos por execução
#   VERIFY_KEEP=1               mantém o diretório de trabalho
#
# Saída: 0 se tudo passou, 1 se alguma verificação falhou, 2 em erro de uso.
set -euo pipefail

usage() { sed -n '2,44p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }
case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") usage >&2; exit 2 ;;
esac
[[ -f "$1" ]] || { echo "verify.sh: arquivo não encontrado: $1" >&2; exit 2; }

HERE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
PROBE="$HERE/daemon-probe.sh"
[[ -f "$PROBE" ]] || { echo "verify.sh: falta $PROBE" >&2; exit 2; }
IMAGE="${VERIFY_IMAGE:-ubuntu:22.04}"
TOP="${VERIFY_TOP:-15}"
TIMEOUT="${VERIFY_TIMEOUT:-120}"
HOST_MODE="${VERIFY_HOST_MODE:-auto}"
VERSION_REQUIRED="${VERIFY_VERSION:-1}"
TOOLS="${VERIFY_PATH_TOOLS:-}"
SRC="$(readlink -f "$1")"
SRC_DIR="$(dirname "$SRC")"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/appimage-verify.XXXXXX")"
# shellcheck disable=SC2329  # chamada pelo trap EXIT
cleanup() {
    [[ -n "${CTR_NAME:-}" ]] && docker rm -f "$CTR_NAME" >/dev/null 2>&1
    if [[ "${VERIFY_KEEP:-0}" == 1 ]]; then
        echo "diretório de trabalho mantido: $WORK"
    else
        chmod -R u+rwX "$WORK" 2>/dev/null || true
        rm -rf "$WORK"
    fi
}
trap cleanup EXIT

# Cópia própria: não altera o arquivo de entrada e garante o bit de execução.
APP="$WORK/app.AppImage"
cp "$SRC" "$APP"
cp "$PROBE" "$WORK/daemon-probe.sh"
chmod 0755 "$APP" "$WORK/daemon-probe.sh" "$WORK"

# PATH dos processos testados: /nonexistent, ou um diretório só com $TOOLS.
TEST_PATH=/nonexistent
if [[ -n "$TOOLS" ]]; then
    TEST_PATH="$WORK/shim"
    mkdir "$TEST_PATH"
    for t in $TOOLS; do
        [[ "$t" == *python* ]] && { echo "verify.sh: VERIFY_PATH_TOOLS não pode conter python" >&2; exit 2; }
        target="$(command -v "$t")" || { echo "verify.sh: ferramenta ausente no host: $t" >&2; exit 2; }
        ln -s "$target" "$TEST_PATH/$t"
    done
fi

# Marcas de erro de ambiente: Python ausente/quebrado ou biblioteca faltando.
ERROR_RE='Traceback \(most recent call last\)|ModuleNotFoundError|ImportError|No module named|Failed to execute script|\[PYI-[0-9]+:ERROR\]|Failed to load Python shared library|error while loading shared libraries|cannot open shared object file|version `GLIBC_[0-9.]+'"'"' not found'

declare -a RESULTS=()
FAILED=0
record() {  # status rótulo detalhe
    RESULTS+=("$(printf '%-12s %-30s %s' "$1" "$2" "$3")")
    [[ "$1" == FALHOU ]] && FAILED=1
    return 0
}

section() { printf '\n==== %s ====\n' "$*"; }

# Roda o comando, guarda saída e exit code em $WORK/<nome>.{out,rc}.
capture() {  # nome comando...
    local name="$1"; shift
    local rc=0
    timeout --kill-after=10 "$TIMEOUT" "$@" >"$WORK/$name.out" 2>&1 || rc=$?
    echo "$rc" >"$WORK/$name.rc"
}

show() {  # nome comando-exibido
    echo "\$ $2"
    sed 's/^/  | /' "$WORK/$1.out"
    echo "  exit code: $(cat "$WORK/$1.rc")"
}

# Avalia um caso e registra o resultado.
judge() {  # nome rótulo tipo(help|version|doctor|daemon)
    local name="$1" label="$2" kind="$3" rc out
    rc="$(cat "$WORK/$name.rc")"
    out="$WORK/$name.out"
    if [[ "$kind" == version && "$VERSION_REQUIRED" != 1 ]]; then
        record PENDENTE "$label" "exit $rc; não exigido (VERIFY_VERSION=0)"
        return 0
    fi
    if grep -Eq "$ERROR_RE" "$out"; then
        record FALHOU "$label" "exit $rc; erro de ambiente: $(grep -Eo "$ERROR_RE" "$out" | head -n1)"
        return 0
    fi
    if [[ "$rc" == 124 || "$rc" == 137 ]]; then
        record FALHOU "$label" "exit $rc; estourou ${TIMEOUT}s"
        return 0
    fi
    case "$kind" in
        help)
            if [[ "$rc" == 0 ]] && grep -q 'dracaena' "$out" && grep -Eqi 'usage|uso' "$out"; then
                record OK "$label" "exit 0; texto de uso"
            else
                record FALHOU "$label" "exit $rc; esperado 0 com texto de uso"
            fi ;;
        version)
            if [[ "$rc" == 0 ]] && grep -Eq '^dracaena [0-9]' "$out"; then
                record OK "$label" "exit 0; $(head -n1 "$out")"
            else
                record FALHOU "$label" "exit $rc; esperado 0 e \"dracaena <versão>\""
            fi ;;
        doctor)
            if [[ "$rc" != 0 && "$rc" != 1 ]]; then
                record FALHOU "$label" "exit $rc; esperado 0 ou 1"
            elif ! grep -q '"checks"' "$out"; then
                record FALHOU "$label" "exit $rc; relatório sem \"checks\""
            else
                record OK "$label" "exit $rc; relatório produzido"
            fi ;;
        daemon)
            if [[ "$rc" == 0 ]]; then
                record OK "$label" "socket criado; status respondeu ok"
            else
                record FALHOU "$label" "exit $rc; daemon não respondeu ao status"
            fi ;;
    esac
}

kind_of() { case "$1" in --help) echo help ;; --version|-V) echo version ;; *) echo "$1" ;; esac; }
case_name() { local c="${1//-/}"; echo "$2_$c"; }

# Cliente "hello" externo: manda o pedido IPC cru e confere toggle_cmd[0].
HELLO_PY='
import json, socket, sys
s = socket.socket(socket.AF_UNIX)
s.settimeout(10)
s.connect(sys.argv[1])
s.sendall(b"{\"v\": 0, \"id\": 1, \"cmd\": \"hello\"}\n")
buf = b""
while not buf.endswith(b"\n"):
    chunk = s.recv(65536)
    if not chunk:
        break
    buf += chunk
print(buf.decode().strip())
reply = json.loads(buf)
cmd = (reply.get("data") or {}).get("toggle_cmd")
print("toggle_cmd:", json.dumps(cmd), "| esperado[0]:", sys.argv[2])
sys.exit(0 if reply.get("ok") and isinstance(cmd, list) and cmd and cmd[0] == sys.argv[2] else 3)
'
HAVE_PY=0
command -v python3 >/dev/null 2>&1 && HAVE_PY=1

# Sobe o daemon (daemon-probe.sh) em segundo plano com XDG_RUNTIME_DIR visível
# do host, manda o hello de fora e então libera o probe para encerrar.
run_daemon() {  # nome host|ctr modo
    local name="$1" where="$2" mode="$3" run="$WORK/$1.run" expected pid rc=0 i=0
    rm -rf "$run"
    mkdir -m 700 "$run"
    if [[ "$where" == host ]]; then
        expected="$(readlink -f "$APP")"
        timeout --kill-after=10 "$TIMEOUT" env PROBE_PATH="$TEST_PATH" PROBE_RUN_DIR="$run" \
            PROBE_WAIT_FILE="$run/done" sh "$WORK/daemon-probe.sh" "$APP" "$mode" >"$WORK/$name.out" 2>&1 &
        echo "sh daemon-probe.sh <app> $mode   # daemon --simulate + status; hello do host" >"$WORK/$name.cmd"
    else
        expected=/work/app.AppImage
        CTR_NAME="appimage-verify-$$-$RANDOM"
        # shellcheck disable=SC2016  # expande dentro do contêiner
        timeout --kill-after=10 "$TIMEOUT" docker run --rm --name "$CTR_NAME" "${DOCKER_OPTS[@]}" -v "$run:/xdg" "$IMAGE" \
            sh -c "$PREFIX"'PROBE_PATH="$p" PROBE_RUN_DIR=/xdg PROBE_WAIT_FILE=/xdg/done exec sh /work/daemon-probe.sh /work/app.AppImage extract' \
            >"$WORK/$name.out" 2>&1 &
        echo "$SHOWN -v <run>:/xdg sh /work/daemon-probe.sh /work/app.AppImage extract   # PATH=$SHOWN_PATH; hello do host pelo socket em <run>" >"$WORK/$name.cmd"
    fi
    pid=$!
    while [[ ! -S "$run/dracaena/ctl.sock" ]] && kill -0 "$pid" 2>/dev/null && (( i < TIMEOUT * 2 )); do
        sleep 0.5
        i=$((i + 1))
    done
    if [[ ! -S "$run/dracaena/ctl.sock" ]]; then
        echo "socket não apareceu" >"$WORK/$name.hello"; echo nosock >"$WORK/$name.hellorc"
    elif [[ "$HAVE_PY" == 1 ]]; then
        local hrc=0
        timeout 30 python3 -I -c "$HELLO_PY" "$run/dracaena/ctl.sock" "$expected" >"$WORK/$name.hello" 2>&1 || hrc=$?
        echo "$hrc" >"$WORK/$name.hellorc"
    else
        echo "sem python3 no host para o cliente externo" >"$WORK/$name.hello"; echo nopy >"$WORK/$name.hellorc"
    fi
    touch "$run/done"
    wait "$pid" || rc=$?
    echo "$rc" >"$WORK/$name.rc"
    CTR_NAME=""
}

judge_hello() {  # nome rótulo
    local hrc
    hrc="$(cat "$WORK/$1.hellorc")"
    echo "  hello (cliente externo python3 -I):"
    sed 's/^/  | /' "$WORK/$1.hello"
    case "$hrc" in
        0) record OK "$2" "toggle_cmd[0] = arquivo .AppImage" ;;
        nopy) record "NÃO TESTADO" "$2" "sem python3 no host para o cliente externo" ;;
        nosock) record FALHOU "$2" "daemon não criou o socket" ;;
        *) record FALHOU "$2" "hello rc $hrc; toggle_cmd não aponta para o .AppImage" ;;
    esac
}

section "Arquivo"
SIZE="$(stat -c %s "$SRC")"
echo "caminho: $SRC"
echo "tamanho: $SIZE bytes ($(numfmt --to=iec-i --suffix=B "$SIZE"))"
echo "sha256:  $(sha256sum "$SRC" | cut -d' ' -f1)"
command -v file >/dev/null && echo "tipo:    $(file -b "$SRC")"
echo "PATH dos testes: $([[ -n "$TOOLS" ]] && echo "diretório só com: $TOOLS" || echo /nonexistent)"
echo "--version como critério: $([[ "$VERSION_REQUIRED" == 1 ]] && echo sim || echo 'não (VERIFY_VERSION=0)')"

# ---------------------------------------------------------------- (a) host
section "(a) Host sem Python no ambiente (env -i, PATH=$TEST_PATH)"
fuse_usable() {
    [[ -r /dev/fuse && -w /dev/fuse ]] && { command -v fusermount3 || command -v fusermount; } >/dev/null 2>&1
}
case "$HOST_MODE" in
    auto) if fuse_usable; then HOST_MODE=fuse; else HOST_MODE=extract; fi ;;
    fuse|extract) ;;
    *) echo "VERIFY_HOST_MODE inválido: $HOST_MODE" >&2; exit 2 ;;
esac
echo "modo: $HOST_MODE"
echo "variáveis Python/venv no shell que chama (todas descartadas pelo env -i):"
env | grep -E '^(PYTHON[A-Z_]*|VIRTUAL_ENV|CONDA_PREFIX|QH_PYTHON)=' | sed 's/^/  /' || echo "  (nenhuma)"
echo "ambiente visto pelo processo testado: $(env -i HOME=/tmp/x TMPDIR=/tmp/y PATH="$TEST_PATH" /usr/bin/env | tr '\n' ' ')"
if [[ -n "$TOOLS" ]]; then
    echo "conteúdo do PATH: $(find "$TEST_PATH" -mindepth 1 -printf '%f '); python3 nele: [$(PATH="$TEST_PATH" command -v python3 || true)]"
    record INFO "PATH relaxado" "PATH só com: $TOOLS (critério estrito é /nonexistent)"
fi

host_run() {  # nome modo args...
    local name="$1" mode="$2"; shift 2
    local home extra=()
    home="$(mktemp -d "$WORK/home.XXXXXX")"
    [[ "$mode" == extract ]] && extra=(--appimage-extract-and-run)
    if [[ "$1" == daemon ]]; then
        run_daemon "$name" host "$mode"
    else
        mkdir "$home/tmp"
        capture "$name" env -i HOME="$home" TMPDIR="$home/tmp" PATH="$TEST_PATH" "$APP" "${extra[@]}" "$@"
        echo "env -i HOME=<tmp> TMPDIR=<tmp> PATH=$TEST_PATH <app> ${extra[*]} $*" >"$WORK/$name.cmd"
    fi
}

for cmd in --help doctor daemon --version -V; do
    name="$(case_name "$cmd" host)"
    mode="$HOST_MODE"
    host_run "$name" "$mode" "$cmd"
    if [[ "$mode" == fuse && "$(cat "$WORK/$name.rc")" != 0 ]] \
        && grep -Eqi 'fuse|fusermount|squashfs|mount' "$WORK/$name.out"; then
        echo "FUSE falhou com PATH=$TEST_PATH:"
        sed 's/^/  | /' "$WORK/$name.out"
        record INFO "host $cmd (FUSE)" "falhou ao montar; repetido com --appimage-extract-and-run"
        mode=extract
        host_run "$name" "$mode" "$cmd"
    fi
    show "$name" "$(cat "$WORK/$name.cmd")"
    judge "$name" "host $cmd ($mode)" "$(kind_of "$cmd")"
    if [[ "$cmd" == daemon ]]; then judge_hello "$name" "host hello.toggle_cmd"; fi
done

# ------------------------------------------------------------ (b) contêiner
section "(b) Contêiner sem Python ($IMAGE)"
if [[ "${VERIFY_SKIP_CONTAINER:-0}" == 1 ]]; then
    echo "pulado por VERIFY_SKIP_CONTAINER=1"
    record "NÃO TESTADO" "contêiner $IMAGE" "VERIFY_SKIP_CONTAINER=1"
elif ! command -v docker >/dev/null 2>&1 || ! docker info >/dev/null 2>&1; then
    echo "docker indisponível"
    record FALHOU "contêiner $IMAGE" "docker indisponível (VERIFY_SKIP_CONTAINER=1 pula)"
else
    docker image inspect "$IMAGE" >/dev/null 2>&1 || docker pull -q "$IMAGE" >/dev/null
    echo "imagem: $IMAGE ($(docker image inspect -f '{{.Id}}' "$IMAGE"))"
    DOCKER_OPTS=(--network none --user "$(id -u):$(id -g)" -e "VERIFY_PATH_TOOLS=$TOOLS"
                 -v "$WORK/app.AppImage:/work/app.AppImage:ro"
                 -v "$WORK/daemon-probe.sh:/work/daemon-probe.sh:ro")
    DOCKER=(docker run --rm "${DOCKER_OPTS[@]}" "$IMAGE")
    # Mesmo PATH do host, montado dentro do contêiner com as ferramentas dele.
    # shellcheck disable=SC2016  # expande dentro do contêiner
    PREFIX='p=/nonexistent; if [ -n "$VERIFY_PATH_TOOLS" ]; then mkdir /tmp/shim; for t in $VERIFY_PATH_TOOLS; do c=$(command -v "$t") && ln -s "$c" /tmp/shim/"$t"; done; p=/tmp/shim; fi; '
    SHOWN_PATH="${TOOLS:+<dir com: $TOOLS (as que existirem na imagem)>}"
    SHOWN_PATH="${SHOWN_PATH:-/nonexistent}"
    SHOWN="docker run --rm --network none --user $(id -u):$(id -g) -v <app>:/work/app.AppImage:ro $IMAGE"

    # shellcheck disable=SC2016  # expande dentro do contêiner
    capture ctr_python "${DOCKER[@]}" sh -c \
        'echo "python3=[$(command -v python3)] python=[$(command -v python)]"; ls /usr/bin/python* /usr/local/bin/python* 2>/dev/null; true'
    show ctr_python "$SHOWN sh -c 'command -v python3; command -v python; ls /usr/bin/python* /usr/local/bin/python*'"
    if grep -qx 'python3=\[\] python=\[\]' "$WORK/ctr_python.out" \
        && [[ "$(wc -l <"$WORK/ctr_python.out")" == 1 ]]; then
        record OK "contêiner sem python3" "command -v python3 vazio"
    else
        record FALHOU "contêiner sem python3" "a imagem tem Python; a prova não vale"
    fi

    for cmd in --help doctor daemon --version -V; do
        name="$(case_name "$cmd" ctr)"
        if [[ "$cmd" == daemon ]]; then
            run_daemon "$name" ctr extract
            show "$name" "$(cat "$WORK/$name.cmd")"
            judge "$name" "contêiner $cmd" daemon
            judge_hello "$name" "contêiner hello.toggle_cmd"
            continue
        else
            # shellcheck disable=SC2016  # expande dentro do contêiner
            capture "$name" "${DOCKER[@]}" sh -c \
                "$PREFIX"'h=$(mktemp -d); exec env -i HOME="$h" PATH="$p" /work/app.AppImage --appimage-extract-and-run "$@"' \
                sh "$cmd"
            show "$name" "$SHOWN sh -c 'env -i HOME=\$(mktemp -d) PATH=$SHOWN_PATH /work/app.AppImage --appimage-extract-and-run $cmd'"
        fi
        judge "$name" "contêiner $cmd" "$(kind_of "$cmd")"
    done
fi

# ------------------------------------------------------------ (c) conteúdo
section "(c) Conteúdo extraído"
if (cd "$WORK" && env -i PATH=/nonexistent "$APP" --appimage-extract >/dev/null 2>"$WORK/extract.err") \
    && [[ -d "$WORK/squashfs-root" ]]; then
    ROOT="$WORK/squashfs-root"
    TOTAL="$(du -sb "$ROOT" | cut -f1)"
    mapfile -t SOS < <(find "$ROOT" -type f \( -name '*.so' -o -name '*.so.*' \) -printf '%s\t%P\n' | sort -nr)
    SO_TOTAL=0
    for line in "${SOS[@]}"; do SO_TOTAL=$((SO_TOTAL + ${line%%$'\t'*})); done
    echo "total extraído:   $TOTAL bytes ($(numfmt --to=iec-i --suffix=B "$TOTAL")), $(find "$ROOT" -type f | wc -l) arquivos"
    echo "bibliotecas .so:  ${#SOS[@]} arquivos, $SO_TOTAL bytes ($(numfmt --to=iec-i --suffix=B "$SO_TOTAL"))"
    echo
    echo "as $TOP maiores bibliotecas embutidas:"
    printf '%s\n' "${SOS[@]}" | head -n "$TOP" \
        | while IFS=$'\t' read -r bytes path; do
            printf '  %10s  %10s  %s\n' "$bytes" "$(numfmt --to=iec-i --suffix=B "$bytes")" "$path"
        done
    echo
    echo "libpython embutida:"
    printf '%s\n' "${SOS[@]}" | cut -f2 | grep -E '(^|/)libpython[0-9.]+\.so' | sed 's/^/  /' || echo "  (nenhuma encontrada)"
    echo
    echo "AppRun: $(if [[ -L "$ROOT/AppRun" ]]; then echo "link para $(readlink "$ROOT/AppRun")"; else file -b "$ROOT/AppRun" 2>/dev/null || echo presente; fi)"
    [[ -f "$ROOT/AppRun" && ! -L "$ROOT/AppRun" ]] && head -n1 "$ROOT/AppRun" | grep -q '^#!' \
        && sed 's/^/  | /' "$ROOT/AppRun"
    # Executáveis cujo shebang chama um Python externo dependeriam do sistema.
    SHEBANGS="$(find "$ROOT" -type f -perm -u+x ! -name '*.so' ! -name '*.so.*' -print0 \
        | while IFS= read -r -d '' f; do
            first="$(head -c 128 "$f" | tr -d '\0' | head -n1)"
            [[ "$first" == '#!'*python* ]] && printf '  %s: %s\n' "${f#"$ROOT"/}" "$first"
        done || true)"
    if [[ -n "$SHEBANGS" ]]; then
        echo "executáveis com shebang Python:"
        echo "$SHEBANGS"
        record FALHOU "sem shebang Python" "há executáveis que chamam um Python externo"
    else
        echo "executáveis com shebang Python: nenhum"
        record OK "sem shebang Python" "nenhum executável depende de Python externo"
    fi
    if command -v objdump >/dev/null 2>&1; then
        GLIBC="$(find "$ROOT" -type f -print0 \
            | xargs -0 -r objdump -T 2>/dev/null | grep -Eo 'GLIBC_[0-9]+(\.[0-9]+)+' | sort -Vu | tail -n1 || true)"
        echo "maior versão GLIBC exigida pelos ELF embutidos: ${GLIBC:-(nenhuma)}"
    fi
    PROMPTS_ROOT="$ROOT/usr/bin/_internal/prompts"
    PROMPTS=(system.txt answer.txt invalid.txt retry.txt)
    missing_prompts=()
    for prompt in "${PROMPTS[@]}"; do
        [[ -f "$PROMPTS_ROOT/$prompt" ]] || missing_prompts+=("$prompt")
    done
    if [[ "${#missing_prompts[@]}" == 0 ]]; then
        record OK "prompts empacotados" "4 arquivos em usr/bin/_internal/prompts"
    else
        record FALHOU "prompts empacotados" "ausentes em usr/bin/_internal/prompts: ${missing_prompts[*]}"
    fi
    record INFO "conteúdo" "$(numfmt --to=iec-i --suffix=B "$TOTAL") extraído; ${#SOS[@]} .so"
else
    echo "falha ao extrair:"
    sed 's/^/  | /' "$WORK/extract.err"
    record FALHOU "extração" "--appimage-extract não gerou squashfs-root"
fi

# Arquivos auxiliares do build, quando estão ao lado do AppImage.
for aux in bundled-sizes.txt build-packages.txt; do
    if [[ -f "$SRC_DIR/$aux" ]]; then
        echo
        echo "$aux ($(wc -l <"$SRC_DIR/$aux") linhas; primeiras $TOP):"
        head -n "$TOP" "$SRC_DIR/$aux" | sed 's/^/  /'
    fi
done

section "Resumo"
printf '%s\n' "${RESULTS[@]}"
echo "RESULTADO: $([[ "$FAILED" == 0 ]] && echo OK || echo FALHOU)"
exit "$FAILED"
