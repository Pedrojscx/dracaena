#!/usr/bin/env bash
# matrix.sh <arquivo.AppImage>
#
# Mede a compatibilidade do AppImage em imagens limpas, sem instalar pacotes.
# Cada contêiner extrai o AppDir uma única vez e reutiliza essa extração para
# --version, --help, doctor, daemon --simulate + IPC e a escolha do navegador
# (Firefox padrão, Chromium padrão, nenhum). Os testes FUSE são separados
# porque exigem permissões do host: um na imagem limpa (sem fusermount não há
# montagem e o runtime orienta o uso de extract-and-run) e outro numa imagem
# com fuse3 instalado na hora, que prova que o runtime estático dispensa libfuse2.
set -euo pipefail

usage() {
    echo "uso: $0 <arquivo.AppImage>" >&2
    echo "variáveis: MATRIX_ONLY=<imagem|slug> MATRIX_REPORT=<arquivo.md> MATRIX_TIMEOUT=<segundos>" >&2
}

case "${1:-}" in
    -h|--help) usage; exit 0 ;;
    "") usage; exit 2 ;;
esac
[[ -f "$1" ]] || { echo "matrix.sh: arquivo não encontrado: $1" >&2; exit 2; }
command -v docker >/dev/null 2>&1 || { echo "matrix.sh: docker não encontrado" >&2; exit 2; }
docker info >/dev/null 2>&1 || { echo "matrix.sh: daemon docker indisponível" >&2; exit 2; }

APPIMAGE="$(readlink -f "$1")"
REPORT="${MATRIX_REPORT:-$HOME/wt/relatorios-appimage/MATRIZ.md}"
TIMEOUT="${MATRIX_TIMEOUT:-360}"
ONLY="${MATRIX_ONLY:-}"
REMOVE_PULLED="${MATRIX_REMOVE_PULLED:-1}"
WORK="$(mktemp -d "${TMPDIR:-/tmp}/appimage-matrix.XXXXXX")"
IPC="$WORK/appimage-ipc"
FAILED=0

# shellcheck disable=SC2329  # invocada indiretamente pelo trap EXIT
cleanup() {
    chmod -R u+rwX "$WORK" 2>/dev/null || true
    rm -rf "$WORK"
}
trap cleanup EXIT

# Derivado do cliente mínimo fornecido em /tmp/appimage-ipc.c. A compilação é
# feita no host para que as imagens medidas permaneçam intocadas.
cc -static -O2 -x c -o "$IPC" - <<'IPC_C'
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>

int main(int argc, char **argv) {
    int fd;
    struct sockaddr_un address = {0};
    const char request[] = "{\"v\":0,\"id\":1,\"cmd\":\"hello\",\"args\":{}}\n";
    char buffer[8192];
    ssize_t size;
    if (argc != 2 || strlen(argv[1]) >= sizeof(address.sun_path)) return 2;
    alarm(15);
    fd = socket(AF_UNIX, SOCK_STREAM, 0);
    if (fd < 0) return 3;
    address.sun_family = AF_UNIX;
    strcpy(address.sun_path, argv[1]);
    if (connect(fd, (struct sockaddr *)&address, sizeof(address)) < 0) return 4;
    if (write(fd, request, sizeof(request) - 1) != sizeof(request) - 1) return 5;
    size = read(fd, buffer, sizeof(buffer) - 1);
    if (size <= 0) return 6;
    buffer[size] = 0;
    fputs(buffer, stdout);
    close(fd);
    return 0;
}
IPC_C
chmod 0755 "$IPC"

# slug|rótulo|imagem|motivo de não suporte (vazio = suportada)
# Não suportada: só musl (Alpine). O AppImage é construído sobre glibc 2.28 e roda em
# qualquer glibc >= 2.28. A falha nas não suportadas é esperada e não reprova o job;
# só uma falha nas suportadas reprova.
IMAGES=(
    'ubuntu-20.04|Ubuntu 20.04|ubuntu:20.04|'
    'ubuntu-22.04|Ubuntu 22.04|ubuntu:22.04|'
    'ubuntu-24.04|Ubuntu 24.04|ubuntu:24.04|'
    'debian-11|Debian 11|debian:11|'
    'debian-12|Debian 12|debian:12|'
    'fedora-latest|Fedora latest|fedora:latest|'
    'archlinux-latest|Arch Linux latest|archlinux:latest|'
    'opensuse-tumbleweed|openSUSE Tumbleweed|opensuse/tumbleweed|'
    'almalinux-8|AlmaLinux 8|almalinux:8|'
    'almalinux-9|AlmaLinux 9|almalinux:9|'
    'alpine-latest|Alpine latest|alpine:latest|musl, sem glibc'
)

mkdir -p "$(dirname "$REPORT")"
ARTIFACT_SHA="$(sha256sum "$APPIMAGE" | awk '{print $1}')"
{
    echo '# Matriz de compatibilidade do AppImage'
    echo
    echo "Artefato: \`$(basename "$APPIMAGE")\`  "
    echo "SHA-256: \`$ARTIFACT_SHA\`  "
    echo "Gerada em: $(date -u '+%Y-%m-%d %H:%M:%S UTC')  "
    echo 'As imagens são executadas sem instalação de pacotes. **N-T** significa não testado.'
    echo
    # shellcheck disable=SC2016  # crases Markdown literais
    echo '| Distro | libc da imagem | `--version` | `--help` | `doctor` | daemon + IPC | navegador | extract-and-run | FUSE (limpa) | FUSE (+fuse3) | Primeira linha do erro |'
    echo '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|'
} >"$REPORT"

first_line() {
    local file="$1" line=''
    if [[ -f "$file" ]]; then
        IFS= read -r line <"$file" || true
    fi
    line="${line//$'\r'/}"
    [[ -n "$line" ]] || line='falha sem saída'
    printf '%s' "$line"
}

markdown() {
    local value="$1"
    value="${value//$'\n'/ }"
    value="${value//|/\\|}"
    printf '%s' "$value"
}

run_extracted() { # imagem diretório-da-linha
    local image="$1" rowdir="$2" rc=0
    timeout --kill-after=20 "$TIMEOUT" docker run --rm --platform linux/amd64 --network none -i \
        --mount "type=bind,source=$APPIMAGE,target=/work/app.AppImage,readonly" \
        --mount "type=bind,source=$IPC,target=/work/appimage-ipc,readonly" \
        --mount "type=bind,source=$rowdir,target=/result" \
        "$image" sh -s >"$rowdir/docker.out" 2>&1 <<'CONTAINER_SH' || rc=$?
set -u
work=/tmp/appimage-matrix
root=$work/squashfs-root
mkdir -p "$work/home" "$work/run" "$work/config" "$work/data"
chmod 700 "$work/run"

libc='desconhecida'
if command -v getconf >/dev/null 2>&1; then
    value="$(getconf GNU_LIBC_VERSION 2>/dev/null || true)"
    [ -n "$value" ] && libc="$value"
fi
if [ "$libc" = desconhecida ] && command -v ldd >/dev/null 2>&1; then
    ldd --version >"$work/ldd.out" 2>&1 || true
    first=''; second=''
    IFS= read -r first <"$work/ldd.out" || true
    second="$(sed -n '2p' "$work/ldd.out" 2>/dev/null || true)"
    case "$first" in
        *musl*) libc="$first${second:+; $second}" ;;
        '') ;;
        *) libc="$first" ;;
    esac
fi

version=FALHA
help=FALHA
doctor=FALHA
daemon=FALHA
browser=FALHA
extract=FALHA
error=''

remember_error() {
    file="$1"; fallback="$2"
    [ -n "$error" ] && return 0
    line=''
    [ -f "$file" ] && IFS= read -r line <"$file" || true
    error="${line:-$fallback}"
}

cd "$work" || exit 70
extract_rc=0
/work/app.AppImage --appimage-extract >"$work/extract.out" 2>&1 || extract_rc=$?
if [ "$extract_rc" -ne 0 ] || [ ! -x "$root/AppRun" ]; then
    remember_error "$work/extract.out" "extração falhou (exit $extract_rc)"
else
    extract=OK

    version_rc=0
    env HOME="$work/home" XDG_RUNTIME_DIR="$work/run" XDG_CONFIG_HOME="$work/config" \
        XDG_DATA_HOME="$work/data" APPIMAGE=/work/app.AppImage \
        "$root/AppRun" --version >"$work/version.out" 2>&1 || version_rc=$?
    version_line=''; IFS= read -r version_line <"$work/version.out" || true
    case "$version_line" in
        'dracaena '[0-9]*) [ "$version_rc" -eq 0 ] && version=OK ;;
    esac
    [ "$version" = OK ] || remember_error "$work/version.out" "--version falhou (exit $version_rc)"

    help_rc=0
    env HOME="$work/home" XDG_RUNTIME_DIR="$work/run" XDG_CONFIG_HOME="$work/config" \
        XDG_DATA_HOME="$work/data" APPIMAGE=/work/app.AppImage \
        "$root/AppRun" --help >"$work/help.out" 2>&1 || help_rc=$?
    if [ "$help_rc" -eq 0 ] && grep -qi 'dracaena' "$work/help.out" \
        && grep -Eqi 'usage|uso' "$work/help.out"; then
        help=OK
    else
        remember_error "$work/help.out" "--help falhou (exit $help_rc)"
    fi

    doctor_rc=0
    env HOME="$work/home" XDG_RUNTIME_DIR="$work/run" XDG_CONFIG_HOME="$work/config" \
        XDG_DATA_HOME="$work/data" APPIMAGE=/work/app.AppImage \
        "$root/AppRun" doctor >"$work/doctor.out" 2>&1 || doctor_rc=$?
    if { [ "$doctor_rc" -eq 0 ] || [ "$doctor_rc" -eq 1 ]; } \
        && grep -q '"checks"' "$work/doctor.out"; then
        doctor=OK
    else
        remember_error "$work/doctor.out" "doctor falhou (exit $doctor_rc)"
    fi

    rm -rf "$work/run/dracaena"
    env HOME="$work/home" XDG_RUNTIME_DIR="$work/run" XDG_CONFIG_HOME="$work/config" \
        XDG_DATA_HOME="$work/data" APPIMAGE=/work/app.AppImage \
        "$root/AppRun" daemon --simulate >"$work/daemon.out" 2>&1 &
    daemon_pid=$!
    waited=0
    while [ ! -S "$work/run/dracaena/ctl.sock" ] && kill -0 "$daemon_pid" 2>/dev/null \
        && [ "$waited" -lt 30 ]; do
        sleep 1
        waited=$((waited + 1))
    done
    ipc_rc=1
    if [ -S "$work/run/dracaena/ctl.sock" ]; then
        ipc_rc=0
        /work/appimage-ipc "$work/run/dracaena/ctl.sock" >"$work/ipc.out" 2>&1 || ipc_rc=$?
    else
        echo 'socket IPC não apareceu em 30 s' >"$work/ipc.out"
    fi
    if [ "$ipc_rc" -eq 0 ] && grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' "$work/ipc.out"; then
        daemon=OK
    else
        remember_error "$work/ipc.out" "IPC falhou (exit $ipc_rc)"
    fi
    kill "$daemon_pid" 2>/dev/null || true
    wait "$daemon_pid" 2>/dev/null || true

    # Navegador: três cenários simulados com stubs em PATH (nada é instalado).
    # xdg-settings devolve o .desktop do navegador padrão fingido; Firefox e
    # nenhum devem usar o Chromium embutido (dracaena-browsers), e um Chromium
    # padrão deve ser usado como está. BROWSER_BIN fica vazio em todos os casos.
    stubs="$work/stubs"
    mkdir -p "$stubs" "$work/data/applications"
    printf '#!/bin/sh\necho "Mozilla Firefox 130.0"\n' >"$stubs/firefox"
    printf '#!/bin/sh\necho "Chromium 156.0.0.0"\n' >"$stubs/chromium"
    cat >"$stubs/xdg-settings" <<'XDG_STUB'
#!/bin/sh
[ "$1 $2" = "get default-web-browser" ] || exit 2
[ -n "${FAKE_DEFAULT:-}" ] || exit 1
echo "$FAKE_DEFAULT"
XDG_STUB
    chmod 0755 "$stubs/firefox" "$stubs/chromium" "$stubs/xdg-settings"
    printf '[Desktop Entry]\nName=Firefox\nExec=%s %%u\n' "$stubs/firefox" >"$work/data/applications/firefox.desktop"
    printf '[Desktop Entry]\nName=Chromium\nExec=%s %%U\n' "$stubs/chromium" >"$work/data/applications/chromium.desktop"
    browser=OK
    browser_case() { # rótulo id-do-.desktop (vazio = nenhum) esperado (embutido|caminho do stub)
        label="$1"; desktop="$2"; want="$3"
        base="$work/browser-$label"
        env HOME="$work/home" XDG_RUNTIME_DIR="$work/run" XDG_CONFIG_HOME="$work/config" \
            XDG_DATA_HOME="$work/data" APPIMAGE=/work/app.AppImage PATH="$stubs:$PATH" \
            FAKE_DEFAULT="$desktop" "$root/AppRun" doctor >"$base.doctor" 2>&1 </dev/null || true
        install_rc=0
        env HOME="$work/home" XDG_RUNTIME_DIR="$work/run" XDG_CONFIG_HOME="$work/config" \
            XDG_DATA_HOME="$work/data" APPIMAGE=/work/app.AppImage PATH="$stubs:$PATH" \
            FAKE_DEFAULT="$desktop" "$root/AppRun" install-browser >"$base.install" 2>&1 </dev/null || install_rc=$?
        check="$(tr -d '\n' <"$base.doctor" \
            | grep -Eo '\{[^{}]*"name"[[:space:]]*:[[:space:]]*"browser"[^{}]*\}' | head -n 1 || true)"
        good=1
        printf '%s' "$check" | grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' || good=0
        grep -Eq '"ok"[[:space:]]*:[[:space:]]*true' "$base.install" || good=0
        [ "$install_rc" -eq 0 ] || good=0
        if [ "$want" = embutido ]; then
            printf '%s' "$check" | grep -Fq 'dracaena-browsers' || good=0
            grep -Fq 'dracaena-browsers' "$base.install" || good=0
        else
            printf '%s' "$check" | grep -Fq "$want" || good=0
            grep -Fq "$want" "$base.install" || good=0
            if grep -Fq 'dracaena-browsers' "$base.install"; then good=0; fi
        fi
        if [ "$good" -ne 1 ]; then
            browser=FALHA
            detail="${check:-doctor sem o check browser}"
            echo "navegador ($label): esperado $want; doctor: $(printf '%s' "$detail" | cut -c1-200)" >"$work/browser.err"
            remember_error "$work/browser.err" "navegador ($label) falhou"
        fi
    }
    browser_case firefox firefox.desktop embutido
    browser_case chromium chromium.desktop "$stubs/chromium"
    browser_case nenhum '' embutido
fi

[ -n "$error" ] || error='-'
printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$libc" "$version" "$help" "$doctor" "$daemon" "$browser" "$extract" "$error" > /result/row.tsv
CONTAINER_SH
    if [[ "$rc" -ne 0 && ! -s "$rowdir/row.tsv" ]]; then
        return "$rc"
    fi
    return 0
}

# Instala fuse3 (sem libfuse2) no contêiner e roda o AppImage em modo FUSE.
# Códigos de saída 90-92 significam "não foi possível testar", não falha do pacote.
# shellcheck disable=SC2016  # o script roda no contêiner; nada deve expandir aqui
FUSE3_SH='
set -u
if command -v apt-get >/dev/null 2>&1; then
    export DEBIAN_FRONTEND=noninteractive
    install() { apt-get update -qq && apt-get install -y -qq --no-install-recommends fuse3; }
elif command -v dnf >/dev/null 2>&1; then install() { dnf install -y -q fuse3; }
elif command -v zypper >/dev/null 2>&1; then install() { zypper -n -q install fuse3; }
elif command -v pacman >/dev/null 2>&1; then install() { pacman -Sy --noconfirm fuse3; }
elif command -v apk >/dev/null 2>&1; then install() { apk add -q fuse3; }
else echo "gerenciador de pacotes desconhecido"; exit 90; fi
install >/tmp/fuse3-install.log 2>&1 || { echo "falha ao instalar fuse3: $(tail -n 1 /tmp/fuse3-install.log)"; exit 90; }
command -v fusermount3 >/dev/null 2>&1 || { echo "fusermount3 ausente após instalar fuse3"; exit 90; }
for dir in /lib /lib64 /usr/lib /usr/lib64; do
    if [ -d "$dir" ] && find "$dir" -name "libfuse.so.2*" 2>/dev/null | grep -q .; then
        echo "libfuse2 presente na imagem: o teste não provaria a ausência dela"; exit 92
    fi
done
exec /work/app.AppImage --version
'

fuse_not_testable() { # modo rc arquivo-de-saída
    if [[ "$1" == fuse3 ]]; then
        [[ "$2" -ge 90 && "$2" -le 92 ]]
    else
        [[ "$2" -eq 125 ]] || grep -Eqi 'operation not permitted|permission denied|error gathering device|no such file.*fuse|libfuse\.so\.2|fusermount' "$3"
    fi
}

run_fuse() { # imagem diretório-da-linha modo(limpa|fuse3); imprime status
    local image="$1" rowdir="$2" mode="$3" rc=0 line='' out
    out="$rowdir/fuse-$mode.out"
    if [[ ! -c /dev/fuse ]]; then
        echo 'N-T'
        echo 'host sem /dev/fuse' >"$rowdir/fuse-$mode.reason"
        return 0
    fi
    # Em hosts com AppArmor (ex.: runner ubuntu-24.04), o perfil docker-default nega
    # mount dentro do contêiner; sem isso o FUSE falharia por causa do host, não do pacote.
    local -a args=(--platform linux/amd64 --device /dev/fuse --cap-add SYS_ADMIN
        --security-opt apparmor=unconfined
        --mount "type=bind,source=$APPIMAGE,target=/work/app.AppImage,readonly")
    if [[ "$mode" == fuse3 ]]; then
        timeout --kill-after=10 300 docker run --rm "${args[@]}" "$image" sh -c "$FUSE3_SH" >"$out" 2>&1 || rc=$?
    else
        timeout --kill-after=10 90 docker run --rm --network none "${args[@]}" "$image" /work/app.AppImage --version >"$out" 2>&1 || rc=$?
    fi
    IFS= read -r line <"$out" || true
    if [[ "$rc" -eq 0 && "$line" == 'dracaena '[0-9]* ]]; then
        echo 'OK'
    # Imagem limpa sem fusermount: o runtime orienta usar extract-and-run, é N-T.
    # Com fuse3 instalado, só os códigos 90-92 (instalação/ambiente) são N-T; o resto é FALHA.
    elif fuse_not_testable "$mode" "$rc" "$out"; then
        echo 'N-T'
        cp "$out" "$rowdir/fuse-$mode.reason"
    else
        echo 'FALHA'
    fi
}

for spec in "${IMAGES[@]}"; do
    IFS='|' read -r slug distro image unsupported <<<"$spec"
    if [[ -n "$ONLY" && "$ONLY" != "$slug" && "$ONLY" != "$image" ]]; then
        continue
    fi

    echo "[matriz] $distro ($image)" >&2
    rowdir="$WORK/$slug"
    mkdir "$rowdir"
    preexisting=0
    docker image inspect "$image" >/dev/null 2>&1 && preexisting=1

    libc='desconhecida'
    version=FALHA
    help=FALHA
    doctor=FALHA
    daemon=FALHA
    browser=FALHA
    extract=FALHA
    error=''
    if run_extracted "$image" "$rowdir" && [[ -s "$rowdir/row.tsv" ]]; then
        IFS=$'\t' read -r libc version help doctor daemon browser extract error <"$rowdir/row.tsv"
        [[ "$error" == '-' ]] && error=''
    else
        error="$(first_line "$rowdir/docker.out")"
    fi

    fuse="$(run_fuse "$image" "$rowdir" limpa)"
    fuse3="$(run_fuse "$image" "$rowdir" fuse3)"
    for mode in limpa fuse3; do
        status=$fuse; [[ "$mode" == fuse3 ]] && status=$fuse3
        if [[ "$status" == FALHA && -z "$error" ]]; then
            error="$(first_line "$rowdir/fuse-$mode.out")"
        elif [[ "$status" == N-T && -z "$error" && -f "$rowdir/fuse-$mode.reason" ]]; then
            error="$(first_line "$rowdir/fuse-$mode.reason")"
        fi
    done
    [[ -n "$error" ]] || error='—'

    label="$distro"
    [[ -z "$unsupported" ]] || label="$distro (não suportado, falha esperada: $unsupported)"
    printf '| %s | %s | %s | %s | %s | %s | %s | %s | %s | %s | %s |\n' \
        "$(markdown "$label")" "$(markdown "$libc")" "$version" "$help" "$doctor" \
        "$daemon" "$browser" "$extract" "$fuse" "$fuse3" "$(markdown "$error")" >>"$REPORT"

    failed_here=0
    if [[ "$version" == FALHA || "$help" == FALHA || "$doctor" == FALHA \
        || "$daemon" == FALHA || "$browser" == FALHA || "$extract" == FALHA || "$fuse" == FALHA || "$fuse3" == FALHA ]]; then
        failed_here=1
    fi
    if [[ -n "$unsupported" ]]; then
        # Falha esperada: não reprova. Se passar, avisa para revisar a lista de não suportados.
        if [[ "$failed_here" -eq 0 ]]; then
            echo "[matriz] aviso: $distro ($unsupported) passou em tudo; revise a lista de não suportados" >&2
        fi
    elif [[ "$failed_here" -eq 1 ]]; then
        echo "[matriz] REGRESSÃO: $distro é suportada e falhou" >&2
        FAILED=1
    fi

    if [[ "$preexisting" -eq 0 && "$REMOVE_PULLED" == 1 ]] && docker image inspect "$image" >/dev/null 2>&1; then
        echo "[matriz] removendo imagem baixada por esta execução: $image" >&2
        docker image rm "$image" >/dev/null || echo "[matriz] aviso: não foi possível remover $image" >&2
    fi
done

if [[ -n "$ONLY" ]] && ! grep -q '^| ' "$REPORT"; then
    echo "matrix.sh: MATRIX_ONLY não reconhecido: $ONLY" >&2
    exit 2
fi

echo "[matriz] relatório: $REPORT" >&2
exit "$FAILED"
